"""
Low-level PDF parsing primitives.

Supports:
- Classic cross-reference tables (PDF 1.x)
- Cross-reference streams (PDF 1.5+, FlateDecode)
- FlateDecode stream decompression
- BT/ET content-stream text extraction with Tj and TJ operators
- Octal and common escape sequences in PDF literal strings
"""
from __future__ import annotations

import re
import zlib
from typing import Dict, List, Optional, Tuple


class PDFParseError(Exception):
    """Raised when a structural error prevents PDF parsing."""


# ---------------------------------------------------------------------------
# Decompression
# ---------------------------------------------------------------------------


def decode_flate(raw: bytes) -> bytes:
    """Decompress FlateDecode (zlib/deflate) data, tolerating minor errors."""
    try:
        return zlib.decompress(raw)
    except zlib.error:
        try:
            return zlib.decompress(raw, -15)  # raw deflate without zlib header
        except zlib.error:
            return raw  # return compressed bytes unchanged if both attempts fail


# ---------------------------------------------------------------------------
# Cross-reference parsing
# ---------------------------------------------------------------------------


def find_xref_offset(data: bytes) -> int:
    """Return the byte offset of the last cross-reference section."""
    tail = data[-2048:]
    m = re.search(rb"startxref\s+(\d+)", tail)
    if not m:
        raise PDFParseError("startxref not found in file")
    return int(m.group(1))


def _parse_xref_table(
    data: bytes, offset: int
) -> Tuple[Dict[int, int], Optional[int]]:
    """Parse a classic cross-reference table.

    Returns
    -------
    tuple
        ({obj_id: byte_offset}, prev_xref_offset_or_None)
    """
    offsets: Dict[int, int] = {}
    chunk = data[offset : offset + max(131072, len(data) - offset)]
    text = chunk.decode("latin-1", errors="replace")
    lines = text.splitlines()

    i = 0
    if i < len(lines) and lines[i].strip().lower() == "xref":
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
                try:
                    offsets[first_obj + j] = int(parts[0])
                except ValueError:
                    pass

    trailer_text = "\n".join(lines[i : i + 60])
    prev_m = re.search(r"/Prev\s+(\d+)", trailer_text)
    prev = int(prev_m.group(1)) if prev_m else None
    return offsets, prev


def _parse_xref_stream(
    data: bytes, offset: int
) -> Tuple[Dict[int, int], Optional[int]]:
    """Parse a cross-reference stream object (PDF 1.5+).

    Returns
    -------
    tuple
        ({obj_id: byte_offset}, prev_xref_offset_or_None)
    """
    chunk = data[offset : offset + 131072]

    stream_m = re.search(rb"stream\r?\n", chunk)
    if not stream_m:
        raise PDFParseError("xref stream: 'stream' keyword not found")

    header = chunk[: stream_m.start()].decode("latin-1", errors="replace")

    w_m = re.search(r"/W\s*\[\s*([\d\s]+?)\s*\]", header)
    if not w_m:
        raise PDFParseError("xref stream: /W entry missing")
    widths = [int(x) for x in w_m.group(1).split()]
    if len(widths) != 3:
        raise PDFParseError(
            f"xref stream: /W must have 3 entries, got {len(widths)}"
        )
    entry_size = sum(widths)
    if entry_size == 0:
        return {}, None

    size_m = re.search(r"/Size\s+(\d+)", header)
    total_size = int(size_m.group(1)) if size_m else 0

    index_m = re.search(r"/Index\s*\[\s*([\d\s]+?)\s*\]", header)
    if index_m:
        idx = [int(x) for x in index_m.group(1).split()]
        index_pairs = [(idx[k], idx[k + 1]) for k in range(0, len(idx) - 1, 2)]
    else:
        index_pairs = [(0, total_size)]

    prev_m = re.search(r"/Prev\s+(\d+)", header)
    prev = int(prev_m.group(1)) if prev_m else None

    body_start = stream_m.end()
    end_m = re.search(rb"endstream", chunk[body_start:])
    raw = chunk[
        body_start : body_start + (end_m.start() if end_m else len(chunk) - body_start)
    ]
    if b"FlateDecode" in chunk[: stream_m.start()]:
        raw = decode_flate(raw)

    offsets: Dict[int, int] = {}
    pos = 0
    w0, w1, _w2 = widths

    def _rd(buf: bytes, width: int, default: int = 0) -> int:
        return default if width == 0 else int.from_bytes(buf[:width], "big")

    for first_obj, count in index_pairs:
        for j in range(count):
            if pos + entry_size > len(raw):
                break
            entry = raw[pos : pos + entry_size]
            pos += entry_size
            ftype = _rd(entry, w0, default=1)
            f1 = _rd(entry[w0:], w1)
            if ftype == 1:  # uncompressed object at byte offset f1
                offsets[first_obj + j] = f1
            # ftype == 2 means object is in a compressed ObjStm — not yet supported

    return offsets, prev


