"""
pdfextract: Pure-Python structured text and metadata extractor for PDF files.

Reads PDF cross-reference tables, decodes FlateDecode content streams, and
extracts text runs with page-level metadata. Outputs plain text, Markdown,
or JSON. Supports PDF 1.x–1.7 (classic xref tables and PDF 1.5+ xref streams).
"""

__version__ = "0.2.0"
__author__ = "Vaibhav Deshmukh"
__license__ = "MIT"

from .extractor import PDFExtractor, extract_pdf, _cli
from .schema import ExtractionResult, PageResult, PDFParseError

__all__ = [
    "PDFExtractor",
    "ExtractionResult",
    "PageResult",
    "PDFParseError",
    "extract_pdf",
]
