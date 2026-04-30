"""
Pure-Python PDF parser and text extractor.

Supports:
- Classic cross-reference tables (PDF 1.0–1.4)
- Cross-reference streams (PDF 1.5+)
- /Prev chain traversal for incremental updates
- Document-order page traversal via the /Pages tree
- Tj, TJ, ' and " text-show operators
- Literal and hex-encoded PDF strings
- FlateDecode (zlib) compressed content streams
- Metadata extraction from the /Info dictionary

Limitations:
- No font/encoding remapping; text decoded as Latin-1
- No support for encrypted (password-protected) PDFs
- Object streams (PDF 1.5 ObjStm) not decoded
"""
from __future__ import annotations

import re
import zlib
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple

from .schema import ExtractionResult, PageResult


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class PDFParseError(Exception):
    """Raised when fundamental PDF structure cannot be read."""


# ---------------------------------------------------------------------------
# Low-level binary helpers
# ---------------------------------------------------------------------------

def _read_be_int(data: bytes, start: int, width: int) -> int:
    """Read a big-endian unsigned integer of *width* bytes."""
    if width == 0:
        return 1  # default type field value in xref streams
    value = 0
    for byte in data[start : start + width]:
        value = (value << 8) | byte
    return value


def _decompress(raw: bytes) -> bytes:
    """Attempt zlib decompression; return *raw* unchanged on failure."""
    for wbits in (15, -15):
        try:
            return zlib.decompress(raw, wbits)
        except zlib.error:
            pass
    return raw


# ---------------------------------------------------------------------------
# Indirect object parsing
# ---------------------------------------------------------------------------

def _parse_obj_at(data: bytes, offset: int) -> Tuple[int, bytes]:
    """Return *(obj_id, body_bytes)* for the indirect object at *offset*.

    Reads up to 64 KiB from *offset*; raises :class:`PDFParseError` if the
    ``N G obj`` marker is absent.
    """
    chunk = data[offset : offset + 65536]
    m = re.search(rb"(\d+)\s+\d+\s+obj\b", chunk)
    if not m:
        raise PDFParseError(f"obj marker not found at offset {offset}")
    start = m.end()
    end_m = re.search(rb"\bendobj\b", chunk[start:])
    body = chunk[start : start + end_m.start()] if end_m else chunk[start:]
    return int(m.group(1)), body


def _extract_stream_bytes(obj_body: bytes) -> Optional[bytes]:
    """Extract and decompress the stream payload from an object body.

    Returns *None* if the object has no stream.
    """
    m = re.search(rb"stream\r?\n", obj_body)
    if not m:
        return None
    start = m.end()
    end_m = re.search(rb"\bendstream\b", obj_body[start:])
    raw = obj_body[start : start + (end_m.start() if end_m else len(obj_body))]
    header = obj_body[:start]
    if b"FlateDecode" in header:
        raw = _decompress(raw)
    return raw


# ---------------------------------------------------------------------------
# Cross-reference parsing
# ---------------------------------------------------------------------------

def _find_startxref(data: bytes) -> int:
    """Return the byte offset stored in the ``startxref`` trailer token."""
    tail = data[-2048:]
    m = re.search(rb"startxref\s+(\d+)\s*(?:%%EOF)?", tail)
    if not m:
        raise PDFParseError("startxref not found in file tail")
    return int(m.group(1))


