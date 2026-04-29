"""
pdfextract: Pure-Python structured text and metadata extractor for PDF files.

Reads cross-reference tables (classic xref and PDF 1.5+ xref streams),
traverses the page tree, decodes content streams, and outputs plain text,
Markdown, or JSON. Falls back gracefully on malformed PDFs. An optional
Tk-based graphical interface is available via ``pdfextract --gui``.

Typical usage::

    from pdfextract import extract_pdf, PDFExtractor

    # One-shot convenience wrapper
    text = extract_pdf("paper.pdf")

    # Full result object with per-page data and metadata
    result = PDFExtractor("paper.pdf").extract()
    print(result.word_count, result.metadata)
"""
from __future__ import annotations

__version__ = "0.2.0"
__author__ = "Vaibhav Deshmukh"
__license__ = "MIT"

from .extractor import PDFExtractor, extract_pdf
from .parser import PDFParseError
from .schema import ExtractionResult, PageResult

__all__ = [
    "PDFExtractor",
    "ExtractionResult",
    "PageResult",
    "PDFParseError",
    "extract_pdf",
]
