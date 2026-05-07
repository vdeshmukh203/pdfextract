"""
pdfextract: Extract structured text and metadata from PDF files.

Pure-Python PDF parser (no external binaries required).  Reads the
cross-reference table or cross-reference stream, walks the page tree to find
every page in document order, decompresses FlateDecode content streams,
decodes text from BT/ET operator blocks, and emits plain text, Markdown, or
JSON.  Document metadata is extracted from the /Info dictionary when present.
"""
from __future__ import annotations

import json
import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

__version__ = "0.2.0"
__author__ = "Vaibhav Deshmukh"
__license__ = "MIT"

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PDFParseError(Exception):
    """Raised when the PDF structure cannot be interpreted."""


# ---------------------------------------------------------------------------
# Low-level file helpers
# ---------------------------------------------------------------------------


def _find_xref_offset(data: bytes) -> int:
    """Return the byte offset recorded in the startxref entry."""
    tail = data[-2048:]
    m = re.search(rb"startxref\s+(\d+)\s+%%EOF", tail)
    if not m:
        m = re.search(rb"startxref\s+(\d+)", tail)
    if not m:
        raise PDFParseError("startxref not found")
    return int(m.group(1))


def _parse_xref_table(data: bytes, offset: int) -> Tuple[Dict[int, int], str]:
    """
    Parse a classic cross-reference table starting at *offset*.

    Returns ``(offsets, trailer_text)`` where *offsets* maps object ID to byte
    offset and *trailer_text* is the raw text of the trailer dictionary.
    """
    offsets: Dict[int, int] = {}
    trailer_pos = data.find(b"trailer", offset)
    section_end = trailer_pos if trailer_pos != -1 else offset + 131072
    chunk = data[offset:section_end].decode("latin-1", errors="replace")
    lines = chunk.splitlines()
    i = 0
    if i < len(lines) and lines[i].strip() == "xref":
        i += 1
    while i < len(lines):
        m = re.match(r"^(\d+)\s+(\d+)$", lines[i].strip())
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
    trailer_text = ""
    if trailer_pos != -1:
        end = data.find(b"startxref", trailer_pos)
        trailer_text = data[trailer_pos: end if end != -1 else trailer_pos + 4096].decode(
            "latin-1", errors="replace"
        )
    return offsets, trailer_text


def _parse_xref_stream(data: bytes, offset: int) -> Tuple[Dict[int, int], str]:
    """
    Parse a cross-reference stream (PDF 1.5+).

    Returns ``(offsets, stream_dict_text)``.  Only type-1 (uncompressed)
    entries are supported; type-2 (object streams) are silently skipped.
    """
    offsets: Dict[int, int] = {}
    try:
        _, obj_body = _parse_obj(data, offset)
    except PDFParseError:
        return offsets, ""

    text = obj_body.decode("latin-1", errors="replace")

    w_m = re.search(r"/W\s*\[\s*(\d+)\s+(\d+)\s+(\d+)\s*\]", text)
    if not w_m:
        return offsets, text
    w = [int(w_m.group(1)), int(w_m.group(2)), int(w_m.group(3))]
    entry_size = sum(w)
    if entry_size == 0:
        return offsets, text

    index_m = re.search(r"/Index\s*\[\s*([\d\s]+)\]", text)
    if index_m:
        nums = list(map(int, index_m.group(1).split()))
        index: List[Tuple[int, int]] = list(zip(nums[::2], nums[1::2]))
    else:
        size_m = re.search(r"/Size\s+(\d+)", text)
        size = int(size_m.group(1)) if size_m else 0
        index = [(0, size)]

    raw = _extract_stream(obj_body)
    if raw is None:
        return offsets, text

    pos = 0
    for first_obj, count in index:
        for j in range(count):
            if pos + entry_size > len(raw):
                break
            entry = raw[pos: pos + entry_size]
            pos += entry_size

            def _field(start: int, width: int) -> int:
                return int.from_bytes(entry[start: start + width], "big") if width else 1

            f_type = _field(0, w[0])
            f_offset = _field(w[0], w[1])
            if f_type == 1:
                offsets[first_obj + j] = f_offset

    return offsets, text


