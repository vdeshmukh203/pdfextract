"""
pdfextract — standalone single-file edition.

Pure-Python PDF parser that reads cross-reference tables (classic and stream),
decodes FlateDecode content streams, extracts text from BT/ET blocks, reads
the PDF Info dictionary for metadata, and traverses the page tree in document
order.  Output formats: plain text, Markdown, or JSON.

This file is a self-contained copy of the library for users who prefer to run
without installing the package.  The canonical installable version lives in
``src/pdfextract/``.

Usage (CLI)::

    python pdfextract.py paper.pdf
    python pdfextract.py paper.pdf -f markdown -o paper.md
    python pdfextract.py paper.pdf -f json -p 5
"""
from __future__ import annotations

import json
import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PDFParseError(Exception):
    """Raised when a structural error prevents parsing."""


# ---------------------------------------------------------------------------
# Decompression
# ---------------------------------------------------------------------------


def _decode_flate(raw: bytes) -> bytes:
    try:
        return zlib.decompress(raw)
    except zlib.error:
        try:
            return zlib.decompress(raw, -15)
        except zlib.error:
            return raw


# ---------------------------------------------------------------------------
# Cross-reference parsing
# ---------------------------------------------------------------------------


def _find_xref_offset(data: bytes) -> int:
    tail = data[-2048:]
    m = re.search(rb"startxref\s+(\d+)", tail)
    if not m:
        raise PDFParseError("startxref not found in file")
    return int(m.group(1))


def _parse_xref_table(
    data: bytes, offset: int
) -> Tuple[Dict[int, int], Optional[int]]:
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
    return offsets, int(prev_m.group(1)) if prev_m else None


def _parse_xref_stream(
    data: bytes, offset: int
) -> Tuple[Dict[int, int], Optional[int]]:
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
        raise PDFParseError(f"xref stream: /W must have 3 entries, got {len(widths)}")
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
        body_start : body_start + (
            end_m.start() if end_m else len(chunk) - body_start
        )
    ]
    if b"FlateDecode" in chunk[: stream_m.start()]:
        raw = _decode_flate(raw)
    offsets: Dict[int, int] = {}
    pos = 0
    w0, w1 = widths[0], widths[1]

    def _rd(buf: bytes, w: int, default: int = 0) -> int:
        return default if w == 0 else int.from_bytes(buf[:w], "big")

    for first_obj, count in index_pairs:
        for j in range(count):
            if pos + entry_size > len(raw):
                break
            entry = raw[pos : pos + entry_size]
            pos += entry_size
            ftype = _rd(entry, w0, default=1)
            f1 = _rd(entry[w0:], w1)
            if ftype == 1:
                offsets[first_obj + j] = f1
    return offsets, prev


def _build_xref(data: bytes) -> Dict[int, int]:
    try:
        offset: Optional[int] = _find_xref_offset(data)
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
        except Exception:
            break
        for obj_id, byte_off in section.items():
            combined.setdefault(obj_id, byte_off)
        offset = prev  # type: ignore[assignment]
    return combined or _scan_objects(data)


def _scan_objects(data: bytes) -> Dict[int, int]:
    offsets: Dict[int, int] = {}
    for m in re.finditer(rb"(?<!\d)(\d+)\s+\d+\s+obj\b", data):
        obj_id = int(m.group(1))
        offsets.setdefault(obj_id, m.start())
    return offsets


# ---------------------------------------------------------------------------
# Object parsing
# ---------------------------------------------------------------------------


def _parse_obj(data: bytes, byte_off: int) -> bytes:
    window = data[byte_off : byte_off + 131072]
    m = re.search(rb"\d+\s+\d+\s+obj", window)
    if not m:
        raise PDFParseError(f"obj marker not found at offset {byte_off}")
    body_start = m.end()
    end_m = re.search(rb"endobj", window[body_start:])
    return window[
        body_start : body_start + (end_m.start() if end_m else len(window) - body_start)
    ]


def _extract_stream(obj_bytes: bytes) -> Optional[bytes]:
    sm = re.search(rb"stream\r?\n", obj_bytes)
    if not sm:
        return None
    body_start = sm.end()
    end_m = re.search(rb"endstream", obj_bytes[body_start:])
    raw = obj_bytes[
        body_start : body_start + (end_m.start() if end_m else len(obj_bytes))
    ]
    if b"FlateDecode" in obj_bytes[: sm.start()]:
        raw = _decode_flate(raw)
    return raw


def _resolve(data: bytes, xref: Dict[int, int], ref: str) -> Optional[bytes]:
    m = re.fullmatch(r"\s*(\d+)\s+\d+\s+R\s*", ref)
    if not m:
        return None
    obj_id = int(m.group(1))
    if obj_id not in xref:
        return None
    try:
        return _parse_obj(data, xref[obj_id])
    except PDFParseError:
        return None


