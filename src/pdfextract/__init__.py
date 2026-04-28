"""
pdfextract: Extract structured text and metadata from PDF files.

Pure-Python PDF parser (no external binaries required) that reads cross-reference
tables, decodes content streams, extracts text runs with page metadata,
and outputs plain text, Markdown, or JSON.  Degrades gracefully on encrypted
or malformed PDFs rather than raising unhandled exceptions.

Quick start::

    from pdfextract import extract_pdf, PDFExtractor

    # One-shot helper
    text = extract_pdf("paper.pdf")

    # Full result object
    from pdfextract import PDFExtractor
    result = PDFExtractor("paper.pdf").extract()
    print(result.page_count, result.word_count)
    print(result.to_markdown())
"""

__version__ = "0.2.0"
__author__ = "Vaibhav Deshmukh"
__license__ = "MIT"

from ._extractor import PDFExtractor, extract_pdf
from ._parser import PDFParseError
from ._schema import ExtractionResult, PageResult

__all__ = [
    "PDFExtractor",
    "ExtractionResult",
    "PageResult",
    "PDFParseError",
    "extract_pdf",
]
