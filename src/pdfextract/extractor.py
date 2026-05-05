"""PDF parsing and text-extraction engine."""
from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple, Union

from .schema import ExtractionResult, PDFParseError, PageResult


# ---------------------------------------------------------------------------
# Low-level byte helpers
# ---------------------------------------------------------------------------

def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _find_xref_offset(data: bytes) -> int:
    """Locate startxref offset by scanning the last 1 KiB of the file."""
    tail = data[-1024:]
    m = re.search(rb"startxref\s+(\d+)", tail)
    if not m:
        raise PDFParseError("startxref not found — file may be corrupt or not a PDF.")
    return int(m.group(1))


def _parse_xref_table(data: bytes, offset: int) -> Dict[int, int]:
    """
    Parse a classic cross-reference table. Returns {obj_id: byte_offset}.

    Falls back gracefully when the table is partial or malformed.
    """
    offsets: Dict[int, int] = {}
    # Use a generous window; large xref sections can exceed 4 KiB.
    window = data[offset: offset + 524288].decode("latin-1", errors="replace")
    lines = window.splitlines()
    i = 0
    if i < len(lines) and lines[i].strip() == "xref":
        i += 1
    while i < len(lines):
        header = lines[i].strip()
        m = re.match(r"(\d+)\s+(\d+)", header)
        if not m:
            break
        first_obj = int(m.group(1))
        count = int(m.group(2))
        i += 1
        for j in range(count):
            if i >= len(lines):
                break
            entry = lines[i].strip()
            i += 1
            parts = entry.split()
            if len(parts) < 3:
                continue
            byte_off, _gen, kind = parts[0], parts[1], parts[2]
            if kind == "n":
                offsets[first_obj + j] = int(byte_off)
    return offsets


def _parse_xref_stream(data: bytes, offset: int) -> Dict[int, int]:
    """
    Parse a PDF 1.5+ cross-reference stream object.
    Returns {obj_id: byte_offset} for in-use entries (type 1).
    """
    offsets: Dict[int, int] = {}
    chunk = data[offset: offset + 65536]
    obj_m = re.search(rb"\d+\s+\d+\s+obj", chunk)
    if not obj_m:
        return offsets
    body = chunk[obj_m.end():]

    # Extract /W (field widths) and /Index (or default [0 /Size])
    w_m = re.search(rb"/W\s*\[\s*([\d\s]+)\]", body)
    if not w_m:
        return offsets
    widths = [int(x) for x in w_m.group(1).split()]
    if len(widths) < 3:
        return offsets
    w1, w2, w3 = widths[0], widths[1], widths[2]

    size_m = re.search(rb"/Size\s+(\d+)", body)
    total = int(size_m.group(1)) if size_m else 0

    index_m = re.search(rb"/Index\s*\[\s*([\d\s]+)\]", body)
    if index_m:
        idx_vals = [int(x) for x in index_m.group(1).split()]
        subsections = [(idx_vals[k], idx_vals[k + 1]) for k in range(0, len(idx_vals) - 1, 2)]
    else:
        subsections = [(0, total)]

    stream_m = re.search(rb"stream\r?\n", body)
    if not stream_m:
        return offsets
    raw_stream = body[stream_m.end():]
    end_m = re.search(rb"endstream", raw_stream)
    if end_m:
        raw_stream = raw_stream[: end_m.start()]
    if b"FlateDecode" in body[: stream_m.start()]:
        try:
            raw_stream = zlib.decompress(raw_stream)
        except zlib.error:
            try:
                raw_stream = zlib.decompress(raw_stream, -15)
            except zlib.error:
                return offsets

    entry_size = w1 + w2 + w3
    if entry_size == 0:
        return offsets

    pos = 0
    for first_obj, count in subsections:
        for j in range(count):
            if pos + entry_size > len(raw_stream):
                break
            entry = raw_stream[pos: pos + entry_size]
            pos += entry_size

            def _int(b: bytes) -> int:
                return int.from_bytes(b, "big") if b else 0

            field1 = _int(entry[:w1]) if w1 else 1
            field2 = _int(entry[w1: w1 + w2])
            # field3 not needed for type-1 entries
            if field1 == 1:  # in-use, field2 = byte offset
                offsets[first_obj + j] = field2
    return offsets


