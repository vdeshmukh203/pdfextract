"""
pdfextract: Extract structured text and metadata from PDF files.

Pure-Python PDF parser (no external binaries required) that reads
cross-reference tables, follows incremental-update chains, decompresses
FlateDecode content streams, extracts text via BT/ET block parsing,
harvests document metadata from the Info dictionary, and outputs plain
text, Markdown, or JSON.  Supports single-file and batch (glob) modes.
Falls back gracefully on encrypted or structurally malformed PDFs.
"""
from __future__ import annotations

import glob as _glob_mod
import json
import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

__version__ = "0.1.0"
__author__ = "Vaibhav Deshmukh"
__license__ = "MIT"

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PDFParseError(Exception):
    """Raised when a file cannot be parsed as a PDF."""


# ---------------------------------------------------------------------------
# Low-level binary helpers
# ---------------------------------------------------------------------------


def _find_xref_offset(data: bytes) -> int:
    """Locate the ``startxref`` byte offset from the end of *data*."""
    tail = data[-2048:]
    m = re.search(rb"startxref\s+(\d+)", tail)
    if not m:
        raise PDFParseError("startxref marker not found")
    return int(m.group(1))


def _parse_xref_table(data: bytes, offset: int) -> Tuple[Dict[int, int], Optional[int]]:
    """
    Parse one classical cross-reference table starting at *offset*.

    Returns ``(offsets, prev_offset)`` where *prev_offset* is the value of
    the ``/Prev`` trailer key, or ``None`` if absent.
    """
    offsets: Dict[int, int] = {}
    # Use a 1 MiB window so large xref tables are not truncated.
    chunk = data[offset: offset + (1 << 20)].decode("latin-1", errors="replace")
    lines = chunk.splitlines()
    i = 0
    if lines and lines[i].strip() == "xref":
        i += 1
    while i < len(lines):
        header = lines[i].strip()
        hm = re.match(r"(\d+)\s+(\d+)", header)
        if not hm:
            break
        first_obj = int(hm.group(1))
        count = int(hm.group(2))
        i += 1
        for j in range(count):
            if i >= len(lines):
                break
            parts = lines[i].strip().split()
            i += 1
            if len(parts) >= 3 and parts[2] == "n":
                offsets[first_obj + j] = int(parts[0])
    # Extract /Prev from the trailer dictionary for xref chaining.
    prev: Optional[int] = None
    trailer_m = re.search(r"trailer\s*<<(.+?)>>", chunk, re.DOTALL)
    if trailer_m:
        prev_m = re.search(r"/Prev\s+(\d+)", trailer_m.group(1))
        if prev_m:
            prev = int(prev_m.group(1))
    return offsets, prev


def _collect_xref(data: bytes) -> Dict[int, int]:
    """Walk the full xref chain, merging all incremental updates."""
    offset: Optional[int] = _find_xref_offset(data)
    merged: Dict[int, int] = {}
    seen: set = set()
    while offset is not None and offset not in seen:
        seen.add(offset)
        partial, prev = _parse_xref_table(data, offset)
        # Earlier revisions have lower priority; do not overwrite later entries.
        for oid, off in partial.items():
            if oid not in merged:
                merged[oid] = off
        offset = prev
    return merged


# ---------------------------------------------------------------------------
# Object and stream parsing
# ---------------------------------------------------------------------------


def _parse_obj(data: bytes, byte_off: int) -> Tuple[int, bytes]:
    """
    Extract the body of one indirect object.

    Returns ``(obj_id, body_bytes)`` where *body_bytes* runs from after the
    ``obj`` keyword to just before ``endobj``.
    """
    chunk = data[byte_off: byte_off + (1 << 17)]  # 128 KiB window
    m = re.search(rb"(\d+)\s+\d+\s+obj", chunk)
    if not m:
        raise PDFParseError(f"obj marker not found at offset {byte_off}")
    oid = int(m.group(1))
    body_start = m.end()
    end_m = re.search(rb"\bendobj\b", chunk[body_start:])
    body = chunk[body_start: body_start + end_m.start()] if end_m else chunk[body_start:]
    return oid, body


def _decode_flate(raw: bytes) -> bytes:
    """Decompress a FlateDecode stream, tolerating common truncation issues."""
    for wbits in (15, -15):
        try:
            return zlib.decompress(raw, wbits)
        except zlib.error:
            pass
    try:
        d = zlib.decompressobj(-15)
        return d.decompress(raw) + d.flush(zlib.Z_SYNC_FLUSH)
    except zlib.error:
        return raw


