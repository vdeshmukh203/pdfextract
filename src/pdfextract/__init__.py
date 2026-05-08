"""
pdfextract: Pure-Python structured text and metadata extractor for PDF files.

Extract text, metadata, and structured output from PDF documents without
external binaries or native library dependencies.

Basic usage::

    from pdfextract import PDFExtractor, extract_pdf

    # High-level convenience function
    text = extract_pdf("paper.pdf")
    markdown = extract_pdf("paper.pdf", output_format="markdown")

    # Full result with per-page data and metadata
    result = PDFExtractor("paper.pdf").extract()
    print(result.metadata.get("Title"))
    for page in result.pages:
        print(page.page_number, page.word_count)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .extractor import PDFExtractor
from .parser import PDFParseError
from .schema import ExtractionResult, PageResult

__version__ = "0.2.0"
__author__ = "Vaibhav Deshmukh"
__license__ = "MIT"


def extract_pdf(
    path: str,
    output_format: str = "text",
    output_path: Optional[str] = None,
    max_pages: int = 0,
) -> str:
    """Extract text from a PDF and optionally write the result to a file.

    Parameters
    ----------
    path : str
        Path to the input PDF file.
    output_format : str
        ``"text"`` (default), ``"markdown"``, or ``"json"``.
    output_path : str, optional
        If given, write output to this file path.
    max_pages : int
        Maximum number of pages to extract (``0`` = all pages).

    Returns
    -------
    str
        Extracted content in the requested format.

    Raises
    ------
    PDFParseError
        If the input file is not a valid PDF.
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


__all__ = [
    "PDFExtractor",
    "PDFParseError",
    "ExtractionResult",
    "PageResult",
    "extract_pdf",
]
