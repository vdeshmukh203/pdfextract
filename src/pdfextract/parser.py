"""
Low-level PDF parsing utilities.

Handles xref table and cross-reference stream parsing, /Prev chain traversal,
page-tree traversal for correct page ordering, stream decompression, and
Info dictionary extraction.  No external dependencies required.
"""
from __future__ import annotations

import re
import struct
import zlib
from typing import Dict, Iterator, List, Optional, Tuple

from .schema import PDFParseError


# ---------------------------------------------------------------------------
# Stream decompression
# ---------------------------------------------------------------------------

def _decode_flate(raw: bytes) -> bytes:
    """Decompress a FlateDecode stream; falls back to raw on failure."""
    try:
        return zlib.decompress(raw)
    except zlib.error:
        try:
            return zlib.decompress(raw, -15)  # raw deflate
        except zlib.error:
            return raw


# ---------------------------------------------------------------------------
# Object parsing
# ---------------------------------------------------------------------------

def parse_obj(data: bytes, byte_off: int) -> Tuple[int, bytes]:
    """Return (obj_id, body_bytes) for the indirect object at *byte_off*."""
    chunk = data[byte_off: byte_off + 65536]
    m = re.search(rb"(\d+)\s+\d+\s+obj", chunk)
    if not m:
        raise PDFParseError(f"'obj' marker not found at offset {byte_off}")
    start = m.end()
    end_m = re.search(rb"\bendobj\b", chunk[start:])
    body = chunk[start: start + end_m.start()] if end_m else chunk[start:]
    return int(m.group(1)), body


def extract_stream_bytes(obj_body: bytes) -> Optional[bytes]:
    """Decompress and return the stream content of an object, or None."""
    m = re.search(rb"stream\r?\n", obj_body)
    if not m:
        return None
    start = m.end()
    end_m = re.search(rb"\bendstream\b", obj_body[start:])
    raw = obj_body[start: start + end_m.start()] if end_m else obj_body[start:]
    if b"FlateDecode" in obj_body[:m.start()]:
        raw = _decode_flate(raw)
    return raw


def resolve_ref(data: bytes, xref: Dict[int, int], ref: bytes) -> Optional[bytes]:
    """Dereference an indirect reference (b'N M R') and return the object body."""
    m = re.match(rb"(\d+)\s+\d+\s+R", ref.strip())
    if not m:
        return None
    obj_id = int(m.group(1))
    if obj_id not in xref:
        return None
    try:
        _, body = parse_obj(data, xref[obj_id])
        return body.strip()
    except PDFParseError:
        return None


# ---------------------------------------------------------------------------
# Cross-reference table parsing
# ---------------------------------------------------------------------------

def _parse_xref_table(data: bytes, offset: int) -> Tuple[Dict[int, int], bytes]:
    """
    Parse a classic xref table starting at *offset*.

    Returns (obj_offsets, trailer_dict_bytes).
    """
    offsets: Dict[int, int] = {}
    chunk = data[offset: offset + 131072]
    text = chunk.decode("latin-1", errors="replace")
    lines = text.splitlines()

    i = 0
    if i < len(lines) and lines[i].strip() == "xref":
        i += 1

    while i < len(lines):
        header = lines[i].strip()
        if header.startswith("trailer"):
            break
        hm = re.match(r"(\d+)\s+(\d+)", header)
        if not hm:
            i += 1
            continue
        first_obj, count = int(hm.group(1)), int(hm.group(2))
        i += 1
        for j in range(count):
            if i >= len(lines):
                break
            parts = lines[i].strip().split()
            i += 1
            if len(parts) >= 3 and parts[2] == "n":
                offsets[first_obj + j] = int(parts[0])

    trailer_m = re.search(rb"trailer\s*(<<.*?>>)", chunk, re.DOTALL)
    trailer = trailer_m.group(1) if trailer_m else b""
    return offsets, trailer


# ---------------------------------------------------------------------------
# Cross-reference stream parsing (PDF 1.5+)
# ---------------------------------------------------------------------------

