"""
Pure-Python PDF parser and text extractor.

Reads cross-reference tables, decodes FlateDecode content streams, extracts
text runs from BT/ET blocks, and attempts to recover document metadata from
the Info dictionary. No external binaries are required.
"""
from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from .schema import ExtractionResult, PageResult


class PDFParseError(Exception):
    """Raised when the PDF structure cannot be parsed."""


# ---------------------------------------------------------------------------
# Low-level byte helpers
# ---------------------------------------------------------------------------

def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _find_xref_offset(data: bytes) -> int:
    """Locate startxref offset by scanning the last 2 KB of the file."""
    tail = data[-2048:]
    m = re.search(rb"startxref\s+(\d+)", tail)
    if not m:
        raise PDFParseError("startxref not found")
    return int(m.group(1))


def _parse_xref_table(data: bytes, offset: int) -> Dict[int, int]:
    """Parse a classic xref table. Returns {obj_id: byte_offset}."""
    offsets: Dict[int, int] = {}
    # Read a generous window; large PDFs can have multi-KB xref tables.
    window_size = min(len(data) - offset, 512 * 1024)
    chunk = data[offset : offset + window_size].decode("latin-1", errors="replace")
    lines = chunk.splitlines()
    i = 0
    if i < len(lines) and lines[i].strip() == "xref":
        i += 1
    while i < len(lines):
        header = lines[i].strip()
        if header.startswith("trailer"):
            break
        m = re.match(r"(\d+)\s+(\d+)", header)
        if not m:
            i += 1
            continue
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


def _parse_obj(data: bytes, byte_off: int) -> Tuple[int, bytes]:
    """Extract the raw bytes of one indirect object."""
    # 64 KB is sufficient for typical page streams; fall back to larger window.
    for window in (65536, 524288):
        chunk = data[byte_off : byte_off + window]
        m = re.search(rb"(\d+)\s+\d+\s+obj", chunk)
        if not m:
            raise PDFParseError(f"obj marker not found at offset {byte_off}")
        start = m.end()
        end_m = re.search(rb"endobj", chunk[start:])
        if end_m:
            return int(m.group(1)), chunk[start : start + end_m.start()]
        if window == 65536:
            continue  # retry with bigger window
    return int(m.group(1)), chunk[start:]  # type: ignore[possibly-undefined]


# ---------------------------------------------------------------------------
# Stream decoding
# ---------------------------------------------------------------------------

def _decode_flate(raw: bytes) -> bytes:
    """Decompress a zlib/deflate stream, trying both with and without header."""
    for wbits in (15, -15):
        try:
            return zlib.decompress(raw, wbits)
        except zlib.error:
            continue
    return raw  # return compressed bytes rather than crashing


def _extract_stream(obj_bytes: bytes) -> Optional[bytes]:
    """Extract and decompress the data stream from an object body."""
    m = re.search(rb"stream\r?\n", obj_bytes)
    if not m:
        return None
    stream_start = m.end()
    header = obj_bytes[:stream_start]
    end_m = re.search(rb"endstream", obj_bytes[stream_start:])
    raw = obj_bytes[stream_start : stream_start + (end_m.start() if end_m else len(obj_bytes))]
    if b"FlateDecode" in header:
        raw = _decode_flate(raw)
    return raw


# ---------------------------------------------------------------------------
# Text extraction from content streams
# ---------------------------------------------------------------------------

_BT_ET = re.compile(rb"BT\b(.+?)\bET\b", re.DOTALL)
_STRING_RE = re.compile(rb"\(([^)\\]|\\.)*\)")
_HEX_STRING_RE = re.compile(rb"<([0-9A-Fa-f\s]+)>")


def _decode_pdf_string(raw: bytes) -> str:
    """Decode a PDF literal string, handling octal escapes and common two-char escapes."""
    out: List[str] = []
    i = 0
    while i < len(raw):
        if raw[i : i + 1] == b"\\":
            i += 1
            if i >= len(raw):
                break
            nc = raw[i : i + 1]
            if nc == b"n":
                out.append("\n")
            elif nc == b"r":
                out.append("\r")
            elif nc == b"t":
                out.append("\t")
            elif nc in (b"(", b")", b"\\"):
                out.append(nc.decode("latin-1"))
            elif nc[0:1] >= b"0" and nc[0:1] <= b"7":
                # Octal escape: up to 3 digits
                octal_bytes = raw[i : i + 3]
                octal_str = ""
                for b in octal_bytes:
                    ch = chr(b)
                    if "0" <= ch <= "7":
                        octal_str += ch
                    else:
                        break
                if octal_str:
                    out.append(chr(int(octal_str, 8)))
                    i += len(octal_str) - 1  # -1 because outer i+=1 follows
            else:
                out.append(nc.decode("latin-1", errors="replace"))
        else:
            out.append(raw[i : i + 1].decode("latin-1", errors="replace"))
        i += 1
    return "".join(out)


def _decode_hex_string(raw: bytes) -> str:
    """Decode a PDF hex string <4E6F72...> to text."""
    hex_clean = re.sub(rb"\s+", b"", raw)
    if len(hex_clean) % 2:
        hex_clean += b"0"
    try:
        decoded = bytes.fromhex(hex_clean.decode("ascii", errors="replace"))
        return decoded.decode("latin-1", errors="replace")
    except ValueError:
        return ""