# ---------------------------------------------------------------------------
# Dictionary helpers
# ---------------------------------------------------------------------------


def _dict_get(obj_bytes: bytes, key: str) -> Optional[str]:
    text = obj_bytes.decode("latin-1", errors="replace")
    pattern = (
        r"/" + re.escape(key) + r"\s+"
        r"(/\w+|<[^>]*>|\[[^\]]*\]|\([^)]*\)|-?\d+(?:\s+\d+\s+R)?|\d+(?:\.\d+)?)"
    )
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1).strip() if m else None


def _dict_get_refs(obj_bytes: bytes, key: str) -> List[str]:
    raw = _dict_get(obj_bytes, key)
    if raw is None:
        return []
    return re.findall(r"\d+\s+\d+\s+R", raw)


# ---------------------------------------------------------------------------
# Text extraction from content streams
# ---------------------------------------------------------------------------

_BT_ET_RE = re.compile(rb"BT(.+?)ET", re.DOTALL)
_STR_RE = re.compile(rb"\((?:[^)\\]|\\.)*\)")


def _decode_pdf_string(raw: bytes) -> str:
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
                out.append("\n"); i += 1
            elif esc == ord("r"):
                out.append("\r"); i += 1
            elif esc == ord("t"):
                out.append("\t"); i += 1
            elif esc in (ord("("), ord(")"), ord("\\")):
                out.append(chr(esc)); i += 1
            elif ord("0") <= esc <= ord("7"):
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
                out.append(chr(esc)); i += 1
        else:
            out.append(chr(b) if b < 128 else raw[i : i + 1].decode("latin-1"))
            i += 1
    return "".join(out)


def _extract_text_from_stream(stream: bytes) -> str:
    parts: List[str] = []
    for bt in _BT_ET_RE.finditer(stream):
        block = bt.group(1)
        for sm in _STR_RE.finditer(block):
            text = _decode_pdf_string(sm.group(0)[1:-1])
            if text.strip():
                parts.append(text.strip())
        for tj in re.finditer(rb"\[([^\]]+)\]\s*TJ", block):
            for sm in _STR_RE.finditer(tj.group(1)):
                text = _decode_pdf_string(sm.group(0)[1:-1])
                if text.strip():
                    parts.append(text.strip())
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class PageResult:
    page_number: int
    text: str
    word_count: int = field(init=False)
    char_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.word_count = len(self.text.split())
        self.char_count = len(self.text)


