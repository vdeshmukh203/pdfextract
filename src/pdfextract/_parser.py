"""Low-level pure-Python PDF parser (PDF 1.x, no encryption)."""
from __future__ import annotations
import re
import zlib
from typing import Dict, List, Optional, Tuple


class PDFParseError(Exception):
    pass


# ---------------------------------------------------------------------------
# Cross-reference and trailer
# ---------------------------------------------------------------------------

def find_xref_offset(data: bytes) -> int:
    tail = data[-1024:]
    m = re.search(rb"startxref\s+(\d+)", tail)
    if not m:
        raise PDFParseError("startxref not found")
    return int(m.group(1))


def parse_xref_and_trailer(data: bytes, offset: int) -> Tuple[Dict[int, int], Dict]:
    """Parse classic xref table plus trailer dict. Returns (offsets, trailer)."""
    offsets: Dict[int, int] = {}
    chunk = data[offset:offset + 131072]
    text = chunk.decode("latin-1", errors="replace")
    lines = text.splitlines()
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

    trailer: Dict = {}
    trailer_m = re.search(rb"trailer\s*<<(.+?)>>", chunk, re.DOTALL)
    if trailer_m:
        trailer = _parse_dict_refs(trailer_m.group(1))
    return offsets, trailer


def _parse_dict_refs(raw: bytes) -> Dict:
    """Extract key→(obj_id, gen) or key→int from a flat PDF dict bytes."""
    result: Dict = {}
    for m in re.finditer(
        rb"/(\w+)\s+(?:(\d+)\s+(\d+)\s+R|(\d+))",
        raw,
    ):
        key = m.group(1).decode("latin-1")
        if m.group(2) is not None:
            result[key] = ("ref", int(m.group(2)))
        elif m.group(4) is not None:
            result[key] = int(m.group(4))
    return result


# ---------------------------------------------------------------------------
# Object access
# ---------------------------------------------------------------------------

def get_obj_body(data: bytes, byte_off: int) -> Tuple[int, bytes]:
    chunk = data[byte_off:byte_off + 131072]
    m = re.search(rb"(\d+)\s+\d+\s+obj", chunk)
    if not m:
        raise PDFParseError(f"obj marker not found at offset {byte_off}")
    start = m.end()
    end_m = re.search(rb"\bendobj\b", chunk[start:])
    body = chunk[start: start + end_m.start()] if end_m else chunk[start:]
    return int(m.group(1)), body


def _decode_flate(raw: bytes) -> bytes:
    for wbits in (15, -15):
        try:
            return zlib.decompress(raw, wbits)
        except zlib.error:
            pass
    return raw


def extract_stream(obj_body: bytes) -> Optional[bytes]:
    m = re.search(rb"stream\r?\n", obj_body)
    if not m:
        return None
    start = m.end()
    end_m = re.search(rb"endstream", obj_body[start:])
    raw = obj_body[start: start + end_m.start()] if end_m else obj_body[start:]
    if b"FlateDecode" in obj_body[:start]:
        raw = _decode_flate(raw)
    return raw


# ---------------------------------------------------------------------------
# Page tree traversal
# ---------------------------------------------------------------------------

def _resolve_ref(trailer_or_dict: Dict, key: str) -> Optional[int]:
    v = trailer_or_dict.get(key)
    if isinstance(v, tuple) and v[0] == "ref":
        return v[1]
    return None


def _walk_page_tree(
    data: bytes,
    xref: Dict[int, int],
    node_id: int,
    out: List[bytes],
    depth: int = 0,
) -> None:
    if depth > 64 or node_id not in xref:
        return
    try:
        _, body = get_obj_body(data, xref[node_id])
    except PDFParseError:
        return

    is_pages = b"/Type /Pages" in body or b"/Type\n/Pages" in body
    if is_pages:
        kids_m = re.search(rb"/Kids\s*\[([^\]]+)\]", body)
        if kids_m:
            for kid_id in re.findall(rb"(\d+)\s+\d+\s+R", kids_m.group(1)):
                _walk_page_tree(data, xref, int(kid_id), out, depth + 1)
    else:
        # Treat any non-Pages node as a Page
        out.append(body)


def get_page_bodies(
    data: bytes,
    xref: Dict[int, int],
    trailer: Dict,
) -> List[bytes]:
    """Return ordered list of Page object bodies by walking the page tree."""
    root_id = _resolve_ref(trailer, "Root")
    if root_id is None or root_id not in xref:
        return _fallback_page_bodies(data, xref)

    try:
        _, catalog = get_obj_body(data, xref[root_id])
    except PDFParseError:
        return _fallback_page_bodies(data, xref)

    pages_m = re.search(rb"/Pages\s+(\d+)\s+\d+\s+R", catalog)
    if not pages_m:
        return _fallback_page_bodies(data, xref)

    pages_root = int(pages_m.group(1))
    out: List[bytes] = []
    _walk_page_tree(data, xref, pages_root, out)
    return out if out else _fallback_page_bodies(data, xref)


