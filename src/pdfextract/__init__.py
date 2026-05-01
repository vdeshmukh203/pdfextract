"""
pdfextract: Structured extraction of text, tables, and metadata from scientific PDFs.

Pure-Python PDF parser (no external binaries) that reads cross-reference tables,
decodes content streams, resolves page-content references, and outputs plain text,
Markdown, or JSON. Includes a Tkinter GUI (``pdfextract-gui``) and a CLI
(``pdfextract``).

Quick start::

    from pdfextract import extract_pdf
    text = extract_pdf("paper.pdf")

    from pdfextract import PDFExtractor
    result = PDFExtractor("paper.pdf").extract()
    print(result.metadata)
"""

__version__ = "0.2.0"
__author__ = "Vaibhav Deshmukh"
__license__ = "MIT"

from ._parser import PDFParseError
from .extractor import PDFExtractor, extract_pdf, extract_batch
from .schema import ExtractionResult, PageResult

__all__ = [
    "PDFExtractor",
    "ExtractionResult",
    "PageResult",
    "PDFParseError",
    "extract_pdf",
    "extract_batch",
]
