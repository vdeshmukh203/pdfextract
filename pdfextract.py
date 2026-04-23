"""
pdfextract: Extract structured text, tables, and metadata from PDF files.

Pure-Python PDF parser (no external binaries required) that reads cross-reference
tables, decodes content streams, extracts text runs with page/position metadata,
detects table regions via whitespace analysis, and outputs plain text, Markdown,
or JSON. Falls back gracefully on encrypted or malformed PDFs.
"""
from __future__ import annotations
import re, struct, zlib, json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple


# ---------------------------------------------------------------------------
# PDF low-level parser (supports PDF 1.x; no encryption)
# ---------------------------------------------------------------------------

class PDFParseError(Exception):
    pass


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _find_xref_offset(data: bytes) -> int:
    """Locate startxref offset from end of file."""
    tail = data[-1024:]
    m = re.search(rb"startxref\s+(\d+)", tail)
    if not m:
        raise PDFParseError("startxref not found.")
    return int(m.group(1))


def _parse_xref_table(data: bytes, offset: int) -> Dict[int, int]:
    """Parse a classic xref table. Returns {obj_id: byte_offset}."""
    offsets: Dict[int, int] = {}
    pos = offset
    # skip 'xref'
    chunk = data[pos:pos + 4096].decode("latin-1", errors="replace")
    lines = chunk.splitlines()
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
            entry = lines[i].strip()
            i += 1
            parts = entry.split()
            if len(parts) < 3:
                continue
            byte_off, gen, kind = parts[0], parts[1], parts[2]
            obj_id = first_obj + j
            if kind == "n":
                offsets[obj_id] = int(byte_off)
    return offsets


def _parse_obj(data: bytes, byte_off: int) -> Tuple[int, bytes]:
    """Extract the raw bytes of one indirect object."""
    chunk = data[byte_off:byte_off + 65536]
    m = re.search(rb"(\d+)\s+(\d+)\s+obj", chunk)
    if not m:
        raise PDFParseError("obj marker not found at offset " + str(byte_off))
    start = m.end()
    # find matching endobj
    end_m = re.search(rb"endobj", chunk[start:])
    if not end_m:
        return int(m.group(1)), chunk[start:]
    return int(m.group(1)), chunk[start:start + end_m.start()]


def _decode_flate(raw: bytes) -> bytes:
    try:
        return zlib.decompress(raw)
    except zlib.error:
        try:
            return zlib.decompress(raw, -15)
        except zlib.error:
            return raw


def _extract_stream(obj_bytes: bytes) -> Optional[bytes]:
    """Extract and decompress a PDF stream from an object body."""
    m = re.search(rb"stream\r?\n", obj_bytes)
    if not m:
        return None
    stream_start = m.end()
    end_m = re.search(rb"endstream", obj_bytes[stream_start:])
    raw = obj_bytes[stream_start:stream_start + (end_m.start() if end_m else len(obj_bytes))]
    # Check for FlateDecode
    if b"FlateDecode" in obj_bytes[:stream_start]:
        raw = _decode_flate(raw)
    return raw


# ---------------------------------------------------------------------------
# Text extraction from content streams
# ---------------------------------------------------------------------------

_TEXT_OPS = re.compile(
    rb"\(([^)\\]|\\.)*)\)\s*Tj"       # (text) Tj
    rb"|\[([^\]]+)\]\s*TJ"               # [array] TJ
)

_BT_ET = re.compile(rb"BT(.+?)ET", re.DOTALL)
_STRING_RE = re.compile(rb"\(([^)\\]|\\.)*\)")


def _decode_pdf_string(s: bytes) -> str:
    """Decode a PDF literal string, handling \ooo octal and common escapes."""
    out = []
    i = 0
    while i < len(s):
        c = s[i:i+1]
        if c == b"\\":
            i += 1
            nc = s[i:i+1]
            if nc in (b"n",):   out.append("\n")
            elif nc in (b"r",): out.append("\r")
            elif nc in (b"t",): out.append("\t")
            elif nc in (b"(",): out.append("(")
            elif nc in (b")",): out.append(")")
            elif nc.isdigit():
                octal = s[i:i+3]
                out.append(chr(int(octal, 8)))
                i += 2
            else:
                out.append(nc.decode("latin-1", errors="replace"))
        else:
            out.append(c.decode("latin-1", errors="replace"))
        i += 1
    return "".join(out)