def _get_xref(data: bytes) -> Dict[int, int]:
    """Return the cross-reference table, supporting both classic and stream forms."""
    offset = _find_xref_offset(data)
    # Peek at what's at that offset to decide which parser to use.
    peek = data[offset: offset + 32].lstrip()
    if peek.startswith(b"xref"):
        offsets = _parse_xref_table(data, offset)
    else:
        # Likely a cross-reference stream (PDF 1.5+).
        offsets = _parse_xref_stream(data, offset)
    if not offsets:
        raise PDFParseError("Cross-reference table is empty or could not be parsed.")
    return offsets


# ---------------------------------------------------------------------------
# Object parsing
# ---------------------------------------------------------------------------

def _parse_obj(data: bytes, byte_off: int) -> Tuple[int, bytes]:
    """Return (obj_id, raw_body_bytes) for an indirect object."""
    chunk = data[byte_off: byte_off + 65536]
    m = re.search(rb"(\d+)\s+\d+\s+obj", chunk)
    if not m:
        raise PDFParseError("obj marker not found at offset %d" % byte_off)
    start = m.end()
    end_m = re.search(rb"\bendobj\b", chunk[start:])
    body = chunk[start: start + (end_m.start() if end_m else len(chunk) - start)]
    return int(m.group(1)), body


# ---------------------------------------------------------------------------
# Stream decoding
# ---------------------------------------------------------------------------

def _decode_flate(raw: bytes) -> bytes:
    """Decompress a FlateDecode stream, tolerating minor trailing-data errors."""
    try:
        return zlib.decompress(raw)
    except zlib.error:
        try:
            return zlib.decompress(raw, -15)
        except zlib.error:
            return raw


def _extract_stream(obj_body: bytes) -> Optional[bytes]:
    """Extract and decompress the content stream from an object body."""
    m = re.search(rb"stream\r?\n", obj_body)
    if not m:
        return None
    stream_start = m.end()
    end_m = re.search(rb"\bendstream\b", obj_body[stream_start:])
    raw = obj_body[stream_start: stream_start + (end_m.start() if end_m else len(obj_body))]
    header = obj_body[:stream_start]
    if b"FlateDecode" in header:
        raw = _decode_flate(raw)
    return raw


# ---------------------------------------------------------------------------
# PDF string decoding
# ---------------------------------------------------------------------------

def _decode_pdf_string(s: bytes) -> str:
    """
    Decode a PDF literal string, handling octal escapes (1–3 digits) and
    standard two-character escape sequences.
    """
    out: List[str] = []
    i = 0
    while i < len(s):
        c = s[i: i + 1]
        if c == b"\\":
            i += 1
            if i >= len(s):
                break
            nc = s[i: i + 1]
            if nc == b"n":
                out.append("\n")
            elif nc == b"r":
                out.append("\r")
            elif nc == b"t":
                out.append("\t")
            elif nc == b"b":
                out.append("\b")
            elif nc == b"f":
                out.append("\f")
            elif nc in (b"(", b")", b"\\"):
                out.append(nc.decode("latin-1"))
            elif nc == b"\n":
                pass  # line continuation
            elif nc == b"\r":
                # \r or \r\n line continuation
                if i + 1 < len(s) and s[i + 1: i + 2] == b"\n":
                    i += 1
            elif nc.isdigit():
                # Read up to 3 octal digits
                j = i
                while j < i + 3 and j < len(s) and s[j: j + 1].isdigit():
                    j += 1
                out.append(chr(int(s[i:j], 8) & 0xFF))
                i = j - 1  # loop will add 1
            else:
                out.append(nc.decode("latin-1", errors="replace"))
        else:
            out.append(c.decode("latin-1", errors="replace"))
        i += 1
    return "".join(out)


def _decode_utf16be_string(raw: bytes) -> str:
    """Decode a UTF-16-BE PDF string (starts with BOM \xfe\xff)."""
    try:
        return raw.decode("utf-16-be")
    except (UnicodeDecodeError, ValueError):
        return raw.decode("latin-1", errors="replace")


def _pdf_string_to_str(raw: bytes) -> str:
    """Auto-detect encoding for a PDF string value."""
    if raw.startswith(b"\xfe\xff"):
        return _decode_utf16be_string(raw[2:])
    return _decode_pdf_string(raw)


# ---------------------------------------------------------------------------
# Text extraction from content streams
# ---------------------------------------------------------------------------