def build_xref(data: bytes) -> Dict[int, int]:
    """Build the complete cross-reference table, following /Prev chains.

    Tries the standard xref first; falls back to a linear byte-scan when the
    xref section is missing or unparseable.

    Parameters
    ----------
    data : bytes
        Raw PDF file bytes.

    Returns
    -------
    dict
        Mapping of object ID → byte offset.
    """
    try:
        offset: Optional[int] = find_xref_offset(data)
    except PDFParseError:
        return _scan_objects(data)

    visited: set = set()
    combined: Dict[int, int] = {}

    while offset is not None and offset not in visited:
        visited.add(offset)
        head = data[offset : offset + 16].lstrip()
        try:
            if head.startswith(b"xref"):
                section, prev = _parse_xref_table(data, offset)
            else:
                section, prev = _parse_xref_stream(data, offset)
        except (PDFParseError, Exception):
            break
        for obj_id, byte_off in section.items():
            combined.setdefault(obj_id, byte_off)
        offset = prev  # type: ignore[assignment]

    return combined or _scan_objects(data)


def _scan_objects(data: bytes) -> Dict[int, int]:
    """Fallback: scan raw bytes for indirect-object markers ``N G obj``."""
    offsets: Dict[int, int] = {}
    for m in re.finditer(rb"(?<!\d)(\d+)\s+\d+\s+obj\b", data):
        obj_id = int(m.group(1))
        offsets.setdefault(obj_id, m.start())
    return offsets


# ---------------------------------------------------------------------------
# Object parsing
# ---------------------------------------------------------------------------


def parse_obj(data: bytes, byte_off: int) -> bytes:
    """Return the raw body bytes of the indirect object at *byte_off*."""
    window = data[byte_off : byte_off + 131072]
    m = re.search(rb"\d+\s+\d+\s+obj", window)
    if not m:
        raise PDFParseError(f"obj marker not found at offset {byte_off}")
    body_start = m.end()
    end_m = re.search(rb"endobj", window[body_start:])
    return window[
        body_start : body_start + (end_m.start() if end_m else len(window) - body_start)
    ]


def extract_stream_data(obj_bytes: bytes) -> Optional[bytes]:
    """Extract and decompress stream data from an object body.

    Returns *None* when the object contains no stream.
    """
    sm = re.search(rb"stream\r?\n", obj_bytes)
    if not sm:
        return None
    body_start = sm.end()
    end_m = re.search(rb"endstream", obj_bytes[body_start:])
    raw = obj_bytes[
        body_start : body_start + (end_m.start() if end_m else len(obj_bytes))
    ]
    if b"FlateDecode" in obj_bytes[: sm.start()]:
        raw = decode_flate(raw)
    return raw


def resolve_indirect(
    data: bytes, xref: Dict[int, int], ref: str
) -> Optional[bytes]:
    """Resolve an indirect reference string such as ``'5 0 R'``.

    Returns the raw object body bytes, or *None* if unresolvable.
    """
    m = re.fullmatch(r"\s*(\d+)\s+\d+\s+R\s*", ref)
    if not m:
        return None
    obj_id = int(m.group(1))
    if obj_id not in xref:
        return None
    try:
        return parse_obj(data, xref[obj_id])
    except PDFParseError:
        return None