def _extract_stream(obj_bytes: bytes) -> Optional[bytes]:
    """Extract and optionally decompress the stream data from an object body."""
    m = re.search(rb"stream\r?\n", obj_bytes)
    if not m:
        return None
    stream_start = m.end()
    end_m = re.search(rb"\bendstream\b", obj_bytes[stream_start:])
    raw = obj_bytes[stream_start: stream_start + (end_m.start() if end_m else len(obj_bytes))]
    if b"FlateDecode" in obj_bytes[:stream_start]:
        raw = _decode_flate(raw)
    return raw


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

_INFO_KEYS = (
    "Title", "Author", "Subject", "Keywords",
    "Creator", "Producer", "CreationDate", "ModDate",
)


def _extract_info_dict(data: bytes, xref: Dict[int, int]) -> Dict[str, str]:
    """
    Parse the PDF Info dictionary and return a ``{key: value}`` mapping.

    Handles both literal-string ``(…)`` and hex-string ``<…>`` encodings,
    including UTF-16 BE strings introduced by a ``0xFEFF`` BOM.
    """
    tail = data[-8192:].decode("latin-1", errors="replace")
    trailer_m = re.search(r"trailer\s*<<(.+?)>>", tail, re.DOTALL)
    if not trailer_m:
        return {}
    info_m = re.search(r"/Info\s+(\d+)\s+\d+\s+R", trailer_m.group(1))
    if not info_m:
        return {}
    info_id = int(info_m.group(1))
    if info_id not in xref:
        return {}
    try:
        _, obj_body = _parse_obj(data, xref[info_id])
    except PDFParseError:
        return {}

    result: Dict[str, str] = {}
    obj_text = obj_body.decode("latin-1", errors="replace")
    for key in _INFO_KEYS:
        # Literal string form: /Key (value)
        lm = re.search(r"/" + key + r"\s*\(([^)]*)\)", obj_text)
        if lm:
            result[key] = _decode_pdf_string(lm.group(1).encode("latin-1"))
            continue
        # Hex string form: /Key <hexdigits>
        hm = re.search(r"/" + key + r"\s*<([0-9a-fA-F\s]+)>", obj_text)
        if hm:
            hex_bytes = bytes.fromhex(re.sub(r"\s", "", hm.group(1)))
            if hex_bytes[:2] == b"\xfe\xff":
                result[key] = hex_bytes[2:].decode("utf-16-be", errors="replace")
            else:
                result[key] = hex_bytes.decode("latin-1", errors="replace")
    return result


# ---------------------------------------------------------------------------
# Text extraction from content streams
# ---------------------------------------------------------------------------

_BT_ET = re.compile(rb"BT(.+?)ET", re.DOTALL)
_STRING_RE = re.compile(rb"\(([^)\\]|\\.)*\)")


def _decode_pdf_string(s: bytes) -> str:
    """
    Decode a PDF literal string, correctly handling:

    * ``\\n`` ``\\r`` ``\\t`` ``\\(`` ``\\)`` ``\\\\`` escape sequences
    * Octal escapes ``\\ooo`` (1–3 digits)
    * Raw latin-1 bytes for all other characters
    """
    out: List[str] = []
    i = 0
    while i < len(s):
        b = s[i]
        if b == ord("\\"):
            i += 1
            if i >= len(s):
                break
            nc = s[i]
            if nc == ord("n"):
                out.append("\n")
            elif nc == ord("r"):
                out.append("\r")
            elif nc == ord("t"):
                out.append("\t")
            elif nc == ord("("):
                out.append("(")
            elif nc == ord(")"):
                out.append(")")
            elif nc == ord("\\"):
                out.append("\\")
            elif chr(nc).isdigit():
                # Octal: 1–3 digits; do NOT include the initial digit in i
                j = i
                while j < i + 3 and j < len(s) and chr(s[j]).isdigit():
                    j += 1
                out.append(chr(int(s[i:j].decode(), 8) & 0xFF))
                i = j
                continue  # skip the i += 1 below
            else:
                out.append(chr(nc))
        else:
            out.append(chr(b))
        i += 1
    return "".join(out)


