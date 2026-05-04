"""
pdfextract — pure-Python structured text and metadata extractor for PDF files.

This ``__init__.py`` re-exports the public API from the top-level
``pdfextract`` module so that the package can be used both as a
single-module install (``py-modules = ["pdfextract"]`` in pyproject.toml)
and in a source-layout development environment where ``src/`` is on
``sys.path``.
"""
from pdfextract import (  # noqa: F401
    __version__,
    __author__,
    __license__,
    PDFParseError,
    PDFExtractor,
    ExtractionResult,
    PageResult,
    extract_pdf,
    batch_extract,
)

__all__ = [
    "__version__",
    "__author__",
    "__license__",
    "PDFParseError",
    "PDFExtractor",
    "ExtractionResult",
    "PageResult",
    "extract_pdf",
    "batch_extract",
]
