"""
pdfextract: Extract structured text and metadata from scientific PDF files.

Pure-Python PDF parser requiring only the Python standard library.  Reads
cross-reference tables (PDF ≤ 1.4) and cross-reference streams (PDF 1.5+),
decodes FlateDecode content streams, extracts text in reading order from
BT/ET blocks, recovers document metadata from the Info dictionary, and
emits results as plain text, Markdown, or JSON.  Falls back gracefully on
encrypted or malformed documents.
"""
from __future__ import annotations

import json
import re
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PDFParseError(Exception):
    """Raised when a PDF structure cannot be parsed."""


# ---------------------------------------------------------------------------
# Low-level byte helpers
# ---------------------------------------------------------------------------

def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _find_xref_offset(data: bytes) -> int:
    """Return the byte offset stored in the ``startxref`` trailer token."""
    tail = data[-1024:]
    m = re.search(rb"startxref\s+(\d+)", tail)
    if not m:
        raise PDFParseError("startxref token not found")
    return int(m.group(1))


# ---------------------------------------------------------------------------
# Cross-reference table (PDF ≤ 1.4)
# ---------------------------------------------------------------------------

def _parse_xref_table(data: bytes, offset: int) -> Dict[int, int]:
    """Parse a classic ``xref`` table.  Returns ``{obj_id: byte_offset}``."""
    offsets: Dict[int, int] = {}
    chunk = data[offset:offset + 131072].decode("latin-1", errors="replace")
    lines = chunk.splitlines()
    i = 0
    if lines and lines[i].strip() == "xref":
        i += 1
    while i < len(lines):
        m = re.match(r"(\d+)\s+(\d+)", lines[i].strip())
        if not m:
            break
        first_obj, count = int(m.group(1)), int(m.group(2))
        i += 1
        for j in range(count):
            if i >= len(lines):
                break
            parts = lines[i].strip().split()
            i += 1
            if len(parts) >= 3 and parts[2] == "n":
                offsets[first_obj + j] = int(parts[0])
    return offsets


# ---------------------------------------------------------------------------
# Cross-reference stream (PDF 1.5+)
# ---------------------------------------------------------------------------

def _parse_xref_stream(data: bytes, offset: int) -> Dict[int, int]:
    """
    Parse a cross-reference stream object (PDF 1.5+).

    Returns ``{obj_id: byte_offset}`` for type-1 (uncompressed) entries.
    Type-2 (object-stream) entries are ignored — they are uncommon in
    scientific papers and require full object-stream decompression.
    """
    offsets: Dict[int, int] = {}
    try:
        chunk = data[offset:offset + 131072]
        m = re.search(rb"\d+\s+\d+\s+obj", chunk)
        if not m:
            return offsets
        body_start = m.end()
        stream_m = re.search(rb"stream\r?\n", chunk[body_start:])
        if not stream_m:
            return offsets
        dict_bytes = chunk[body_start:body_start + stream_m.start()]
        stream_start = body_start + stream_m.end()
        end_m = re.search(rb"endstream", chunk[stream_start:])
        raw = chunk[stream_start:stream_start + (end_m.start() if end_m else len(chunk))]

        if b"FlateDecode" in dict_bytes:
            raw = _decode_flate(raw)

        w_m = re.search(rb"/W\s*\[([^\]]+)\]", dict_bytes)
        idx_m = re.search(rb"/Index\s*\[([^\]]+)\]", dict_bytes)
        size_m = re.search(rb"/Size\s+(\d+)", dict_bytes)
        if not w_m:
            return offsets

        widths = [int(x) for x in w_m.group(1).split()]
        if len(widths) != 3:
            return offsets
        w1, w2, w3 = widths
        entry_size = w1 + w2 + w3
        if entry_size == 0:
            return offsets

        if idx_m:
            idx_parts = [int(x) for x in idx_m.group(1).split()]
        elif size_m:
            idx_parts = [0, int(size_m.group(1))]
        else:
            return offsets

        pos = 0
        pair = 0
        while pair + 1 < len(idx_parts):
            first_obj = idx_parts[pair]
            count = idx_parts[pair + 1]
            pair += 2
            for j in range(count):
                if pos + entry_size > len(raw):
                    break
                entry = raw[pos:pos + entry_size]
                pos += entry_size
                typ = int.from_bytes(entry[:w1], "big") if w1 else 1
                off = int.from_bytes(entry[w1:w1 + w2], "big") if w2 else 0
                if typ == 1:
                    offsets[first_obj + j] = off
    except Exception:
        pass
    return offsets