def _parse_obj(data: bytes, byte_off: int) -> Tuple[int, bytes]:
    """Return ``(obj_id, body_bytes)`` for the indirect object at *byte_off*."""
    chunk = data[byte_off: byte_off + 131072]
    m = re.search(rb"(\d+)\s+\d+\s+obj", chunk)
    if not m:
        raise PDFParseError(f"obj marker not found at offset {byte_off}")
    start = m.end()
    end_m = re.search(rb"endobj", chunk[start:])
    body = chunk[start: start + end_m.start()] if end_m else chunk[start:]
    return int(m.group(1)), body


def _decode_flate(raw: bytes) -> bytes:
    """Decompress zlib/deflate data; tries multiple wbits values on error."""
    for wbits in (15, -15, 47):
        try:
            return zlib.decompress(raw, wbits)
        except zlib.error:
            pass
    return raw


def _extract_stream(obj_bytes: bytes) -> Optional[bytes]:
    """Extract and decompress a PDF stream from an object body, or return None."""
    m = re.search(rb"stream\r?\n", obj_bytes)
    if not m:
        return None
    start = m.end()
    end_m = re.search(rb"\rendstream|endstream", obj_bytes[start:])
    raw = obj_bytes[start: start + (end_m.start() if end_m else len(obj_bytes))]
    if b"FlateDecode" in obj_bytes[:start]:
        raw = _decode_flate(raw)
    return raw


# ---------------------------------------------------------------------------
# Page tree traversal
# ---------------------------------------------------------------------------


def _get_page_ids(data: bytes, xref: Dict[int, int], node_id: int) -> List[int]:
    """
    Recursively walk the PDF page tree rooted at *node_id*.

    Returns leaf page object IDs in document order.
    """
    if node_id not in xref:
        return []
    try:
        _, body = _parse_obj(data, xref[node_id])
    except PDFParseError:
        return []
    text = body.decode("latin-1", errors="replace")

    if re.search(r"/Type\s*/Pages\b", text):
        kids_m = re.search(r"/Kids\s*\[([^\]]+)\]", text)
        if not kids_m:
            return []
        kid_ids = [
            int(m.group(1))
            for m in re.finditer(r"(\d+)\s+\d+\s+R", kids_m.group(1))
        ]
        result: List[int] = []
        for kid in kid_ids:
            result.extend(_get_page_ids(data, xref, kid))
        return result

    if re.search(r"/Type\s*/Page\b", text):
        return [node_id]
    return []


def _get_content_bytes(data: bytes, xref: Dict[int, int], page_id: int) -> bytes:
    """
    Return the combined content stream bytes for the page at *page_id*.

    The PDF page dictionary holds a /Contents key whose value is either a
    single indirect reference or an array of references; each reference points
    to a stream object.  This function collects and concatenates those streams.
    """
    if page_id not in xref:
        return b""
    try:
        _, page_body = _parse_obj(data, xref[page_id])
    except PDFParseError:
        return b""

    page_text = page_body.decode("latin-1", errors="replace")
    contents_m = re.search(r"/Contents\s*(\[[^\]]*\]|\d+\s+\d+\s+R)", page_text)
    if not contents_m:
        return b""

    ref_ids = [
        int(m.group(1))
        for m in re.finditer(r"(\d+)\s+\d+\s+R", contents_m.group(1))
    ]
    combined = b""
    for ref_id in ref_ids:
        if ref_id not in xref:
            continue
        try:
            _, sbody = _parse_obj(data, xref[ref_id])
            s = _extract_stream(sbody)
            if s:
                combined += s + b" "
        except PDFParseError:
            pass
    return combined


# ---------------------------------------------------------------------------
# Text extraction from content streams
# ---------------------------------------------------------------------------

_BT_ET = re.compile(rb"BT(.+?)ET", re.DOTALL)
_STRING_RE = re.compile(rb"\(([^)\\]|\\.)*\)")
_HEX_STRING_RE = re.compile(rb"<([0-9A-Fa-f\s]+)>")


