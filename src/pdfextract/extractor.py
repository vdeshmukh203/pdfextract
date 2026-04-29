"""PDF text extractor, public API, and CLI entry point."""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from .parser import PDFParseError, PDFParser, _decode_hex_string, _decode_literal_string
from .schema import ExtractionResult, PageResult

# ---------------------------------------------------------------------------
# Content-stream text extraction
# ---------------------------------------------------------------------------

_BT_ET = re.compile(rb"BT(.+?)ET", re.DOTALL)
_LITERAL_STR = re.compile(rb"\(([^)\\]*(?:\\.[^)\\]*)*)\)")
_HEX_STR = re.compile(rb"<([0-9a-fA-F\s]+)>")


def _strings_from_block(block: bytes) -> List[str]:
    """Extract all text strings from a single BT…ET block."""
    parts: List[str] = []

    # Collect raw positions and strings, then sort by byte position so that
    # TJ arrays and standalone Tj calls are interleaved in stream order.
    tokens: List[tuple] = []  # (start_pos, text)

    for m in _LITERAL_STR.finditer(block):
        tokens.append((m.start(), _decode_literal_string(m.group(1))))

    # Hex strings that appear inside TJ arrays
    for tj_m in re.finditer(rb"\[([^\]]+)\]\s*TJ", block):
        inner = tj_m.group(1)
        for hm in _HEX_STR.finditer(inner):
            tokens.append((tj_m.start(), _decode_hex_string(hm.group(1))))

    tokens.sort(key=lambda t: t[0])
    return [text for _, text in tokens]


def _extract_text_from_stream(stream: bytes) -> str:
    """Pull all text from a PDF content stream via BT/ET block parsing."""
    parts: List[str] = []
    for bt_block in _BT_ET.finditer(stream):
        block_parts = _strings_from_block(bt_block.group(1))
        parts.extend(block_parts)
    return " ".join(p.strip() for p in parts if p.strip())


# ---------------------------------------------------------------------------
# Public extractor class
# ---------------------------------------------------------------------------

class PDFExtractor:
    """Extract text and metadata from a PDF file without external binaries.

    Parameters
    ----------
    path:
        Path to the PDF file.
    max_pages:
        Stop after this many pages; ``0`` means extract all pages.
    """

    def __init__(self, path: str, max_pages: int = 0) -> None:
        self.path = Path(path)
        self.max_pages = max_pages

    def extract(self) -> ExtractionResult:
        """Run extraction and return an :class:`~pdfextract.ExtractionResult`."""
        result = ExtractionResult(source=self.path.name, page_count=0)
        parser = PDFParser(self.path)

        try:
            parser.load()
        except PDFParseError as exc:
            result.errors.append(f"load error: {exc}")
            return result
        except OSError as exc:
            result.errors.append(f"file error: {exc}")
            return result

        try:
            result.metadata = parser.get_metadata()
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"metadata error: {exc}")

        try:
            page_streams = parser.get_page_content_streams()
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"page listing error: {exc}")
            return result

        pages: List[PageResult] = []
        for page_num, stream in page_streams:
            if self.max_pages and page_num > self.max_pages:
                break
            try:
                text = _extract_text_from_stream(stream)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"page {page_num} text error: {exc}")
                text = ""
            pages.append(PageResult(page_number=page_num, text=text))

        result.pages = pages
        result.page_count = len(pages)
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
    """Extract text from *path* and return it as a string.

    Parameters
    ----------
    path:
        Input PDF path.
    output_format:
        ``"text"`` (default), ``"markdown"``, or ``"json"``.
    output_path:
        If provided, write the output to this file path.
    max_pages:
        Maximum number of pages to process; ``0`` means all pages.

    Returns
    -------
    str
        Extracted content in the requested format.
    """
    extractor = PDFExtractor(path, max_pages=max_pages)
    result = extractor.extract()

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
        description="Extract structured text and metadata from PDF files.",
    )
    parser.add_argument("input", nargs="?", help="Path to input PDF file.")
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
        help="Maximum pages to extract (0 = all).",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the graphical user interface.",
    )
    args = parser.parse_args()

    if args.gui:
        from .gui import _gui
        _gui()
        return

    if not args.input:
        parser.print_help()
        return

    out = extract_pdf(
        args.input,
        output_format=args.fmt,
        output_path=args.output,
        max_pages=args.max_pages,
    )
    if args.output:
        print(f"Written to {args.output}")
    else:
        print(out)
