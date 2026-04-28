"""Low-level PDF binary parsing: xref tables, indirect objects, streams, metadata."""
from __future__ import annotations

import re
import zlib
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple


class PDFParseError(Exception):
    """Raised when the PDF structure cannot be parsed."""


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------

def read_pdf_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if not data.startswith(b"%PDF"):
        raise PDFParseError(f"Not a PDF file: {path}")
    return data


# ---------------------------------------------------------------------------
# Cross-reference table
# ---------------------------------------------------------------------------

def find_xref_offset(data: bytes) -> int:
    """Locate the startxref offset by scanning the last 2 KB of the file."""
    tail = data[-2048:]
    m = re.search(rb"startxref\s+(\d+)", tail)
    if not m:
        raise PDFParseError("startxref marker not found; file may be corrupt.")
    return int(m.group(1))


def parse_xref_table(data: bytes, offset: int) -> Dict[int, int]:
    """Parse a classic PDF xref table; return ``{obj_id: byte_offset}``.

    Raises ``PDFParseError`` when a cross-reference *stream* (PDF 1.5+) is
    detected instead of a classic table, because stream-based xrefs require
    a different (and more complex) parsing path that is not yet implemented.
    """
    # Detect cross-reference streams: offset points to an "N G obj" header
    # rather than the literal "xref" keyword.
    probe = data[offset: offset + 64]
    if not re.match(rb"\s*xref", probe):
        if re.match(rb"\s*\d+\s+\d+\s+obj", probe):
            raise PDFParseError(
                "Cross-reference stream (PDF 1.5+) detected at offset "
                f"{offset}.  Only classic xref tables are supported."
            )
        raise PDFParseError(
            f"Expected 'xref' keyword at offset {offset}; got: {probe[:16]!r}"
        )

    # Read a generous window so we don't truncate large xref tables.
    xref_text = data[offset: offset + 524288].decode("latin-1", errors="replace")
    lines = xref_text.splitlines()

    offsets: Dict[int, int] = {}
    i = 0
    if lines[i].strip() == "xref":
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
            parts = lines[i].strip().split()
            i += 1
            if len(parts) < 3:
                continue
            obj_id = first_obj + j
            if parts[2] == "n":
                offsets[obj_id] = int(parts[0])

    return offsets


# ---------------------------------------------------------------------------
# Indirect objects
# ---------------------------------------------------------------------------

def parse_obj(data: bytes, byte_off: int) -> Tuple[int, bytes]:
    """Return ``(obj_number, body_bytes)`` for one indirect object."""
    chunk = data[byte_off: byte_off + 131072]
    m = re.search(rb"(\d+)\s+\d+\s+obj", chunk)
    if not m:
        raise PDFParseError(f"'obj' marker not found at offset {byte_off}")
    start = m.end()
    end_m = re.search(rb"endobj", chunk[start:])
    body = chunk[start: start + end_m.start()] if end_m else chunk[start:]
    return int(m.group(1)), body


# ---------------------------------------------------------------------------
# Stream decoding
# ---------------------------------------------------------------------------

def _decode_flate(raw: bytes) -> bytes:
    for wbits in (15, -15):
        try:
            return zlib.decompress(raw, wbits)
        except zlib.error:
            pass
    return raw  # return raw bytes on failure rather than raising


def extract_stream(obj_bytes: bytes) -> Optional[bytes]:
    """Extract and decompress (FlateDecode) the data stream from an object body."""
    m = re.search(rb"stream\r?\n", obj_bytes)
    if not m:
        return None
    stream_start = m.end()
    end_m = re.search(rb"endstream", obj_bytes[stream_start:])
    raw = obj_bytes[stream_start: stream_start + (end_m.start() if end_m else len(obj_bytes))]
    if b"FlateDecode" in obj_bytes[:stream_start]:
        raw = _decode_flate(raw)
    return raw


# ---------------------------------------------------------------------------
# Page object detection
# ---------------------------------------------------------------------------

_PAGE_TYPE_RE = re.compile(rb"/Type\s*/Page\b")


def is_page_object(obj_body: bytes) -> bool:
    """Return True when *obj_body* is a PDF page dictionary."""
    return bool(_PAGE_TYPE_RE.search(obj_body))


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

_INFO_REF_RE = re.compile(rb"/Info\s+(\d+)\s+\d+\s+R")
_META_STRING_RE = re.compile(rb"\(([^)\\]|\\.)*\)")

_META_KEYS = (
    "Title", "Author", "Subject", "Keywords",
    "Creator", "Producer", "CreationDate", "ModDate",
)


def extract_metadata(data: bytes, xref: Dict[int, int]) -> Dict[str, str]:
    """Return document metadata from the PDF /Info dictionary (if present)."""
    # Search the last 4 KB for the /Info reference in the trailer.
    tail = data[-4096:]
    m = _INFO_REF_RE.search(tail)
    if not m:
        return {}

    info_id = int(m.group(1))
    if info_id not in xref:
        return {}

    try:
        _, obj_body = parse_obj(data, xref[info_id])
    except PDFParseError:
        return {}

    meta: Dict[str, str] = {}
    for key in _META_KEYS:
        pat = re.compile(rb"/" + key.encode() + rb"\s*\(([^)\\]|\\.)*\)")
        km = pat.search(obj_body)
        if km:
            raw = km.group(0)
            inner = raw[raw.index(b"(") + 1: -1]
            from ._text import decode_pdf_string  # local import to avoid circular dep
            meta[key] = decode_pdf_string(inner)
    return meta


# ---------------------------------------------------------------------------
# Page stream iterator
# ---------------------------------------------------------------------------

_CONTENTS_RE = re.compile(rb"/Contents\s+(\d+)\s+\d+\s+R")


def iter_page_streams(
    data: bytes, xref: Dict[int, int], max_pages: int = 0
) -> Iterator[Tuple[int, bytes]]:
    """Yield ``(1-based page_number, content_stream_bytes)`` for every page.

    PDF pages store their content in a separate *content stream* object
    referenced via ``/Contents N 0 R``.  This function follows that reference
    to retrieve the actual text-bearing stream.  If no ``/Contents`` reference
    is found, it falls back to looking for an inline stream in the page object
    itself (non-standard but occasionally seen).
    """
    page_num = 0
    for obj_id in sorted(xref):
        byte_off = xref[obj_id]
        try:
            _, obj_body = parse_obj(data, byte_off)
        except PDFParseError:
            continue

        if not is_page_object(obj_body):
            continue

        # Follow /Contents N 0 R to the actual content stream object.
        stream: Optional[bytes] = None
        m = _CONTENTS_RE.search(obj_body)
        if m:
            content_id = int(m.group(1))
            if content_id in xref:
                try:
                    _, content_body = parse_obj(data, xref[content_id])
                    stream = extract_stream(content_body)
                except PDFParseError:
                    pass

        # Fallback: some unusual PDFs embed the stream in the page object.
        if stream is None:
            stream = extract_stream(obj_body)

        page_num += 1
        yield page_num, stream if stream is not None else b""

        if max_pages and page_num >= max_pages:
            return