def _extract_text_from_stream(stream: bytes) -> str:
    """Pull visible text from a PDF content stream via BT/ET block parsing."""
    parts: List[str] = []
    for bt_block in _BT_ET.finditer(stream):
        block = bt_block.group(1)
        tokens: List[str] = []

        # Collect literal strings
        for s_m in _STRING_RE.finditer(block):
            text = _decode_pdf_string(s_m.group(0)[1:-1])
            if text.strip():
                tokens.append(text)

        # Collect TJ arrays which may interleave strings and kerning numbers
        for tj_m in re.finditer(rb"\[([^\]]+)\]\s*TJ", block):
            inner = tj_m.group(1)
            for s in _STRING_RE.finditer(inner):
                text = _decode_pdf_string(s.group(0)[1:-1])
                if text.strip():
                    tokens.append(text)
            for h in _HEX_STRING_RE.finditer(inner):
                text = _decode_hex_string(h.group(1))
                if text.strip():
                    tokens.append(text)

        # Hex strings outside TJ (e.g. Tj with hex)
        for h_m in _HEX_STRING_RE.finditer(block):
            text = _decode_hex_string(h_m.group(1))
            if text.strip():
                tokens.append(text)

        if tokens:
            parts.append(" ".join(tokens))

    return " ".join(p.strip() for p in parts if p.strip())


# ---------------------------------------------------------------------------
# Metadata extraction from Info dictionary
# ---------------------------------------------------------------------------

_PDF_INFO_KEYS = ("Title", "Author", "Subject", "Keywords", "Creator", "Producer")


def _extract_metadata(data: bytes) -> Dict[str, str]:
    """Attempt to extract document metadata from the PDF trailer's Info dict."""
    metadata: Dict[str, str] = {}
    # Locate the trailer dictionary
    trailer_m = re.search(rb"trailer\s*<<(.+?)>>", data[-32768:], re.DOTALL)
    if not trailer_m:
        return metadata
    trailer = trailer_m.group(1)
    # Find /Info reference
    info_m = re.search(rb"/Info\s+(\d+)\s+\d+\s+R", trailer)
    if not info_m:
        return metadata
    info_obj_id = int(info_m.group(1))

    # Scan for the Info object
    obj_m = re.search(
        rb"\b" + str(info_obj_id).encode() + rb"\s+\d+\s+obj\s*<<(.+?)>>",
        data,
        re.DOTALL,
    )
    if not obj_m:
        return metadata

    info_dict = obj_m.group(1)
    for key in _PDF_INFO_KEYS:
        key_bytes = key.encode()
        val_m = re.search(
            rb"/" + key_bytes + rb"\s*\(([^)\\]|\\.)*\)", info_dict
        )
        if val_m:
            raw = val_m.group(0)
            paren_m = re.search(rb"\((.+)\)$", raw, re.DOTALL)
            if paren_m:
                metadata[key] = _decode_pdf_string(paren_m.group(1))
        else:
            # Try hex string form
            hex_m = re.search(
                rb"/" + key_bytes + rb"\s*<([0-9A-Fa-f\s]+)>", info_dict
            )
            if hex_m:
                metadata[key] = _decode_hex_string(hex_m.group(1))
    return metadata


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------

class PDFExtractor:
    """
    Extract text and metadata from a PDF file without external binaries.

    Parameters
    ----------
    path : str or Path
        Path to the PDF file.
    max_pages : int, optional
        Stop after this many pages. 0 means extract all pages.
    """

    def __init__(self, path: str, max_pages: int = 0) -> None:
        self.path = Path(path)
        self.max_pages = max_pages
        self._data: bytes = b""

    def _load(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"PDF not found: {self.path}")
        self._data = _read_bytes(self.path)
        if self._data[:4] != b"%PDF":
            raise PDFParseError(f"Not a valid PDF file: {self.path}")

    def _get_xref(self) -> Dict[int, int]:
        offset = _find_xref_offset(self._data)
        return _parse_xref_table(self._data, offset)

    def _get_page_streams(self, xref: Dict[int, int]) -> Iterator[Tuple[int, bytes]]:
        """Yield (page_number, content_stream_bytes) for each page object."""
        page_num = 0
        for obj_id in sorted(xref.keys()):
            byte_off = xref[obj_id]
            try:
                _, obj_body = _parse_obj(self._data, byte_off)
            except PDFParseError:
                continue
            # Detect page objects by /Type /Page (not /Pages)
            if not re.search(rb"/Type\s*/Page\b", obj_body):
                continue
            if re.search(rb"/Type\s*/Pages\b", obj_body):
                continue
            stream = _extract_stream(obj_body)
            if stream is None:
                # Page may reference /Contents by object number; extract inline text
                contents_m = re.search(rb"/Contents\s+(\d+)\s+\d+\s+R", obj_body)
                if contents_m:
                    ref_id = int(contents_m.group(1))
                    if ref_id in xref:
                        try:
                            _, ref_body = _parse_obj(self._data, xref[ref_id])
                            stream = _extract_stream(ref_body)
                        except PDFParseError:
                            pass
            if stream:
                page_num += 1
                yield page_num, stream
                if self.max_pages and page_num >= self.max_pages:
                    return

    def extract(self) -> ExtractionResult:
        """Run the extraction pipeline. Returns an ExtractionResult."""
        self._load()
        result = ExtractionResult(source=self.path.name, page_count=0)
        try:
            xref = self._get_xref()
        except PDFParseError as exc:
            result.errors.append(f"xref error: {exc}")
            return result

        result.metadata = _extract_metadata(self._data)

        pages: List[PageResult] = []
        errors: List[str] = []
        for page_num, stream in self._get_page_streams(xref):
            try:
                text = _extract_text_from_stream(stream)
            except Exception as exc:
                errors.append(f"page {page_num} error: {exc}")
                text = ""
            pages.append(PageResult(page_number=page_num, text=text))

        result.pages = pages
        result.page_count = len(pages)
        result.errors = errors
        return result