def _parse_xref_table(
    data: bytes, offset: int
) -> Tuple[Dict[int, int], Optional[int]]:
    """Parse a classic ``xref`` table.

    Returns a mapping ``{obj_id: byte_offset}`` and the ``/Prev`` offset (or
    *None* if absent).
    """
    offsets: Dict[int, int] = {}
    # Read up to 1 MiB — large xref tables can be hundreds of KB
    end = min(offset + 1_048_576, len(data))
    chunk = data[offset:end].decode("latin-1", errors="replace")
    lines = chunk.splitlines()

    i = 0
    if i < len(lines) and lines[i].strip() == "xref":
        i += 1

    while i < len(lines):
        line = lines[i].strip()
        if line == "trailer":
            i += 1
            break
        m = re.match(r"(\d+)\s+(\d+)$", line)
        if not m:
            i += 1
            continue
        first_obj, count = int(m.group(1)), int(m.group(2))
        i += 1
        for j in range(count):
            if i >= len(lines):
                break
            parts = lines[i].strip().split()
            i += 1
            if len(parts) >= 3 and parts[2] == "n":
                offsets[first_obj + j] = int(parts[0])

    # Locate /Prev in the trailer dictionary
    trailer_text = "\n".join(lines[i : i + 60])
    pm = re.search(r"/Prev\s+(\d+)", trailer_text)
    return offsets, (int(pm.group(1)) if pm else None)


def _parse_xref_stream(
    data: bytes, offset: int
) -> Tuple[Dict[int, int], Optional[int]]:
    """Parse a cross-reference stream (PDF 1.5+).

    Returns ``{obj_id: byte_offset}`` and the ``/Prev`` offset (or *None*).
    Falls back to an empty map on any parse error.
    """
    offsets: Dict[int, int] = {}
    try:
        _, obj_body = _parse_obj_at(data, offset)
        stream = _extract_stream_bytes(obj_body)
        if stream is None:
            return offsets, None

        # /W [type_width  offset_width  gen_width]
        w_m = re.search(rb"/W\s*\[\s*([\d\s]+?)\s*\]", obj_body)
        if not w_m:
            return offsets, None
        w = [int(x) for x in w_m.group(1).split()]
        if len(w) < 3 or sum(w) == 0:
            return offsets, None
        entry_size = sum(w)

        # /Index defaults to [0 /Size]
        idx_m = re.search(rb"/Index\s*\[\s*([\d\s]+?)\s*\]", obj_body)
        if idx_m:
            idx_vals = [int(x) for x in idx_m.group(1).split()]
            subsections = [
                (idx_vals[k], idx_vals[k + 1])
                for k in range(0, len(idx_vals) - 1, 2)
            ]
        else:
            size_m = re.search(rb"/Size\s+(\d+)", obj_body)
            size = int(size_m.group(1)) if size_m else 0
            subsections = [(0, size)]

        pos = 0
        for first_obj, count in subsections:
            for j in range(count):
                if pos + entry_size > len(stream):
                    break
                entry = stream[pos : pos + entry_size]
                pos += entry_size
                f1 = _read_be_int(entry, 0, w[0])
                f2 = _read_be_int(entry, w[0], w[1])
                if f1 == 1:  # in-use, uncompressed object
                    offsets[first_obj + j] = f2

        prev_m = re.search(rb"/Prev\s+(\d+)", obj_body)
        return offsets, (int(prev_m.group(1)) if prev_m else None)
    except Exception:
        return offsets, None


def _load_full_xref(data: bytes) -> Dict[int, int]:
    """Build the complete xref map, following ``/Prev`` chains.

    Newer entries (from later xref sections) take precedence over older ones,
    as required by the PDF specification.
    """
    offset = _find_startxref(data)
    visited: Set[int] = set()
    chains: List[Dict[int, int]] = []

    while offset not in visited:
        visited.add(offset)
        # Distinguish classic xref table from xref stream by first non-blank bytes
        probe = data[offset : offset + 16].lstrip()
        if probe.startswith(b"xref"):
            offsets, prev = _parse_xref_table(data, offset)
        else:
            offsets, prev = _parse_xref_stream(data, offset)
        chains.append(offsets)
        if prev is None:
            break
        offset = prev

    # Apply oldest-first so newest entries win
    combined: Dict[int, int] = {}
    for chain in reversed(chains):
        combined.update(chain)
    return combined


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

_INFO_KEYS = (
    "Title",
    "Author",
    "Subject",
    "Keywords",
    "Creator",
    "Producer",
    "CreationDate",
)