def _get_xref(data: bytes) -> Dict[int, int]:
    """
    Return the complete cross-reference map, handling both table and stream
    formats and chained ``/Prev`` updates.
    """
    offset = _find_xref_offset(data)
    chunk = data[offset:offset + 32].lstrip()
    if chunk.startswith(b"xref"):
        xref = _parse_xref_table(data, offset)
        trailer_m = re.search(rb"trailer\s*<<(.+?)>>", data[offset:offset + 131072], re.DOTALL)
        if trailer_m:
            prev_m = re.search(rb"/Prev\s+(\d+)", trailer_m.group(1))
            if prev_m:
                prev = _parse_xref_table(data, int(prev_m.group(1)))
                for k, v in prev.items():
                    xref.setdefault(k, v)
        return xref
    return _parse_xref_stream(data, offset)


# ---------------------------------------------------------------------------
# Compression
# ---------------------------------------------------------------------------

def _decode_flate(raw: bytes) -> bytes:
    """Decompress a FlateDecode stream, trying raw deflate as a fallback."""
    try:
        return zlib.decompress(raw)
    except zlib.error:
        try:
            return zlib.decompress(raw, -15)
        except zlib.error:
            return raw


# ---------------------------------------------------------------------------
# Object access
# ---------------------------------------------------------------------------

def _parse_obj(data: bytes, byte_off: int) -> Tuple[int, bytes]:
    """Extract the raw bytes of one indirect object body."""
    chunk = data[byte_off:byte_off + 65536]
    m = re.search(rb"(\d+)\s+(\d+)\s+obj", chunk)
    if not m:
        raise PDFParseError("obj marker not found at offset %d" % byte_off)
    start = m.end()
    end_m = re.search(rb"endobj", chunk[start:])
    body = chunk[start:start + end_m.start()] if end_m else chunk[start:]
    return int(m.group(1)), body


def _extract_stream(obj_bytes: bytes) -> Optional[bytes]:
    """Extract and decompress (FlateDecode) the content stream of an object."""
    m = re.search(rb"stream\r?\n", obj_bytes)
    if not m:
        return None
    start = m.end()
    end_m = re.search(rb"endstream", obj_bytes[start:])
    raw = obj_bytes[start:start + (end_m.start() if end_m else len(obj_bytes))]
    if b"FlateDecode" in obj_bytes[:start]:
        raw = _decode_flate(raw)
    return raw


# ---------------------------------------------------------------------------
# String decoding
# ---------------------------------------------------------------------------

def _decode_pdf_string(s: bytes) -> str:
    """
    Decode a PDF literal string, handling UTF-16BE BOM and octal escapes.

    Parameters
    ----------
    s : bytes
        Raw bytes between the enclosing parentheses (parentheses stripped).
    """
    if s[:2] == b"\xfe\xff":
        try:
            return s[2:].decode("utf-16-be", errors="replace")
        except Exception:
            pass
    out: List[str] = []
    i = 0
    while i < len(s):
        c = s[i:i + 1]
        if c == b"\\":
            i += 1
            if i >= len(s):
                break
            nc = s[i:i + 1]
            if nc == b"n":
                out.append("\n")
            elif nc == b"r":
                out.append("\r")
            elif nc == b"t":
                out.append("\t")
            elif nc in (b"(", b")", b"\\"):
                out.append(nc.decode("latin-1"))
            elif nc.isdigit():
                j = i
                while j < i + 3 and j < len(s) and s[j:j + 1].isdigit():
                    j += 1
                out.append(chr(int(s[i:j], 8)))
                i = j - 1
            else:
                out.append(nc.decode("latin-1", errors="replace"))
        else:
            out.append(c.decode("latin-1", errors="replace"))
        i += 1
    return "".join(out)