def _parse_xref_stream(data: bytes, offset: int) -> Tuple[Dict[int, int], bytes]:
    """
    Parse a cross-reference stream (PDF 1.5+) at *offset*.

    Returns (obj_offsets, stream_dict_bytes_used_as_trailer).
    """
    offsets: Dict[int, int] = {}
    try:
        _, obj_body = parse_obj(data, offset)
    except PDFParseError:
        return offsets, b""

    stream_data = extract_stream_bytes(obj_body)
    if not stream_data:
        return offsets, obj_body

    # /W [w1 w2 w3] — widths of the three fields
    w_m = re.search(rb"/W\s*\[([^\]]+)\]", obj_body)
    if not w_m:
        return offsets, obj_body
    w_vals = w_m.group(1).split()
    if len(w_vals) < 3:
        return offsets, obj_body
    w1, w2, w3 = int(w_vals[0]), int(w_vals[1]), int(w_vals[2])
    entry_size = w1 + w2 + w3
    if entry_size == 0:
        return offsets, obj_body

    # /Index [first count ...]  (default: [0 /Size])
    size_m = re.search(rb"/Size\s+(\d+)", obj_body)
    total = int(size_m.group(1)) if size_m else 0
    idx_m = re.search(rb"/Index\s*\[([^\]]+)\]", obj_body)
    if idx_m:
        idx_parts = idx_m.group(1).split()
        pairs = [
            (int(idx_parts[k]), int(idx_parts[k + 1]))
            for k in range(0, len(idx_parts) - 1, 2)
        ]
    else:
        pairs = [(0, total)]

    pos = 0
    for first_obj, count in pairs:
        for j in range(count):
            if pos + entry_size > len(stream_data):
                break
            entry = stream_data[pos: pos + entry_size]
            pos += entry_size
            f1 = int.from_bytes(entry[:w1], "big") if w1 else 1
            f2 = int.from_bytes(entry[w1: w1 + w2], "big") if w2 else 0
            if f1 == 1:  # normal in-use object; type 2 = compressed (skip)
                offsets[first_obj + j] = f2

    return offsets, obj_body  # stream dict doubles as trailer


# ---------------------------------------------------------------------------
# Unified xref loader with /Prev chain following
# ---------------------------------------------------------------------------

def load_xref(data: bytes) -> Tuple[Dict[int, int], bytes]:
    """
    Locate the latest xref, follow /Prev chains, and merge all entries.

    Returns (obj_offsets, latest_trailer_bytes).
    Newer entries take precedence over older ones (PDF spec §7.5.6).
    """
    tail = data[-1024:]
    sx_m = re.search(rb"startxref\s+(\d+)", tail)
    if not sx_m:
        raise PDFParseError("startxref not found — file may be corrupt or truncated")
    offset = int(sx_m.group(1))

    all_offsets: Dict[int, int] = {}
    latest_trailer = b""
    seen: set = set()

    while offset not in seen:
        seen.add(offset)
        # Detect xref table vs xref stream by peeking at bytes at offset
        peek = data[offset: offset + 8].lstrip()
        if peek.startswith(b"xref"):
            offsets, trailer = _parse_xref_table(data, offset)
        else:
            offsets, trailer = _parse_xref_stream(data, offset)

        # First pass = newest; only add entries not already present
        for oid, off in offsets.items():
            all_offsets.setdefault(oid, off)
        if not latest_trailer:
            latest_trailer = trailer

        prev_m = re.search(rb"/Prev\s+(\d+)", trailer)
        if not prev_m:
            break
        offset = int(prev_m.group(1))

    return all_offsets, latest_trailer


# ---------------------------------------------------------------------------
# Page tree traversal
# ---------------------------------------------------------------------------

def get_page_obj_ids(
    data: bytes, xref: Dict[int, int], trailer: bytes
) -> List[int]:
    """
    Walk the PDF Pages tree and return page object IDs in reading order.

    Falls back to an empty list if the tree cannot be resolved.
    """
    root_m = re.search(rb"/Root\s+(\d+\s+\d+\s+R)", trailer)
    if not root_m:
        return []
    catalog = resolve_ref(data, xref, root_m.group(1))
    if not catalog:
        return []
    pages_m = re.search(rb"/Pages\s+(\d+\s+\d+\s+R)", catalog)
    if not pages_m:
        return []

    page_ids: List[int] = []

    def _walk(ref_bytes: bytes) -> None:
        body = resolve_ref(data, xref, ref_bytes)
        if not body:
            return
        type_m = re.search(rb"/Type\s*/(\w+)", body)
        node_type = type_m.group(1) if type_m else b""
        if node_type == b"Pages":
            kids_m = re.search(rb"/Kids\s*\[([^\]]+)\]", body)
            if not kids_m:
                return
            for kid_m in re.finditer(rb"\d+\s+\d+\s+R", kids_m.group(1)):
                _walk(kid_m.group(0))
        elif node_type == b"Page":
            id_m = re.match(rb"(\d+)", ref_bytes.strip())
            if id_m:
                page_ids.append(int(id_m.group(1)))

    _walk(pages_m.group(1))
    return page_ids