def _extract_metadata(data: bytes, xref: Dict[int, int]) -> Dict[str, str]:
    """Extract document information from the PDF ``/Info`` dictionary."""
    metadata: Dict[str, str] = {}
    # Search the tail of the file for the trailer /Info reference
    tail = data[-65536:].decode("latin-1", errors="replace")
    info_m = re.search(r"/Info\s+(\d+)\s+\d+\s+R", tail)
    if not info_m:
        return metadata
    info_id = int(info_m.group(1))
    if info_id not in xref:
        return metadata
    try:
        _, obj_body = _parse_obj_at(data, xref[info_id])
    except PDFParseError:
        return metadata

    for key in _INFO_KEYS:
        pattern = rb"/" + key.encode() + rb"\s*(\([^)]*\)|<[^>]*>)"
        m = re.search(pattern, obj_body)
        if not m:
            continue
        raw = m.group(1)
        if raw.startswith(b"("):
            value = _decode_pdf_string(raw[1:-1])
        else:
            value = _decode_hex_string(raw[1:-1])
        value = value.strip()
        if value:
            metadata[key] = value
    return metadata


# ---------------------------------------------------------------------------
# Page tree traversal
# ---------------------------------------------------------------------------

def _collect_page_ids(
    data: bytes,
    xref: Dict[int, int],
    node_id: int,
    visited: Optional[Set[int]] = None,
) -> List[int]:
    """Recursively collect leaf ``/Page`` object IDs from the page tree.

    Follows the ``/Kids`` arrays in ``/Pages`` (intermediate) nodes and
    returns the IDs of terminal ``/Page`` nodes in document order.  A
    *visited* set guards against malformed circular references.
    """
    if visited is None:
        visited = set()
    if node_id in visited or node_id not in xref:
        return []
    visited.add(node_id)

    try:
        _, obj_body = _parse_obj_at(data, xref[node_id])
    except PDFParseError:
        return []

    if re.search(rb"/Type\s*/Pages\b", obj_body):
        kids_m = re.search(rb"/Kids\s*\[([^\]]+)\]", obj_body)
        if not kids_m:
            return []
        ids: List[int] = []
        for ref_m in re.finditer(rb"(\d+)\s+\d+\s+R", kids_m.group(1)):
            ids.extend(_collect_page_ids(data, xref, int(ref_m.group(1)), visited))
        return ids

    if re.search(rb"/Type\s*/Page\b", obj_body):
        return [node_id]

    return []


def _find_pages_root(data: bytes, xref: Dict[int, int]) -> Optional[int]:
    """Return the obj_id of the ``/Pages`` root node.

    Reads the document catalogue via the ``/Root`` reference in the trailer.
    """
    tail = data[-65536:].decode("latin-1", errors="replace")
    root_m = re.search(r"/Root\s+(\d+)\s+\d+\s+R", tail)
    if not root_m:
        return None
    root_id = int(root_m.group(1))
    if root_id not in xref:
        return None
    try:
        _, catalog = _parse_obj_at(data, xref[root_id])
    except PDFParseError:
        return None
    pages_m = re.search(rb"/Pages\s+(\d+)\s+\d+\s+R", catalog)
    return int(pages_m.group(1)) if pages_m else None


# ---------------------------------------------------------------------------
# PDF string decoders
# ---------------------------------------------------------------------------

def _decode_pdf_string(s: bytes) -> str:
    """Decode a PDF literal string, handling ``\\ooo`` octal and escapes."""
    out: List[str] = []
    i = 0
    while i < len(s):
        b = s[i : i + 1]
        if b == b"\\":
            i += 1
            if i >= len(s):
                break
            nc = s[i : i + 1]
            if nc == b"n":
                out.append("\n")
            elif nc == b"r":
                out.append("\r")
            elif nc == b"t":
                out.append("\t")
            elif nc in (b"(", b")", b"\\"):
                out.append(nc.decode("latin-1"))
            elif nc.isdigit():
                # Octal: 1–3 digits
                octal_raw = s[i : i + 3].decode("latin-1", errors="replace")
                om = re.match(r"([0-7]{1,3})", octal_raw)
                if om:
                    out.append(chr(int(om.group(1), 8)))
                    i += len(om.group(1)) - 1
                else:
                    out.append(nc.decode("latin-1", errors="replace"))
            else:
                out.append(nc.decode("latin-1", errors="replace"))
        else:
            out.append(b.decode("latin-1", errors="replace"))
        i += 1
    return "".join(out)