def _decode_hex_string(s: bytes) -> str:
    """
    Decode a PDF hex string ``<…>``.

    Parameters
    ----------
    s : bytes
        The hex digits between the angle brackets (angle brackets stripped).
    """
    hex_chars = re.sub(rb"\s", b"", s)
    if len(hex_chars) % 2:
        hex_chars += b"0"
    try:
        raw = bytes(int(hex_chars[i:i + 2], 16) for i in range(0, len(hex_chars), 2))
    except ValueError:
        return ""
    if raw[:2] == b"\xfe\xff":
        try:
            return raw[2:].decode("utf-16-be", errors="replace")
        except Exception:
            pass
    return raw.decode("latin-1", errors="replace")


def _parse_string_value(val: bytes) -> str:
    """Parse a PDF string value that may be a literal or a hex string."""
    val = val.strip()
    if val.startswith(b"("):
        m = re.match(rb"\(([^)\\]|\\.)*\)", val)
        if m:
            return _decode_pdf_string(m.group(0)[1:-1])
    if val.startswith(b"<") and not val.startswith(b"<<"):
        m = re.match(rb"<([0-9a-fA-F\s]*)>", val)
        if m:
            return _decode_hex_string(m.group(1))
    return val.decode("latin-1", errors="replace").strip()


# ---------------------------------------------------------------------------
# Text extraction from content streams
# ---------------------------------------------------------------------------

_BT_ET = re.compile(rb"BT(.+?)ET", re.DOTALL)
_STRING_RE = re.compile(rb"\(([^)\\]|\\.)*\)")
_HEX_STRING_RE = re.compile(rb"<([0-9a-fA-F\s]+)>")
_TJ_ARRAY_RE = re.compile(rb"\[([^\]]*)\]\s*TJ")
_ANY_STR_RE = re.compile(rb'\(([^)\\]|\\.)*\)|<([0-9a-fA-F\s]+)>')


def _extract_text_from_stream(stream: bytes) -> str:
    """
    Extract text from a PDF content stream using BT/ET block parsing.

    Handles literal strings ``(text) Tj``, TJ arrays ``[(text) -kern] TJ``,
    hex strings ``<hex> Tj``, and the single-quote ``'`` / double-quote
    ``"`` shorthand text-showing operators.  Processes each operator once
    in document order to avoid double-counting text that appears in both
    TJ arrays and the surrounding block.
    """
    parts: List[str] = []

    for bt_m in _BT_ET.finditer(stream):
        block = bt_m.group(1)
        i = 0
        n = len(block)

        while i < n:
            b = block[i:i + 1]

            # TJ array: [(string) kern (string) …] TJ
            if b == b"[":
                tj_m = _TJ_ARRAY_RE.match(block, i)
                if tj_m:
                    inner = tj_m.group(1)
                    texts: List[str] = []
                    for m in _ANY_STR_RE.finditer(inner):
                        token = m.group(0)
                        if token.startswith(b"("):
                            texts.append(_decode_pdf_string(token[1:-1]))
                        else:
                            texts.append(_decode_hex_string(token[1:-1]))
                    if texts:
                        parts.append("".join(texts))
                    i = tj_m.end()
                    continue

            # Literal string: (text) Tj | ' | "
            elif b == b"(":
                str_m = _STRING_RE.match(block, i)
                if str_m:
                    rest = block[str_m.end():str_m.end() + 12].lstrip()
                    if rest.startswith(b"Tj") or rest.startswith(b"'") or rest.startswith(b'"'):
                        parts.append(_decode_pdf_string(str_m.group(0)[1:-1]))
                    i = str_m.end()
                    continue

            # Hex string: <hex> Tj
            elif b == b"<" and block[i:i + 2] != b"<<":
                hex_m = _HEX_STRING_RE.match(block, i)
                if hex_m:
                    rest = block[hex_m.end():hex_m.end() + 12].lstrip()
                    if rest.startswith(b"Tj"):
                        parts.append(_decode_hex_string(hex_m.group(1)))
                    i = hex_m.end()
                    continue

            i += 1

    return " ".join(p for p in parts if p.strip())


# ---------------------------------------------------------------------------
# Metadata extraction from PDF Info dictionary
# ---------------------------------------------------------------------------

_INFO_KEYS = ("Title", "Author", "Subject", "Keywords", "CreationDate", "Creator")