_BT_ET = re.compile(rb"BT\b(.+?)\bET\b", re.DOTALL)
_STRING_RE = re.compile(rb"\(([^)\\]|\\.)*\)")


def _extract_text_from_stream(stream: bytes) -> str:
    """Extract readable text from a PDF content stream."""
    parts: List[str] = []
    for bt_block in _BT_ET.finditer(stream):
        block = bt_block.group(1)
        # Collect Tj / ' / " strings
        for string_m in _STRING_RE.finditer(block):
            raw = string_m.group(0)[1:-1]
            parts.append(_decode_pdf_string(raw))
        # Collect TJ array strings
        for tj_m in re.finditer(rb"\[([^\]]+)\]\s*TJ", block):
            for s in _STRING_RE.finditer(tj_m.group(1)):
                raw = s.group(0)[1:-1]
                parts.append(_decode_pdf_string(raw))
    return " ".join(p.strip() for p in parts if p.strip())


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

_INFO_KEYS = ("Title", "Author", "Subject", "Keywords", "Creator", "Producer",
              "CreationDate", "ModDate")


def _extract_metadata(data: bytes, xref: Dict[int, int]) -> Dict[str, str]:
    """
    Parse the PDF Info dictionary. Returns a dict of string-valued entries.
    """
    metadata: Dict[str, str] = {}

    # Locate /Info reference in the trailer.
    tail = data[-4096:].decode("latin-1", errors="replace")
    info_m = re.search(r"/Info\s+(\d+)\s+\d+\s+R", tail)
    if not info_m:
        return metadata
    info_id = int(info_m.group(1))
    if info_id not in xref:
        return metadata

    try:
        _, obj_body = _parse_obj(data, xref[info_id])
    except PDFParseError:
        return metadata

    body_str = obj_body.decode("latin-1", errors="replace")
    for key in _INFO_KEYS:
        # Match /Key (string) or /Key <hex>
        m = re.search(r"/" + key + r"\s*\(([^)\\]|\\.)*\)", body_str)
        if m:
            raw = m.group(0).split("(", 1)[1].rstrip(")")
            metadata[key] = _decode_pdf_string(raw.encode("latin-1"))
            continue
        # Hex string form
        m = re.search(r"/" + key + r"\s*<([0-9A-Fa-f\s]+)>", body_str)
        if m:
            hex_str = re.sub(r"\s+", "", m.group(1))
            try:
                raw_bytes = bytes.fromhex(hex_str)
                metadata[key] = _pdf_string_to_str(raw_bytes)
            except ValueError:
                pass
    return metadata


# ---------------------------------------------------------------------------
# Page stream discovery
# ---------------------------------------------------------------------------

_PAGE_TYPE = re.compile(rb"/Type\s*/Page\b")
_CONTENTS_REF = re.compile(rb"/Contents\s+(\d+)\s+\d+\s+R")
_CONTENTS_ARRAY = re.compile(rb"/Contents\s*\[([^\]]+)\]")
_OBJ_REF = re.compile(rb"(\d+)\s+\d+\s+R")


def _resolve_content_streams(obj_body: bytes, data: bytes, xref: Dict[int, int]) -> bytes:
    """
    Given a Page object body, fetch and concatenate all content streams.

    Handles both single ``/Contents N G R`` and array ``/Contents [...]`` forms.
    Falls back to trying the object itself for inline streams.
    """
    # Try array form first (order matters for multi-stream pages).
    arr_m = _CONTENTS_ARRAY.search(obj_body)
    if arr_m:
        parts: List[bytes] = []
        for ref_m in _OBJ_REF.finditer(arr_m.group(1)):
            ref_id = int(ref_m.group(1))
            if ref_id in xref:
                try:
                    _, ref_body = _parse_obj(data, xref[ref_id])
                    s = _extract_stream(ref_body)
                    if s:
                        parts.append(s)
                except PDFParseError:
                    pass
        return b"\n".join(parts)

    # Single indirect reference.
    ref_m = _CONTENTS_REF.search(obj_body)
    if ref_m:
        ref_id = int(ref_m.group(1))
        if ref_id in xref:
            try:
                _, ref_body = _parse_obj(data, xref[ref_id])
                s = _extract_stream(ref_body)
                return s if s else b""
            except PDFParseError:
                return b""

    # Inline stream in the page object itself (unusual but valid).
    s = _extract_stream(obj_body)
    return s if s else b""