def _decode_hex_string(s: bytes) -> str:
    """Decode a PDF hex string (without surrounding angle brackets)."""
    cleaned = re.sub(rb"\s+", b"", s)
    if len(cleaned) % 2:
        cleaned += b"0"
    try:
        raw = bytes.fromhex(cleaned.decode("ascii", errors="replace"))
        return raw.decode("latin-1", errors="replace")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Text extraction from content streams
# ---------------------------------------------------------------------------

# Compiled once for performance
_BT_ET_RE = re.compile(rb"\bBT\b(.+?)\bET\b", re.DOTALL)
_TJ_ITEM_RE = re.compile(
    rb"(\((?:[^)(\\]|\\.)*\))"   # literal string
    rb"|(<[0-9a-fA-F\s]+>)"      # hex string
    rb"|(-?\d+(?:\.\d*)?)"       # numeric (kerning / spacing)
)
_TOKEN_RE = re.compile(
    rb"(\((?:[^)(\\]|\\.|\((?:[^)(\\]|\\.)*\))*\))"  # (literal string)
    rb"|(<[0-9a-fA-F\s]+>)"                           # <hex string>
    rb"|(\[(?:[^\[\]]*)\])"                           # [TJ array]
    rb"|([A-Za-z'\"*]+)"                              # operator / name
)


def _decode_tj_array(arr_content: bytes) -> str:
    """Decode a TJ array, inserting a space for large negative kerning gaps."""
    parts: List[str] = []
    for m in _TJ_ITEM_RE.finditer(arr_content):
        lit, hex_s, num = m.group(1), m.group(2), m.group(3)
        if lit:
            parts.append(_decode_pdf_string(lit[1:-1]))
        elif hex_s:
            parts.append(_decode_hex_string(hex_s[1:-1]))
        elif num:
            try:
                if float(num) < -100:
                    parts.append(" ")
            except ValueError:
                pass
    return "".join(parts)


def _extract_text_from_stream(stream: bytes) -> str:
    """Extract human-readable text from a PDF content stream.

    Processes every ``BT … ET`` text block, tokenising strings and operators.
    Handles ``Tj``, ``TJ``, ``'`` and ``"`` (show-string) operators.
    """
    parts: List[str] = []

    for bt_block in _BT_ET_RE.finditer(stream):
        block = bt_block.group(1)
        pending: List[str] = []

        for m in _TOKEN_RE.finditer(block):
            lit, hex_s, arr, op = (
                m.group(1), m.group(2), m.group(3), m.group(4)
            )

            if lit is not None:
                pending.append(_decode_pdf_string(lit[1:-1]))
            elif hex_s is not None:
                pending.append(_decode_hex_string(hex_s[1:-1]))
            elif arr is not None:
                pending.append(_decode_tj_array(arr[1:-1]))
            elif op in (b"Tj", b"TJ", b"'", b'"'):
                parts.extend(pending)
                pending.clear()
            else:
                # Any other operator resets the operand stack
                pending.clear()

    text = " ".join(p for p in parts if p.strip())
    return re.sub(r" +", " ", text).strip()


# ---------------------------------------------------------------------------
# Main extractor class
# ---------------------------------------------------------------------------