# ---------------------------------------------------------------------------
# Dictionary helpers
# ---------------------------------------------------------------------------


def dict_get(obj_bytes: bytes, key: str) -> Optional[str]:
    """Return the raw string value for *key* in a PDF dictionary object.

    Handles direct values, indirect references, arrays, and literal strings.
    Returns *None* when the key is absent.
    """
    text = obj_bytes.decode("latin-1", errors="replace")
    pattern = (
        r"/" + re.escape(key) + r"\s+"
        r"(/\w+|<[^>]*>|\[[^\]]*\]|\([^)]*\)|-?\d+(?:\s+\d+\s+R)?|\d+(?:\.\d+)?)"
    )
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1).strip() if m else None


def dict_get_refs(obj_bytes: bytes, key: str) -> List[str]:
    """Return all indirect references found in the value of *key*.

    Useful for array-valued keys such as ``/Kids``.
    """
    raw = dict_get(obj_bytes, key)
    if raw is None:
        return []
    return re.findall(r"\d+\s+\d+\s+R", raw)


# ---------------------------------------------------------------------------
# PDF literal string decoding
# ---------------------------------------------------------------------------


def decode_pdf_string(raw: bytes) -> str:
    """Decode a PDF literal string, handling octal escapes and common sequences.

    Parameters
    ----------
    raw : bytes
        String contents *without* the surrounding parentheses.

    Returns
    -------
    str
        Decoded Unicode string (using latin-1 for bytes above 127).
    """
    out: List[str] = []
    i = 0
    n = len(raw)
    while i < n:
        b = raw[i]
        if b == ord("\\"):
            i += 1
            if i >= n:
                break
            esc = raw[i]
            if esc == ord("n"):
                out.append("\n")
                i += 1
            elif esc == ord("r"):
                out.append("\r")
                i += 1
            elif esc == ord("t"):
                out.append("\t")
                i += 1
            elif esc in (ord("("), ord(")"), ord("\\")):
                out.append(chr(esc))
                i += 1
            elif ord("0") <= esc <= ord("7"):
                # 1–3 octal digits
                j, octal = i, ""
                while j < n and j < i + 3 and ord("0") <= raw[j] <= ord("7"):
                    octal += chr(raw[j])
                    j += 1
                try:
                    out.append(chr(int(octal, 8)))
                except (ValueError, OverflowError):
                    pass
                i = j
            else:
                out.append(chr(esc))
                i += 1
        else:
            out.append(chr(b) if b < 128 else raw[i : i + 1].decode("latin-1"))
            i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Text extraction from content streams
# ---------------------------------------------------------------------------

_BT_ET_RE = re.compile(rb"BT(.+?)ET", re.DOTALL)
_STR_RE = re.compile(rb"\((?:[^)\\]|\\.)*\)")


def extract_text_from_stream(stream: bytes) -> str:
    """Extract text from a PDF content stream by processing BT/ET blocks.

    Handles both ``(text) Tj`` and ``[(text) kern ...] TJ`` operators.

    Parameters
    ----------
    stream : bytes
        Raw (decompressed) content stream bytes.

    Returns
    -------
    str
        Space-joined text tokens in stream order.
    """
    parts: List[str] = []
    for bt in _BT_ET_RE.finditer(stream):
        block = bt.group(1)
        for sm in _STR_RE.finditer(block):
            text = decode_pdf_string(sm.group(0)[1:-1])
            if text.strip():
                parts.append(text.strip())
        for tj in re.finditer(rb"\[([^\]]+)\]\s*TJ", block):
            for sm in _STR_RE.finditer(tj.group(1)):
                text = decode_pdf_string(sm.group(0)[1:-1])
                if text.strip():
                    parts.append(text.strip())
    return " ".join(parts)