def _get_page_streams(
    data: bytes, xref: Dict[int, int], max_pages: int
) -> Iterator[Tuple[int, bytes]]:
    """
    Yield (1-based page_number, content_stream_bytes) for each page object.

    Uses a regex to detect page dictionaries robustly, independent of whitespace.
    Follows /Contents indirect references and arrays of references.
    """
    page_num = 0
    for obj_id in sorted(xref.keys()):
        byte_off = xref[obj_id]
        try:
            _, obj_body = _parse_obj(data, byte_off)
        except PDFParseError:
            continue
        if not _PAGE_TYPE.search(obj_body):
            continue
        page_num += 1
        stream = _resolve_content_streams(obj_body, data, xref)
        yield page_num, stream
        if max_pages and page_num >= max_pages:
            return


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class PDFExtractor:
    """
    Extract text and metadata from a PDF file without external binaries.

    Parameters
    ----------
    path : str or Path
        Path to the PDF file.
    max_pages : int, optional
        Stop after this many pages (0 = all pages).
    """

    def __init__(self, path: Union[str, Path], max_pages: int = 0) -> None:
        self.path = Path(path)
        self.max_pages = max_pages
        self._data: bytes = b""

    def _load(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError("PDF not found: " + str(self.path))
        self._data = _read_bytes(self.path)
        if not self._data.startswith(b"%PDF"):
            raise PDFParseError("Not a valid PDF file: " + str(self.path))

    def extract(self) -> ExtractionResult:
        """Parse the PDF and return an :class:`ExtractionResult`."""
        self._load()
        result = ExtractionResult(source=self.path.name, page_count=0)
        try:
            xref = _get_xref(self._data)
        except PDFParseError as exc:
            result.errors.append("xref error: " + str(exc))
            return result

        result.metadata = _extract_metadata(self._data, xref)

        pages: List[PageResult] = []
        errors: List[str] = []
        for page_num, stream in _get_page_streams(self._data, xref, self.max_pages):
            try:
                text = _extract_text_from_stream(stream) if stream else ""
            except Exception as exc:
                errors.append("page %d error: %s" % (page_num, exc))
                text = ""
            pages.append(PageResult(page_number=page_num, text=text))

        result.pages = pages
        result.page_count = len(pages)
        result.errors = errors
        return result


def extract_pdf(
    path: Union[str, Path],
    output_format: str = "text",
    output_path: Optional[Union[str, Path]] = None,
    max_pages: int = 0,
) -> str:
    """
    Extract text from a PDF and optionally write to a file.

    Parameters
    ----------
    path : str or Path
        Input PDF path.
    output_format : str
        ``"text"``, ``"markdown"``, or ``"json"``.
    output_path : str or Path, optional
        If given, write output to this path (UTF-8).
    max_pages : int
        Maximum pages to process (0 = all).

    Returns
    -------
    str
        Extracted content in the requested format.
    """
    if output_format not in ("text", "markdown", "json"):
        raise ValueError("output_format must be 'text', 'markdown', or 'json'.")
    extractor = PDFExtractor(path, max_pages=max_pages)
    result = extractor.extract()
    if output_format == "json":
        out = result.to_json()
    elif output_format == "markdown":
        out = result.to_markdown()
    else:
        out = result.full_text
    if output_path is not None:
        Path(output_path).write_text(out, encoding="utf-8")
    return out


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="pdfextract",
        description="Extract structured text and metadata from PDF files.",
    )
    parser.add_argument("input", help="Path to the input PDF file.")
    parser.add_argument("-o", "--output", default=None, metavar="FILE",
                        help="Write output to FILE instead of stdout.")
    parser.add_argument(
        "-f", "--format",
        choices=["text", "markdown", "json"],
        default="text",
        dest="fmt",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "-p", "--max-pages",
        type=int,
        default=0,
        metavar="N",
        help="Process at most N pages (default: all).",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the graphical interface.",
    )
    args = parser.parse_args()

    if args.gui:
        from .gui import launch
        launch()
        return

    out = extract_pdf(args.input, output_format=args.fmt,
                      output_path=args.output, max_pages=args.max_pages)
    if not args.output:
        print(out)
    else:
        print("Written to " + str(args.output))