def _extract_info_dict(data: bytes, xref: Dict[int, int]) -> Dict[str, str]:
    """
    Locate the PDF Info dictionary and return selected metadata fields.

    Searches the trailer for ``/Info N G R``, then reads that object and
    extracts title, author, subject, keywords, creation date, and creator.
    """
    meta: Dict[str, str] = {}
    # Search for trailer in the last 64 KiB, then fall back to full file
    for search_region in (data[-65536:], data):
        trailer_m = re.search(rb"trailer\s*<<(.+?)>>", search_region, re.DOTALL)
        if trailer_m:
            break
    else:
        return meta

    trailer = trailer_m.group(1)
    info_m = re.search(rb"/Info\s+(\d+)\s+\d+\s+R", trailer)
    if not info_m:
        return meta

    info_id = int(info_m.group(1))
    if info_id not in xref:
        return meta

    try:
        _, obj_body = _parse_obj(data, xref[info_id])
    except PDFParseError:
        return meta

    for key in _INFO_KEYS:
        pattern = rb"/" + key.encode() + rb"\s+(.+?)(?=\s*/|\s*>>)"
        m = re.search(pattern, obj_body, re.DOTALL)
        if m:
            value = _parse_string_value(m.group(1))
            if value:
                meta[key.lower()] = value

    return meta


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PageResult:
    """Extraction result for a single PDF page."""

    page_number: int  # 1-based
    text: str
    word_count: int = 0
    char_count: int = 0

    def __post_init__(self) -> None:
        self.word_count = len(self.text.split())
        self.char_count = len(self.text)


@dataclass
class ExtractionResult:
    """Aggregated extraction result for an entire PDF document."""

    source: str
    page_count: int
    pages: List[PageResult] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text.strip())

    @property
    def word_count(self) -> int:
        return sum(p.word_count for p in self.pages)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "page_count": self.page_count,
            "word_count": self.word_count,
            "metadata": self.metadata,
            "errors": self.errors,
            "pages": [
                {"page": p.page_number, "text": p.text, "words": p.word_count}
                for p in self.pages
            ],
        }

    def to_markdown(self) -> str:
        lines = [
            "# Extracted Text: " + self.source,
            "",
            "**Pages**: %d | **Words**: %d" % (self.page_count, self.word_count),
            "",
        ]
        if self.metadata:
            lines += ["## Metadata", ""]
            for k, v in self.metadata.items():
                lines.append("- **%s**: %s" % (k, v))
            lines.append("")
        if self.errors:
            lines += ["## Warnings", ""]
            for e in self.errors:
                lines.append("- " + e)
            lines.append("")
        for page in self.pages:
            lines += ["## Page %d" % page.page_number, "", page.text, ""]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------

_TYPE_PAGE_RE = re.compile(rb"/Type\s*/Page\b")
_CONTENTS_REF_RE = re.compile(rb"/Contents\s+(\d+)\s+\d+\s+R")
_CONTENTS_ARRAY_RE = re.compile(rb"/Contents\s*\[([^\]]+)\]")