def get_page_content_stream(
    data: bytes, xref: Dict[int, int], page_obj_id: int
) -> Optional[bytes]:
    """Return the merged content stream bytes for a page object."""
    if page_obj_id not in xref:
        return None
    try:
        _, page_body = parse_obj(data, xref[page_obj_id])
    except PDFParseError:
        return None

    # /Contents can be a direct ref or an array of refs
    cont_m = re.search(rb"/Contents\s+(\[.*?\]|\d+\s+\d+\s+R)", page_body, re.DOTALL)
    if not cont_m:
        return None
    cont_raw = cont_m.group(1).strip()

    streams: List[bytes] = []
    if cont_raw.startswith(b"["):
        for ref_m in re.finditer(rb"\d+\s+\d+\s+R", cont_raw):
            body = resolve_ref(data, xref, ref_m.group(0))
            if body:
                s = extract_stream_bytes(body)
                if s is not None:
                    streams.append(s)
    else:
        body = resolve_ref(data, xref, cont_raw)
        if body:
            s = extract_stream_bytes(body)
            if s is not None:
                streams.append(s)

    return b"\n".join(streams) if streams else None


# ---------------------------------------------------------------------------
# Metadata (Info dictionary)
# ---------------------------------------------------------------------------

_INFO_KEYS = (
    b"Title", b"Author", b"Subject", b"Keywords",
    b"Creator", b"Producer", b"CreationDate", b"ModDate",
)


def parse_metadata(
    data: bytes, xref: Dict[int, int], trailer: bytes
) -> Dict[str, str]:
    """Extract the PDF Info dictionary as a plain string dict."""
    meta: Dict[str, str] = {}
    info_m = re.search(rb"/Info\s+(\d+\s+\d+\s+R)", trailer)
    if not info_m:
        return meta
    info_body = resolve_ref(data, xref, info_m.group(1))
    if not info_body:
        return meta
    for key in _INFO_KEYS:
        # Literal string value: /Key (value)
        m = re.search(rb"/" + key + rb"\s*\(([^)\\]*(?:\\.[^)\\]*)*)\)", info_body)
        if m:
            raw_val = m.group(1)
            meta[key.decode()] = _decode_pdf_string(raw_val)
    return meta


# ---------------------------------------------------------------------------
# PDF string decoding
# ---------------------------------------------------------------------------

def _decode_pdf_string(s: bytes) -> str:
    """Decode a PDF literal string bytes (without outer parens)."""
    out: List[str] = []
    i = 0
    while i < len(s):
        b = s[i: i + 1]
        if b == b"\\":
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
            elif nc in (b"(", b")"):
                out.append(nc.decode("latin-1"))
            elif nc == b"\\":
                out.append("\\")
            elif nc[0:1].isdigit() if nc else False:
                # Octal: 1–3 digits
                octal_bytes = s[i: i + 3]
                digits = re.match(rb"([0-7]{1,3})", octal_bytes)
                if digits:
                    val = int(digits.group(1), 8) & 0xFF
                    out.append(chr(val))
                    i += len(digits.group(1)) - 1
            else:
                out.append(nc.decode("latin-1", errors="replace"))
        else:
            out.append(b.decode("latin-1", errors="replace"))
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Text extraction from content streams
# ---------------------------------------------------------------------------

_BT_ET = re.compile(rb"BT\b(.+?)\bET\b", re.DOTALL)
_STRING_RE = re.compile(rb"\(([^)\\]*(?:\\.[^)\\]*)*)\)")


def extract_text_from_stream(stream: bytes) -> str:
    """
    Extract human-readable text from a PDF content stream.

    Processes BT/ET blocks and collects literal strings from both simple
    ``(text) Tj`` and array-form ``[(s1)(s2)] TJ`` operations.  Each BT block
    is treated as a logical line; blocks are joined with newlines.
    """
    page_parts: List[str] = []
    for bt_m in _BT_ET.finditer(stream):
        block_parts: List[str] = []
        block = bt_m.group(1)
        for s_m in _STRING_RE.finditer(block):
            decoded = _decode_pdf_string(s_m.group(1))
            if decoded.strip():
                block_parts.append(decoded)
        if block_parts:
            page_parts.append(" ".join(block_parts))
    return "\n".join(page_parts)