def _extract_text_from_stream(stream: bytes) -> str:
    """Extract text from a PDF content stream via BT/ET block parsing."""
    parts: List[str] = []
    for bt_block in _BT_ET.finditer(stream):
        block = bt_block.group(1)
        # Literal strings used with Tj, Td, etc.
        for sm in _STRING_RE.finditer(block):
            raw = sm.group(0)[1:-1]  # strip outer parens
            parts.append(_decode_pdf_string(raw))
        # Array form used with TJ
        for tj_m in re.finditer(rb"\[([^\]]*)\]\s*TJ", block):
            for sm in _STRING_RE.finditer(tj_m.group(1)):
                raw = sm.group(0)[1:-1]
                parts.append(_decode_pdf_string(raw))
    return " ".join(p.strip() for p in parts if p.strip())


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class PageResult:
    """Text content extracted from one PDF page."""

    page_number: int  # 1-based
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
        """All pages joined by blank lines, skipping empty pages."""
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
        Stop after this many pages (0 = unlimited).
    """

    _PAGE_RE = re.compile(rb"/Type\s*/Page\b")

    def __init__(self, path: str, max_pages: int = 0) -> None:
        self.path = Path(path)
        self.max_pages = max_pages
        self._data: bytes = b""

    def _load(self) -> None:
        self._data = self.path.read_bytes()
        if not self._data.startswith(b"%PDF"):
            raise PDFParseError(f"Not a PDF file: {self.path}")

    def _get_xref(self) -> Dict[int, int]:
        return _collect_xref(self._data)

    def _get_page_streams(self, xref: Dict[int, int]) -> Iterator[Tuple[int, bytes]]:
        """Yield ``(page_number, content_stream_bytes)`` for each page."""
        page_num = 0
        for obj_id in sorted(xref.keys()):
            try:
                _, obj_body = _parse_obj(self._data, xref[obj_id])
            except PDFParseError:
                continue
            if not self._PAGE_RE.search(obj_body):
                continue
            stream = self._resolve_page_stream(obj_body, xref)
            page_num += 1
            yield page_num, stream if stream is not None else b""
            if self.max_pages and page_num >= self.max_pages:
                return

    def _resolve_page_stream(
        self, page_body: bytes, xref: Dict[int, int]
    ) -> Optional[bytes]:
        """
        Return the content stream for a page object.

        Tries three strategies in order:
        1. Inline stream in the page object itself.
        2. Single ``/Contents N M R`` indirect reference.
        3. ``/Contents [N M R …]`` array of references (streams concatenated).
        """
        # Strategy 1: inline stream
        stream = _extract_stream(page_body)
        if stream is not None:
            return stream

        # Strategy 2: single /Contents reference
        single_m = re.search(rb"/Contents\s+(\d+)\s+\d+\s+R", page_body)
        if single_m:
            ref_id = int(single_m.group(1))
            if ref_id in xref:
                try:
                    _, body = _parse_obj(self._data, xref[ref_id])
                    stream = _extract_stream(body)
                    if stream is not None:
                        return stream
                except PDFParseError:
                    pass

        # Strategy 3: /Contents array
        array_m = re.search(rb"/Contents\s*\[([^\]]+)\]", page_body)
        if array_m:
            parts: List[bytes] = []
            for ref_m in re.finditer(rb"(\d+)\s+\d+\s+R", array_m.group(1)):
                ref_id = int(ref_m.group(1))
                if ref_id in xref:
                    try:
                        _, body = _parse_obj(self._data, xref[ref_id])
                        s = _extract_stream(body)
                        if s:
                            parts.append(s)
                    except PDFParseError:
                        pass
            if parts:
                return b"\n".join(parts)

        return None

    def extract(self) -> ExtractionResult:
        """Run extraction and return an :class:`ExtractionResult`."""
        self._load()
        result = ExtractionResult(source=self.path.name, page_count=0)
        errors: List[str] = []
        try:
            xref = self._get_xref()
        except PDFParseError as exc:
            result.errors.append(f"xref error: {exc}")
            return result

        result.metadata = _extract_info_dict(self._data, xref)

        pages: List[PageResult] = []
        for page_num, stream in self._get_page_streams(xref):
            try:
                text = _extract_text_from_stream(stream) if stream else ""
            except Exception as exc:  # noqa: BLE001
                errors.append(f"page {page_num} error: {exc}")
                text = ""
            pages.append(PageResult(page_number=page_num, text=text))

        result.pages = pages
        result.page_count = len(pages)
        result.errors = errors
        return result


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


def extract_pdf(
    path: str,
    output_format: str = "text",
    output_path: Optional[str] = None,
    max_pages: int = 0,
) -> str:
    """
    Extract text from a single PDF file.

    Parameters
    ----------
    path : str
        Path to the input PDF.
    output_format : str
        ``"text"`` (default), ``"markdown"``, or ``"json"``.
    output_path : str, optional
        If provided, the extracted content is also written to this file.
    max_pages : int
        Maximum number of pages to process (0 = all).

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