def _decode_pdf_string(raw: bytes) -> str:
    """Decode a PDF literal string, handling ``\\ooo`` octal and common escapes."""
    out: List[str] = []
    i = 0
    while i < len(raw):
        b = raw[i: i + 1]
        if b == b"\\":
            i += 1
            if i >= len(raw):
                break
            nc = raw[i: i + 1]
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
            elif nc.isdigit():
                # 1–3 octal digits
                digits = b""
                for k in range(i, min(i + 3, len(raw))):
                    ch = raw[k: k + 1]
                    if ch.isdigit() and int(ch) < 8:
                        digits += ch
                    else:
                        break
                if digits:
                    out.append(chr(int(digits, 8)))
                    i += len(digits) - 1
            else:
                out.append(nc.decode("latin-1", errors="replace"))
        else:
            out.append(b.decode("latin-1", errors="replace"))
        i += 1
    return "".join(out)


def _decode_hex_string(hex_bytes: bytes) -> str:
    """Decode a PDF hex string ``<AABBCC...>``."""
    hex_clean = re.sub(rb"\s+", b"", hex_bytes)
    if len(hex_clean) % 2:
        hex_clean += b"0"
    try:
        return bytes.fromhex(hex_clean.decode("ascii")).decode("latin-1", errors="replace")
    except (ValueError, UnicodeDecodeError):
        return ""


def _extract_text_from_stream(stream: bytes) -> str:
    """Extract human-readable text from a PDF content stream."""
    parts: List[str] = []
    for bt_block in _BT_ET.finditer(stream):
        block = bt_block.group(1)
        for string_m in _STRING_RE.finditer(block):
            text = _decode_pdf_string(string_m.group(0)[1:-1])
            if text.strip():
                parts.append(text)
        for hex_m in _HEX_STRING_RE.finditer(block):
            text = _decode_hex_string(hex_m.group(1))
            if text.strip():
                parts.append(text)
    return " ".join(p.strip() for p in parts if p.strip())


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------


def _extract_metadata(data: bytes, xref: Dict[int, int], trailer_text: str) -> Dict[str, str]:
    """Extract document metadata from the /Info dictionary referenced in the trailer."""
    metadata: Dict[str, str] = {}
    m = re.search(r"/Info\s+(\d+)\s+\d+\s+R", trailer_text)
    if not m:
        return metadata
    info_id = int(m.group(1))
    if info_id not in xref:
        return metadata
    try:
        _, info_body = _parse_obj(data, xref[info_id])
        info_text = info_body.decode("latin-1", errors="replace")
        for key in ("Title", "Author", "Subject", "Creator", "Producer", "Keywords", "CreationDate"):
            km = re.search(
                r"/" + key + r"\s*\(([^)\\]*(?:\\.[^)\\]*)*)\)", info_text
            )
            if km:
                val = _decode_pdf_string(km.group(1).encode("latin-1", errors="replace"))
                if val.strip():
                    metadata[key.lower()] = val.strip()
    except Exception:
        pass
    return metadata


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class PageResult:
    """Extracted content for a single PDF page."""

    page_number: int
    text: str
    word_count: int = field(init=False)
    char_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.word_count = len(self.text.split())
        self.char_count = len(self.text)


