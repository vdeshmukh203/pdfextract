"""
pdfextract: Pure-Python structured text and metadata extractor for PDF files.

Extract text, tables, and metadata from PDF documents without requiring any
external binaries or third-party libraries.  Output can be emitted as plain
text, Markdown, or structured JSON.

Quick start
-----------
>>> from pdfextract import extract_pdf
>>> text = extract_pdf("paper.pdf")

>>> from pdfextract import PDFExtractor
>>> result = PDFExtractor("paper.pdf", max_pages=5).extract()
>>> print(result.word_count)
"""

__version__ = "0.2.0"
__author__ = "Vaibhav Deshmukh"
__license__ = "MIT"

from .extractor import PDFExtractor, extract_pdf
from .schema import ExtractionResult, PDFParseError, PageResult

__all__ = [
    "PDFExtractor",
    "ExtractionResult",
    "PageResult",
    "PDFParseError",
    "extract_pdf",
    "__version__",
]