def _fallback_page_bodies(data: bytes, xref: Dict[int, int]) -> List[bytes]:
    """Scan all objects for /Type /Page as a last-resort fallback."""
    pages = []
    for obj_id in sorted(xref.keys()):
        try:
            _, body = get_obj_body(data, xref[obj_id])
        except PDFParseError:
            continue
        if b"/Type /Page" in body or b"/Type\n/Page" in body:
            pages.append(body)
    return pages


def get_content_stream(
    data: bytes,
    xref: Dict[int, int],
    page_body: bytes,
) -> Optional[bytes]:
    """Resolve /Contents reference(s) and return the combined content stream."""
    # Single reference: /Contents 5 0 R
    single = re.search(rb"/Contents\s+(\d+)\s+\d+\s+R", page_body)
    if single:
        cid = int(single.group(1))
        if cid in xref:
            try:
                _, cbody = get_obj_body(data, xref[cid])
                return extract_stream(cbody)
            except PDFParseError:
                pass

    # Array: /Contents [5 0 R 6 0 R ...]
    arr = re.search(rb"/Contents\s*\[([^\]]+)\]", page_body)
    if arr:
        parts = []
        for cid in re.findall(rb"(\d+)\s+\d+\s+R", arr.group(1)):
            cid = int(cid)
            if cid in xref:
                try:
                    _, cbody = get_obj_body(data, xref[cid])
                    s = extract_stream(cbody)
                    if s:
                        parts.append(s)
                except PDFParseError:
                    pass
        if parts:
            return b" ".join(parts)

    # Inline stream on the page object itself (rare)
    return extract_stream(page_body)


# ---------------------------------------------------------------------------
# Metadata from /Info dictionary
# ---------------------------------------------------------------------------

_INFO_KEYS = ("Title", "Author", "Subject", "Keywords", "Creator", "Producer")


def get_metadata(data: bytes, xref: Dict[int, int], trailer: Dict) -> Dict[str, str]:
    info_id = _resolve_ref(trailer, "Info")
    if info_id is None or info_id not in xref:
        return {}
    try:
        _, body = get_obj_body(data, xref[info_id])
    except PDFParseError:
        return {}

    meta: Dict[str, str] = {}
    for key in _INFO_KEYS:
        m = re.search(rb"/" + key.encode() + rb"\s*\(([^)]*(?:\\.[^)]*)*)\)", body)
        if m:
            meta[key] = _decode_pdf_string(m.group(1))
    return meta


# ---------------------------------------------------------------------------
# Text extraction from content streams
# ---------------------------------------------------------------------------

_BT_ET = re.compile(rb"BT(.+?)ET", re.DOTALL)
_STRING_RE = re.compile(rb"\(([^)\\]|\\.)*\)")
_TJ_ARRAY = re.compile(rb"\[([^\]]+)\]\s*TJ")


def extract_text_from_stream(stream: bytes) -> str:
    """Extract text from a PDF content stream, avoiding duplicate extraction."""
    parts: List[str] = []
    for bt in _BT_ET.finditer(stream):
        block = bt.group(1)
        # Track positions covered by TJ arrays so we don't double-extract
        tj_spans = set()
        for tj in _TJ_ARRAY.finditer(block):
            inner = tj.group(1)
            for s in _STRING_RE.finditer(inner):
                parts.append(_decode_pdf_string(s.group(0)[1:-1]))
            tj_spans.add((tj.start(), tj.end()))

        # Extract remaining Tj / TD strings not inside TJ arrays
        for s in _STRING_RE.finditer(block):
            # Skip strings already consumed by TJ array processing
            pos = s.start()
            in_tj = any(a <= pos < b for a, b in tj_spans)
            if not in_tj:
                parts.append(_decode_pdf_string(s.group(0)[1:-1]))

    return " ".join(p.strip() for p in parts if p.strip())


def _decode_pdf_string(s: bytes) -> str:
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
            elif nc in (b"(", b")"):
                out.append(nc.decode("latin-1"))
            elif nc.isdigit():
                octal = s[i:i + 3]
                try:
                    out.append(chr(int(octal, 8)))
                except ValueError:
                    out.append(nc.decode("latin-1", errors="replace"))
                i += 2  # outer loop adds 1 more → 3 total
            else:
                out.append(nc.decode("latin-1", errors="replace"))
        else:
            out.append(c.decode("latin-1", errors="replace"))
        i += 1
    return "".join(out)