@dataclass
class ExtractionResult:
    """Aggregated extraction output for an entire PDF document."""

    source: str
    page_count: int
    pages: List[PageResult] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """Concatenated text of all pages separated by blank lines."""
        return "\n\n".join(p.text for p in self.pages if p.text.strip())

    @property
    def word_count(self) -> int:
        """Total word count across all pages."""
        return sum(p.word_count for p in self.pages)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dictionary suitable for JSON output."""
        return {
            "source": self.source,
            "page_count": self.page_count,
            "word_count": self.word_count,
            "metadata": self.metadata,
            "errors": self.errors,
            "pages": [
                {
                    "page": p.page_number,
                    "text": p.text,
                    "word_count": p.word_count,
                    "char_count": p.char_count,
                }
                for p in self.pages
            ],
        }

    def to_markdown(self) -> str:
        """Render extracted content as a Markdown document."""
        lines = [
            "# Extracted Text: " + self.source,
            "",
            "**Pages**: " + str(self.page_count) + "  |  **Words**: " + str(self.word_count),
            "",
        ]
        if self.metadata:
            lines += ["## Metadata", ""]
            for k, v in self.metadata.items():
                lines.append(f"- **{k}**: {v}")
            lines.append("")
        for page in self.pages:
            lines += ["## Page " + str(page.page_number), "", page.text, ""]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------


class PDFExtractor:
    """
    Extract text and metadata from a PDF file without external binaries.

    Parameters
    ----------
    path : str or pathlib.Path
        Path to the PDF file.
    max_pages : int, optional
        Stop after this many pages.  ``0`` (default) processes all pages.

    Examples
    --------
    >>> result = PDFExtractor("paper.pdf").extract()
    >>> print(result.full_text[:200])
    """

    def __init__(self, path: str, max_pages: int = 0) -> None:
        self.path = Path(path)
        self.max_pages = max_pages
        self._data: bytes = b""

    def _load(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"PDF not found: {self.path}")
        self._data = self.path.read_bytes()
        if self._data[:4] != b"%PDF":
            raise PDFParseError(f"Not a PDF file: {self.path}")

    def _get_xref(self) -> Tuple[Dict[int, int], str]:
        offset = _find_xref_offset(self._data)
        if offset >= len(self._data):
            raise PDFParseError(
                f"startxref offset {offset} is beyond end of file ({len(self._data)} bytes)"
            )
        chunk = self._data[offset: offset + 20].lstrip()
        if chunk.startswith(b"xref"):
            return _parse_xref_table(self._data, offset)
        return _parse_xref_stream(self._data, offset)

    def _get_page_streams(
        self, xref: Dict[int, int], trailer_text: str
    ) -> Iterator[Tuple[int, bytes]]:
        """Yield ``(page_number, content_bytes)`` in document order."""
        root_m = re.search(r"/Root\s+(\d+)\s+\d+\s+R", trailer_text)
        if not root_m:
            return
        root_id = int(root_m.group(1))
        if root_id not in xref:
            return
        try:
            _, cat_body = _parse_obj(self._data, xref[root_id])
        except PDFParseError:
            return
        cat_text = cat_body.decode("latin-1", errors="replace")
        pages_m = re.search(r"/Pages\s+(\d+)\s+\d+\s+R", cat_text)
        if not pages_m:
            return
        page_ids = _get_page_ids(self._data, xref, int(pages_m.group(1)))
        for page_num, page_id in enumerate(page_ids, 1):
            yield page_num, _get_content_bytes(self._data, xref, page_id)
            if self.max_pages and page_num >= self.max_pages:
                return

    def extract(self) -> ExtractionResult:
        """
        Run the extraction pipeline.

        Returns
        -------
        ExtractionResult
            Structured result containing per-page text, metadata, and any
            errors encountered during parsing.
        """
        self._load()
        result = ExtractionResult(source=self.path.name, page_count=0)
        try:
            xref, trailer_text = self._get_xref()
        except PDFParseError as exc:
            result.errors.append(f"xref error: {exc}")
            return result

        result.metadata = _extract_metadata(self._data, xref, trailer_text)

        pages: List[PageResult] = []
        errors: List[str] = []
        for page_num, stream in self._get_page_streams(xref, trailer_text):
            try:
                text = _extract_text_from_stream(stream) if stream else ""
            except Exception as exc:
                errors.append(f"page {page_num} error: {exc}")
                text = ""
            pages.append(PageResult(page_number=page_num, text=text))

        result.pages = pages
        result.page_count = len(pages)
        result.errors = errors
        return result


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def extract_pdf(
    path: str,
    output_format: str = "text",
    output_path: Optional[str] = None,
    max_pages: int = 0,
) -> str:
    """
    Extract text from a PDF and optionally write to a file.

    Parameters
    ----------
    path : str
        Input PDF file path.
    output_format : str
        One of ``"text"`` (default), ``"markdown"``, or ``"json"``.
    output_path : str, optional
        Write output to this file path.
    max_pages : int
        Maximum pages to process (``0`` = all).

    Returns
    -------
    str
        Extracted content in the requested format.
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
# CLI entry point
# ---------------------------------------------------------------------------


def _cli() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="pdfextract",
        description="Extract structured text and metadata from PDF files.",
    )
    parser.add_argument("input", help="Path to input PDF file.")
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
    parser.add_argument("--version", action="version", version=f"pdfextract {__version__}")
    args = parser.parse_args()

    try:
        out = extract_pdf(
            args.input,
            output_format=args.fmt,
            output_path=args.output,
            max_pages=args.max_pages,
        )
    except (FileNotFoundError, PDFParseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not args.output:
        print(out)
    else:
        print(f"Written to {args.output}")


if __name__ == "__main__":
    _cli()