class PDFExtractor:
    """
    Extract text and metadata from a PDF file without external libraries.

    Parameters
    ----------
    path : str | pathlib.Path
        Path to the input PDF file.
    max_pages : int
        Maximum number of pages to process.  ``0`` (default) extracts all pages.

    Examples
    --------
    >>> result = PDFExtractor("paper.pdf").extract()
    >>> print(result.word_count)
    """

    def __init__(self, path: str, max_pages: int = 0) -> None:
        self.path = Path(path)
        self.max_pages = max_pages
        self._data: bytes = b""

    def _load(self) -> None:
        self._data = _read_bytes(self.path)
        if not self._data.startswith(b"%PDF"):
            raise PDFParseError("Not a valid PDF file: %s" % self.path)

    def _get_page_streams(self, xref: Dict[int, int]) -> Iterator[Tuple[int, bytes]]:
        """
        Yield ``(page_number, content_stream_bytes)`` for each page.

        Detects page objects via the ``/Type /Page`` dictionary entry, then
        resolves ``/Contents`` — either a direct object reference or an array
        of references — to obtain the content bytes for text extraction.
        """
        page_num = 0
        for obj_id in sorted(xref.keys()):
            try:
                _, obj_body = _parse_obj(self._data, xref[obj_id])
            except PDFParseError:
                continue

            if not _TYPE_PAGE_RE.search(obj_body):
                continue

            stream_bytes = b""

            # Single /Contents reference
            ref_m = _CONTENTS_REF_RE.search(obj_body)
            if ref_m:
                ref_id = int(ref_m.group(1))
                if ref_id in xref:
                    try:
                        _, content_body = _parse_obj(self._data, xref[ref_id])
                        s = _extract_stream(content_body)
                        if s is not None:
                            stream_bytes = s
                    except PDFParseError:
                        pass
            else:
                # Array of /Contents references
                arr_m = _CONTENTS_ARRAY_RE.search(obj_body)
                if arr_m:
                    chunks: List[bytes] = []
                    for r in re.finditer(rb"(\d+)\s+\d+\s+R", arr_m.group(1)):
                        ref_id = int(r.group(1))
                        if ref_id in xref:
                            try:
                                _, content_body = _parse_obj(self._data, xref[ref_id])
                                s = _extract_stream(content_body)
                                if s is not None:
                                    chunks.append(s)
                            except PDFParseError:
                                pass
                    stream_bytes = b" ".join(chunks)

            page_num += 1
            yield page_num, stream_bytes
            if self.max_pages and page_num >= self.max_pages:
                return

    def extract(self) -> ExtractionResult:
        """
        Run extraction on the PDF file.

        Returns
        -------
        ExtractionResult
            Structured result containing per-page text, document metadata,
            and any non-fatal error messages encountered during parsing.
        """
        self._load()
        result = ExtractionResult(source=self.path.name, page_count=0)
        try:
            xref = _get_xref(self._data)
        except PDFParseError as exc:
            result.errors.append("xref error: " + str(exc))
            return result

        result.metadata = _extract_info_dict(self._data, xref)

        pages: List[PageResult] = []
        errors: List[str] = []
        for page_num, stream in self._get_page_streams(xref):
            try:
                text = _extract_text_from_stream(stream)
            except Exception as exc:
                errors.append("page %d: %s" % (page_num, exc))
                text = ""
            pages.append(PageResult(page_number=page_num, text=text))

        result.pages = pages
        result.page_count = len(pages)
        result.errors = errors
        return result


# ---------------------------------------------------------------------------
# Public convenience API
# ---------------------------------------------------------------------------

def extract_pdf(
    path: str,
    output_format: str = "text",
    output_path: Optional[str] = None,
    max_pages: int = 0,
) -> str:
    """
    Extract text from a PDF and optionally write the result to a file.

    Parameters
    ----------
    path : str
        Path to the input PDF file.
    output_format : str
        ``"text"`` (default), ``"markdown"``, or ``"json"``.
    output_path : str, optional
        Destination file.  When omitted the result is only returned.
    max_pages : int
        Maximum pages to process; ``0`` means no limit.

    Returns
    -------
    str
        Extracted content in the requested format.

    Raises
    ------
    PDFParseError
        If ``path`` is not a readable PDF file.
    FileNotFoundError
        If ``path`` does not exist.

    Examples
    --------
    >>> text = extract_pdf("paper.pdf")
    >>> data = extract_pdf("paper.pdf", output_format="json")
    """
    result = PDFExtractor(path, max_pages=max_pages).extract()
    if output_format == "json":
        out = json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
    elif output_format == "markdown":
        out = result.to_markdown()
    else:
        out = result.full_text
    if output_path:
        Path(output_path).write_text(out, encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------------

def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="pdfextract",
        description="Extract structured text and metadata from PDF files.",
    )
    parser.add_argument("input", nargs="?", help="Input PDF file path.")
    parser.add_argument("-o", "--output", default=None, help="Output file path.")
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
        help="Maximum pages to extract (0 = all).",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the graphical user interface (requires tkinter).",
    )
    args = parser.parse_args()

    if args.gui:
        try:
            from pdfextract_gui import launch_gui
        except ImportError as exc:
            parser.error("GUI unavailable: %s" % exc)
        launch_gui()
        return

    if not args.input:
        parser.error("the following arguments are required: input (or use --gui)")

    out = extract_pdf(
        args.input,
        output_format=args.fmt,
        output_path=args.output,
        max_pages=args.max_pages,
    )
    if not args.output:
        print(out)
    else:
        print("Written to " + args.output)


if __name__ == "__main__":
    _cli()