class PDFExtractor:
    """Extract text and metadata from a PDF file without external binaries.

    Parameters
    ----------
    path : str or pathlib.Path
        Path to the PDF file.
    max_pages : int, optional
        Stop after this many pages (0 = all pages, the default).

    Examples
    --------
    >>> extractor = PDFExtractor("paper.pdf")
    >>> result = extractor.extract()
    >>> print(result.full_text[:200])
    """

    def __init__(self, path: str, max_pages: int = 0) -> None:
        self.path = Path(path)
        self.max_pages = max_pages
        self._data: bytes = b""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Read the PDF bytes and validate the magic number."""
        if not self.path.is_file():
            raise PDFParseError(f"File not found: {self.path}")
        self._data = self.path.read_bytes()
        if not self._data.startswith(b"%PDF"):
            raise PDFParseError(f"Not a valid PDF file: {self.path}")

    def _get_page_ids(self, xref: Dict[int, int]) -> List[int]:
        """Return document-order page object IDs.

        Tries the ``/Pages`` tree first; falls back to scanning all objects
        for ``/Type /Page`` entries (handles malformed page trees).
        """
        pages_root = _find_pages_root(self._data, xref)
        if pages_root is not None:
            ids = _collect_page_ids(self._data, xref, pages_root)
            if ids:
                return ids
        # Fallback: linear scan in object-ID order
        ids = []
        for obj_id in sorted(xref.keys()):
            try:
                _, body = _parse_obj_at(self._data, xref[obj_id])
                if re.search(rb"/Type\s*/Page\b", body):
                    ids.append(obj_id)
            except PDFParseError:
                continue
        return ids

    def _get_content_stream(
        self, page_id: int, xref: Dict[int, int]
    ) -> Optional[bytes]:
        """Return the concatenated content stream(s) for a page object.

        A page's ``/Contents`` value may be a single indirect reference or an
        array of references; both forms are handled.
        """
        try:
            _, page_body = _parse_obj_at(self._data, xref[page_id])
        except PDFParseError:
            return None

        # /Contents may be "5 0 R" or "[5 0 R 6 0 R ...]"
        contents_m = re.search(
            rb"/Contents\s*([\d\s\[\]R]+)", page_body
        )
        if not contents_m:
            return None

        ref_str = contents_m.group(1).strip()
        if ref_str.startswith(b"["):
            ref_str = ref_str[1:].split(b"]")[0]

        streams: List[bytes] = []
        for ref_m in re.finditer(rb"(\d+)\s+\d+\s+R", ref_str):
            ref_id = int(ref_m.group(1))
            if ref_id not in xref:
                continue
            try:
                _, ref_body = _parse_obj_at(self._data, xref[ref_id])
                s = _extract_stream_bytes(ref_body)
                if s is not None:
                    streams.append(s)
            except PDFParseError:
                continue

        # Some PDFs embed the content stream directly in the page object
        if not streams:
            s = _extract_stream_bytes(page_body)
            if s is not None:
                streams.append(s)

        return b"\n".join(streams) if streams else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self) -> ExtractionResult:
        """Run the extraction pipeline.

        Returns
        -------
        ExtractionResult
            Structured result containing per-page text, document metadata,
            and any non-fatal errors encountered.

        Raises
        ------
        PDFParseError
            If the file is missing or does not begin with ``%PDF``.
        """
        self._load()
        result = ExtractionResult(source=self.path.name, page_count=0)

        try:
            xref = _load_full_xref(self._data)
        except PDFParseError as exc:
            result.errors.append(f"xref error: {exc}")
            return result

        result.metadata = _extract_metadata(self._data, xref)

        page_ids = self._get_page_ids(xref)
        if self.max_pages:
            page_ids = page_ids[: self.max_pages]

        pages: List[PageResult] = []
        for page_num, page_id in enumerate(page_ids, start=1):
            stream = self._get_content_stream(page_id, xref)
            if stream is None:
                pages.append(PageResult(page_number=page_num, text=""))
                continue
            try:
                text = _extract_text_from_stream(stream)
            except Exception as exc:
                result.errors.append(f"page {page_num}: {exc}")
                text = ""
            pages.append(PageResult(page_number=page_num, text=text))

        result.pages = pages
        result.page_count = len(pages)
        return result