def batch_extract(
    pattern: str,
    output_format: str = "text",
    output_dir: Optional[str] = None,
    max_pages: int = 0,
) -> List[ExtractionResult]:
    """
    Extract text from all PDFs matching a glob *pattern*.

    Parameters
    ----------
    pattern : str
        Glob pattern, e.g. ``"papers/*.pdf"``.
    output_format : str
        ``"text"``, ``"markdown"``, or ``"json"``.
    output_dir : str, optional
        Directory into which per-file output files are written.
    max_pages : int
        Per-file page limit (0 = all).

    Returns
    -------
    list of ExtractionResult
    """
    _ext_map = {"text": ".txt", "markdown": ".md", "json": ".json"}
    out_dir = Path(output_dir) if output_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    results: List[ExtractionResult] = []
    for pdf_path in sorted(_glob_mod.glob(pattern)):
        result = PDFExtractor(pdf_path, max_pages=max_pages).extract()
        results.append(result)
        if out_dir:
            out_file = out_dir / (Path(pdf_path).stem + _ext_map.get(output_format, ".txt"))
            if output_format == "json":
                out_file.write_text(
                    json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            elif output_format == "markdown":
                out_file.write_text(result.to_markdown(), encoding="utf-8")
            else:
                out_file.write_text(result.full_text, encoding="utf-8")
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="pdfextract",
        description="Extract structured text and metadata from PDF files.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    # ── extract (single file) ──────────────────────────────────────────────
    ep = sub.add_parser("extract", help="Extract text from a single PDF.")
    ep.add_argument("input", help="Path to the PDF file.")
    ep.add_argument("-o", "--output", default=None, help="Output file path.")
    ep.add_argument(
        "-f", "--format",
        choices=["text", "markdown", "json"],
        default="text",
        dest="fmt",
        help="Output format (default: text).",
    )
    ep.add_argument("-p", "--max-pages", type=int, default=0,
                    help="Maximum pages to extract (0 = all).")

    # ── batch ─────────────────────────────────────────────────────────────
    bp = sub.add_parser("batch", help="Extract multiple PDFs matching a glob.")
    bp.add_argument("pattern", help="Glob pattern, e.g. 'papers/*.pdf'.")
    bp.add_argument("-d", "--output-dir", default=None,
                    help="Directory for output files.")
    bp.add_argument(
        "-f", "--format",
        choices=["text", "markdown", "json"],
        default="text",
        dest="fmt",
    )
    bp.add_argument("-p", "--max-pages", type=int, default=0)

    # ── gui ───────────────────────────────────────────────────────────────
    sub.add_parser("gui", help="Launch the graphical user interface.")

    # ── legacy positional (no subcommand) ─────────────────────────────────
    parser.add_argument("input_file", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("-o", "--output", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "-f", "--format",
        choices=["text", "markdown", "json"],
        default="text",
        dest="fmt",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("-p", "--max-pages", type=int, default=0,
                        help=argparse.SUPPRESS)

    args = parser.parse_args()

    if args.command == "gui":
        from pdfextract_gui import main as _gui_main
        _gui_main()
        return

    if args.command == "batch":
        results = batch_extract(
            args.pattern,
            output_format=args.fmt,
            output_dir=args.output_dir,
            max_pages=args.max_pages,
        )
        print(f"Processed {len(results)} file(s).")
        return

    # Single file — either via 'extract' subcommand or legacy positional arg.
    pdf_path = getattr(args, "input", None) or getattr(args, "input_file", None)
    if not pdf_path:
        parser.print_help()
        sys.exit(0)
    out = extract_pdf(
        pdf_path,
        output_format=args.fmt,
        output_path=args.output,
        max_pages=args.max_pages,
    )
    if not args.output:
        print(out)
    else:
        print(f"Written to {args.output}")


if __name__ == "__main__":
    _cli()