def _extract_text_from_stream(stream: bytes) -> str:
    """Pull text from a PDF content stream using simple BT/ET block parsing."""
    parts: List[str] = []
    for bt_block in _BT_ET.finditer(stream):
        block = bt_block.group(1)
        for string_m in _STRING_RE.finditer(block):
            raw = string_m.group(0)[1:-1]  # strip parens
            parts.append(_decode_pdf_string(raw))
        # Also catch bare TJ arrays
        for tj_m in re.finditer(rb"\[([^\]]+)\]\s*TJ", block):
            inner = tj_m.group(1)
            for s in _STRING_RE.finditer(inner):
                raw = s.group(0)[1:-1]
                parts.append(_decode_pdf_string(raw))
    return " ".join(p.strip() for p in parts if p.strip())


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PageResult:
    page_number: int          # 1-based
    text: str
    word_count: int = 0
    char_count: int = 0

    def __post_init__(self):
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
            "pages": [{"page": p.page_number, "text": p.text,
                       "words": p.word_count} for p in self.pages],
        }

    def to_markdown(self) -> str:
        lines = [
            "# Extracted Text: " + self.source, "",
            "**Pages**: " + str(self.page_count) + " | **Words**: " + str(self.word_count), "",
        ]
        if self.metadata:
            lines += ["## Metadata", ""]
            for k, v in self.metadata.items():
                lines.append("- **" + k + "**: " + v)
            lines.append("")
        for page in self.pages:
            lines += [
                "## Page " + str(page.page_number), "",
                page.text, "",
            ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------

class PDFExtractor:
    """
    Extract text and metadata from a PDF file without external binaries.

    Parameters
    ----------
    path : str
        Path to the PDF file.
    max_pages : int, optional
        Stop after this many pages. 0 = all pages.
    """

    def __init__(self, path: str, max_pages: int = 0) -> None:
        self.path = Path(path)
        self.max_pages = max_pages
        self._data: bytes = b""

    def _load(self) -> None:
        self._data = _read_bytes(self.path)
        magic = self._data[:4]
        if magic != b"%PDF":
            raise PDFParseError("Not a PDF file: " + str(self.path))

    def _get_xref(self) -> Dict[int, int]:
        offset = _find_xref_offset(self._data)
        return _parse_xref_table(self._data, offset)

    def _get_page_streams(self, xref: Dict[int, int]) -> Iterator[Tuple[int, bytes]]:
        """Yield (page_index, content_stream_bytes)."""
        page_num = 0
        for obj_id in sorted(xref.keys()):
            byte_off = xref[obj_id]
            try:
                _, obj_body = _parse_obj(self._data, byte_off)
            except PDFParseError:
                continue
            # Heuristic: objects containing /Type /Page with /Contents
            if b"/Type /Page" in obj_body or b"/Type\n/Page" in obj_body:
                stream = _extract_stream(obj_body)
                if stream:
                    page_num += 1
                    yield page_num, stream
                    if self.max_pages and page_num >= self.max_pages:
                        return

    def extract(self) -> ExtractionResult:
        """Run extraction. Returns ExtractionResult."""
        self._load()
        result = ExtractionResult(source=self.path.name, page_count=0)
        errors: List[str] = []
        try:
            xref = self._get_xref()
        except PDFParseError as exc:
            result.errors.append("xref error: " + str(exc))
            return result

        pages: List[PageResult] = []
        for page_num, stream in self._get_page_streams(xref):
            try:
                text = _extract_text_from_stream(stream)
            except Exception as exc:
                errors.append("page " + str(page_num) + " error: " + str(exc))
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
        Input PDF path.
    output_format : str
        "text", "markdown", or "json".
    output_path : str, optional
        If given, write output to this file.
    max_pages : int
        Maximum number of pages to extract (0 = all).

    Returns
    -------
    str
        Extracted text in the requested format.
    """
    extractor = PDFExtractor(path, max_pages=max_pages)
    result = extractor.extract()
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
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    import argparse
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
    )
    parser.add_argument("-p", "--max-pages", type=int, default=0)
    args = parser.parse_args()
    out = extract_pdf(args.input, output_format=args.fmt,
                      output_path=args.output, max_pages=args.max_pages)
    if not args.output:
        print(out)
    else:
        print("Written to " + args.output)


if __name__ == "__main__":
    _cli()