@dataclass
class ExtractionResult:
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

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_markdown(self) -> str:
        lines: List[str] = [
            f"# Extracted Text: {self.source}",
            "",
            f"**Pages**: {self.page_count} | **Words**: {self.word_count}",
            "",
        ]
        if self.metadata:
            lines += ["## Metadata", ""]
            for k, v in self.metadata.items():
                lines.append(f"- **{k}**: {v}")
            lines.append("")
        for page in self.pages:
            lines += [f"## Page {page.page_number}", "", page.text, ""]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class PDFExtractor:
    """Extract text and metadata from a PDF without external binaries.

    Parameters
    ----------
    path : str
        Path to the PDF file.
    max_pages : int, optional
        Maximum pages to extract (0 = all).
    """

    def __init__(self, path: str, max_pages: int = 0) -> None:
        self.path = Path(path)
        self.max_pages = max_pages
        self._data: bytes = b""
        self._xref: Dict[int, int] = {}

    def _load(self) -> None:
        self._data = self.path.read_bytes()
        if self._data[:4] != b"%PDF":
            raise PDFParseError(f"Not a PDF file: {self.path}")

    def _get_obj(self, obj_id: int) -> Optional[bytes]:
        if obj_id not in self._xref:
            return None
        try:
            return _parse_obj(self._data, self._xref[obj_id])
        except PDFParseError:
            return None

    def _resolve_ref(self, ref: str) -> Optional[bytes]:
        return _resolve(self._data, self._xref, ref)

    def _find_root_ref(self) -> Optional[str]:
        tail = self._data[-4096:].decode("latin-1", errors="replace")
        m = re.search(r"/Root\s+(\d+\s+\d+\s+R)", tail)
        if m:
            return m.group(1)
        for obj_id in self._xref:
            ob = self._get_obj(obj_id)
            if ob is None:
                continue
            txt = ob.decode("latin-1", errors="replace")
            if "/Type" in txt and "/XRef" in txt:
                m = re.search(r"/Root\s+(\d+\s+\d+\s+R)", txt)
                if m:
                    return m.group(1)
        return None

    def _extract_metadata(self) -> Dict[str, str]:
        tail = self._data[-4096:].decode("latin-1", errors="replace")
        info_m = re.search(r"/Info\s+(\d+\s+\d+\s+R)", tail)
        if not info_m:
            return {}
        info_bytes = self._resolve_ref(info_m.group(1))
        if info_bytes is None:
            return {}
        metadata: Dict[str, str] = {}
        for key in ("Title", "Author", "Subject", "Keywords", "Creator", "Producer"):
            raw = _dict_get(info_bytes, key)
            if raw:
                if raw.startswith("(") and raw.endswith(")"):
                    raw = raw[1:-1]
                metadata[key] = raw.strip()
        return metadata

    def _iter_pages(self, root_ref: str) -> Iterator[bytes]:
        catalog = self._resolve_ref(root_ref)
        if catalog is None:
            return
        pages_ref = _dict_get(catalog, "Pages")
        if pages_ref and re.search(r"\d+\s+\d+\s+R", pages_ref):
            yield from self._walk_tree(pages_ref)

    def _walk_tree(self, node_ref: str) -> Iterator[bytes]:
        node = self._resolve_ref(node_ref)
        if node is None:
            return
        if _dict_get(node, "Type") == "/Page":
            yield node
        else:
            for kid_ref in _dict_get_refs(node, "Kids"):
                yield from self._walk_tree(kid_ref)

    def _fallback_scan(self) -> Iterator[bytes]:
        for obj_id in sorted(self._xref):
            ob = self._get_obj(obj_id)
            if ob is None:
                continue
            txt = ob.decode("latin-1", errors="replace")
            if "/Type" in txt and "/Page" in txt and "/Pages" not in txt:
                yield ob

    def _page_text(self, page_obj: bytes) -> str:
        contents = _dict_get(page_obj, "Contents")
        if contents is None:
            return ""
        if contents.startswith("["):
            refs = re.findall(r"\d+\s+\d+\s+R", contents)
        elif re.search(r"\d+\s+\d+\s+R", contents):
            refs = [contents]
        else:
            return ""
        streams: List[bytes] = []
        for ref in refs:
            obj = self._resolve_ref(ref)
            if obj is not None:
                sd = _extract_stream(obj)
                if sd:
                    streams.append(sd)
        combined = b"\n".join(streams)
        return _extract_text_from_stream(combined) if combined else ""

    def extract(self) -> "ExtractionResult":
        """Run extraction. Returns ExtractionResult."""
        self._load()
        result = ExtractionResult(source=self.path.name, page_count=0)
        errors: List[str] = []
        try:
            self._xref = _build_xref(self._data)
        except Exception as exc:
            result.errors.append(f"xref error: {exc}")
            return result
        result.metadata = self._extract_metadata()
        root_ref = self._find_root_ref()
        page_src = (
            self._iter_pages(root_ref) if root_ref else self._fallback_scan()
        )
        pages: List[PageResult] = []
        for page_num, page_obj in enumerate(page_src, start=1):
            try:
                text = self._page_text(page_obj)
            except Exception as exc:
                errors.append(f"page {page_num}: {exc}")
                text = ""
            pages.append(PageResult(page_number=page_num, text=text))
            if self.max_pages and page_num >= self.max_pages:
                break
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
    """Extract text from a PDF and optionally write to a file.

    Parameters
    ----------
    path : str
        Input PDF path.
    output_format : str
        ``"text"``, ``"markdown"``, or ``"json"``.
    output_path : str, optional
        If given, write output to this file.
    max_pages : int
        Maximum pages to extract (0 = all).

    Returns
    -------
    str
        Extracted content in the requested format.
    """
    result = PDFExtractor(path, max_pages=max_pages).extract()
    if output_format == "json":
        out = result.to_json()
    elif output_format == "markdown":
        out = result.to_markdown()
    else:
        out = result.full_text
    if output_path:
        Path(output_path).write_text(out, encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="pdfextract",
        description="Extract text and metadata from PDF files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python pdfextract.py paper.pdf\n"
            "  python pdfextract.py paper.pdf -f markdown -o paper.md\n"
            "  python pdfextract.py paper.pdf -f json -p 5\n"
        ),
    )
    parser.add_argument("input", help="Path to input PDF file.")
    parser.add_argument("-o", "--output", default=None, metavar="FILE",
                        help="Write output to FILE instead of stdout.")
    parser.add_argument("-f", "--format",
                        choices=["text", "markdown", "json"],
                        default="text", dest="fmt", metavar="FORMAT")
    parser.add_argument("-p", "--max-pages", type=int, default=0, metavar="N",
                        help="Stop after N pages (0 = all).")
    args = parser.parse_args()
    out = extract_pdf(args.input, output_format=args.fmt,
                      output_path=args.output, max_pages=args.max_pages)
    if not args.output:
        print(out)
    else:
        print(f"Written to {args.output}")


if __name__ == "__main__":
    _cli()
