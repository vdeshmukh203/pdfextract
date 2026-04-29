"""Low-level PDF binary parser.

Handles PDF 1.x classic cross-reference tables and PDF 1.5+ cross-reference
streams. Traverses the page tree to return content streams in page order.
No external binary dependencies are required.
"""
from __future__ import annotations

import re
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


class PDFParseError(Exception):
    """Raised when a PDF file cannot be parsed."""


# ---------------------------------------------------------------------------
# String decoders
# ---------------------------------------------------------------------------

def _decode_flate(raw: bytes) -> bytes:
    """Decompress FlateDecode data, trying with and without the zlib header."""
    for wbits in (15, -15):
        try:
            return zlib.decompress(raw, wbits)
        except zlib.error:
            pass
    return raw


def _decode_hex_string(s: bytes) -> str:
    """Decode a PDF hex string (without angle brackets), e.g. b'48656c6c6f'."""
    hex_data = re.sub(rb"\s+", b"", s)
    if len(hex_data) % 2:
        hex_data += b"0"
    try:
        return bytes.fromhex(hex_data.decode("ascii", errors="replace")).decode(
            "latin-1", errors="replace"
        )
    except ValueError:
        return ""


def _decode_literal_string(s: bytes) -> str:
    """Decode a PDF literal string (without surrounding parentheses)."""
    out: List[str] = []
    i = 0
    while i < len(s):
        c = s[i : i + 1]
        if c == b"\\":
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
            elif nc == b"b":
                out.append("\b")
            elif nc == b"f":
                out.append("\f")
            elif nc in (b"(", b")", b"\\"):
                out.append(nc.decode("latin-1"))
            elif b"0" <= nc <= b"7":
                octal = s[i : i + 3]
                try:
                    out.append(chr(int(octal, 8)))
                    i += len(octal) - 1
                except ValueError:
                    out.append(nc.decode("latin-1", errors="replace"))
            else:
                out.append(nc.decode("latin-1", errors="replace"))
        else:
            out.append(c.decode("latin-1", errors="replace"))
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# PDFParser
# ---------------------------------------------------------------------------

class PDFParser:
    """Read and parse a PDF file, exposing page content streams and metadata.

    Parameters
    ----------
    path:
        Path to the PDF file to open.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: bytes = b""
        self._xref: Dict[int, int] = {}
        self._trailer: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Read and validate the file; build the cross-reference index."""
        self._data = self.path.read_bytes()
        if not self._data.startswith(b"%PDF"):
            raise PDFParseError(f"Not a PDF file: {self.path}")
        xref_offset = self._find_xref_offset()
        self._xref, self._trailer = self._parse_xref_chain(xref_offset, set())

    def get_metadata(self) -> Dict[str, str]:
        """Return selected PDF Info dictionary fields that are non-empty."""
        metadata: Dict[str, str] = {}
        info_ref = self._trailer.get("Info")
        if info_ref is None:
            return metadata
        body = self._get_object_body(int(info_ref))
        if body is None:
            return metadata

        fields = [
            "Title", "Author", "Subject", "Keywords",
            "Creator", "Producer", "CreationDate", "ModDate",
        ]
        for f in fields:
            key = f.encode()
            lit = re.search(rb"/" + key + rb"\s*\(([^)\\]*(?:\\.[^)\\]*)*)\)", body)
            if lit:
                metadata[f] = _decode_literal_string(lit.group(1))
                continue
            hex_m = re.search(rb"/" + key + rb"\s*<([0-9a-fA-F\s]*)>", body)
            if hex_m:
                metadata[f] = _decode_hex_string(hex_m.group(1))

        return {k: v for k, v in metadata.items() if v.strip()}

    def get_page_content_streams(self) -> List[Tuple[int, bytes]]:
        """Return ``(page_number, content_bytes)`` for every page, in order.

        Traverses the ``/Pages`` tree from the document catalog.  Falls back
        to a linear scan of all cross-referenced objects if the tree cannot
        be walked.
        """
        pages: List[Tuple[int, bytes]] = []

        root_ref = self._trailer.get("Root")
        if root_ref is not None:
            page_ids = self._collect_page_ids(int(root_ref))
            if page_ids:
                for page_num, obj_id in enumerate(page_ids, start=1):
                    body = self._get_object_body(obj_id)
                    if body is None:
                        continue
                    stream = self._content_stream_for_page(body)
                    if stream is not None:
                        pages.append((page_num, stream))
                return pages

        # Fallback: scan cross-reference table for /Type /Page objects
        page_num = 0
        for obj_id in sorted(self._xref.keys()):
            body = self._get_object_body(obj_id)
            if body is None:
                continue
            if re.search(rb"/Type\s*/Page\b", body):
                stream = self._content_stream_for_page(body)
                if stream is not None:
                    page_num += 1
                    pages.append((page_num, stream))
        return pages

    # ------------------------------------------------------------------
    # Cross-reference parsing
    # ------------------------------------------------------------------

    def _find_xref_offset(self) -> int:
        tail = self._data[-2048:]
        m = re.search(rb"startxref\s+(\d+)\s*%%EOF", tail)
        if not m:
            m = re.search(rb"startxref\s+(\d+)", tail)
        if not m:
            raise PDFParseError("startxref not found")
        return int(m.group(1))

    def _parse_xref_chain(
        self,
        offset: int,
        seen: Set[int],
    ) -> Tuple[Dict[int, int], Dict[str, Any]]:
        """Recursively parse linked xref tables/streams; later entries win."""
        if offset in seen:
            return {}, {}
        seen.add(offset)

        chunk = self._data[offset : offset + 65536]
        if re.match(rb"\s*xref", chunk):
            offsets, trailer = self._parse_classic_xref(chunk)
        else:
            offsets, trailer = self._parse_xref_stream(offset)

        prev = trailer.get("Prev")
        if prev is not None:
            prev_offsets, prev_trailer = self._parse_xref_chain(int(prev), seen)
            # Earlier xref has lower priority — only fill missing entries
            for k, v in prev_offsets.items():
                offsets.setdefault(k, v)
            for k, v in prev_trailer.items():
                trailer.setdefault(k, v)

        return offsets, trailer

    def _parse_classic_xref(
        self, chunk: bytes
    ) -> Tuple[Dict[int, int], Dict[str, Any]]:
        """Parse a traditional `xref` table plus its `trailer` dictionary."""
        offsets: Dict[int, int] = {}
        text = chunk.decode("latin-1", errors="replace")
        lines = text.splitlines()
        i = 0
        if i < len(lines) and lines[i].strip() == "xref":
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

        trailer = self._parse_trailer_dict(chunk)
        return offsets, trailer

    def _parse_xref_stream(
        self, offset: int
    ) -> Tuple[Dict[int, int], Dict[str, Any]]:
        """Parse a PDF 1.5+ cross-reference stream object."""
        offsets: Dict[int, int] = {}
        try:
            _, body = self._parse_obj_at(offset)
        except PDFParseError:
            return offsets, {}

        stream_bytes = self._extract_stream_bytes(body)
        if stream_bytes is None:
            return offsets, {}

        # Parse /W and /Index from the stream dictionary header
        hdr = body[: body.find(b"stream")]
        w_m = re.search(rb"/W\s*\[([^\]]+)\]", hdr)
        idx_m = re.search(rb"/Index\s*\[([^\]]+)\]", hdr)
        size_m = re.search(rb"/Size\s+(\d+)", hdr)

        if not w_m:
            return offsets, self._parse_trailer_dict(hdr)

        w = [int(x) for x in w_m.group(1).split()]
        if len(w) != 3:
            return offsets, {}
        w0, w1, w2 = w
        entry_size = w0 + w1 + w2

        size = int(size_m.group(1)) if size_m else 0
        if idx_m:
            idx = [int(x) for x in idx_m.group(1).split()]
        else:
            idx = [0, size]

        pos = 0
        seg = 0
        while seg + 1 < len(idx):
            first_obj = idx[seg]
            count = idx[seg + 1]
            seg += 2
            for j in range(count):
                if pos + entry_size > len(stream_bytes):
                    break
                entry = stream_bytes[pos : pos + entry_size]
                pos += entry_size
                type_field = (
                    int.from_bytes(entry[:w0], "big") if w0 else 1
                )
                f1 = (
                    int.from_bytes(entry[w0 : w0 + w1], "big") if w1 else 0
                )
                if type_field == 1:  # in-use uncompressed object
                    offsets[first_obj + j] = f1

        return offsets, self._parse_trailer_dict(hdr)

    def _parse_trailer_dict(self, data: bytes) -> Dict[str, Any]:
        """Extract /Root, /Info, /Prev, /Size from raw bytes."""
        result: Dict[str, Any] = {}
        for key in ("Root", "Info"):
            m = re.search(rb"/" + key.encode() + rb"\s+(\d+)\s+\d+\s+R", data)
            if m:
                result[key] = int(m.group(1))
        for key in ("Prev", "Size"):
            m = re.search(rb"/" + key.encode() + rb"\s+(\d+)", data)
            if m:
                result[key] = int(m.group(1))
        return result

    # ------------------------------------------------------------------
    # Object access
    # ------------------------------------------------------------------

    def _parse_obj_at(self, offset: int) -> Tuple[int, bytes]:
        chunk = self._data[offset : offset + 65536]
        m = re.search(rb"(\d+)\s+\d+\s+obj", chunk)
        if not m:
            raise PDFParseError(f"obj marker not found at offset {offset}")
        start = m.end()
        end_m = re.search(rb"endobj", chunk[start:])
        body = chunk[start : start + (end_m.start() if end_m else len(chunk[start:]))]
        return int(m.group(1)), body

    def _get_object_body(self, obj_id: int) -> Optional[bytes]:
        if obj_id not in self._xref:
            return None
        try:
            _, body = self._parse_obj_at(self._xref[obj_id])
            return body
        except PDFParseError:
            return None

    def _extract_stream_bytes(self, obj_body: bytes) -> Optional[bytes]:
        """Extract and decompress the data stream from an object body."""
        m = re.search(rb"stream\r?\n", obj_body)
        if not m:
            return None
        start = m.end()
        end_m = re.search(rb"\r?\nendstream", obj_body[start:])
        raw = obj_body[start : start + (end_m.start() if end_m else len(obj_body))]
        if b"FlateDecode" in obj_body[:start]:
            raw = _decode_flate(raw)
        return raw

    def get_stream(self, obj_id: int) -> Optional[bytes]:
        body = self._get_object_body(obj_id)
        return None if body is None else self._extract_stream_bytes(body)

    # ------------------------------------------------------------------
    # Page tree traversal
    # ------------------------------------------------------------------

    def _collect_page_ids(self, root_ref: int) -> List[int]:
        """Walk the /Pages tree from the document catalog; return page obj IDs."""
        catalog = self._get_object_body(root_ref)
        if catalog is None:
            return []
        m = re.search(rb"/Pages\s+(\d+)\s+\d+\s+R", catalog)
        if not m:
            return []
        page_ids: List[int] = []
        self._walk_pages(int(m.group(1)), page_ids, set())
        return page_ids

    def _walk_pages(
        self, node_id: int, page_ids: List[int], visited: Set[int]
    ) -> None:
        if node_id in visited:
            return
        visited.add(node_id)
        body = self._get_object_body(node_id)
        if body is None:
            return
        type_m = re.search(rb"/Type\s*/(\w+)", body)
        if not type_m:
            return
        node_type = type_m.group(1)
        if node_type == b"Page":
            page_ids.append(node_id)
        elif node_type == b"Pages":
            kids_m = re.search(rb"/Kids\s*\[([^\]]+)\]", body)
            if kids_m:
                for ref_m in re.finditer(rb"(\d+)\s+\d+\s+R", kids_m.group(1)):
                    self._walk_pages(int(ref_m.group(1)), page_ids, visited)

    # ------------------------------------------------------------------
    # Content stream resolution
    # ------------------------------------------------------------------

    def _content_stream_for_page(self, page_body: bytes) -> Optional[bytes]:
        """Resolve the /Contents entry of a page object to raw stream bytes."""
        # Single indirect reference: /Contents 5 0 R
        single_m = re.search(rb"/Contents\s+(\d+)\s+\d+\s+R", page_body)
        if single_m:
            return self.get_stream(int(single_m.group(1)))

        # Array of references: /Contents [5 0 R 6 0 R ...]
        array_m = re.search(rb"/Contents\s*\[([^\]]+)\]", page_body)
        if array_m:
            parts = []
            for ref_m in re.finditer(rb"(\d+)\s+\d+\s+R", array_m.group(1)):
                s = self.get_stream(int(ref_m.group(1)))
                if s:
                    parts.append(s)
            if parts:
                return b" ".join(parts)

        # Inline stream (unusual but valid for simple pages)
        return self._extract_stream_bytes(page_body)
