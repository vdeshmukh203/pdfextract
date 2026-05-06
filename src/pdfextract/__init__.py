"""
pdfextract: Structured text and metadata extraction from PDF documents.

Provides a Python API, command-line interface, and graphical interface for
extracting text from PDF files. Uses pdfminer.six for layout-aware extraction
that preserves reading order across single- and multi-column layouts.

Basic usage::

    from pdfextract import extract_pdf

    text = extract_pdf("paper.pdf")
    json_output = extract_pdf("paper.pdf", output_format="json")
"""
from __future__ import annotations

__version__ = "0.2.0"
__author__ = "Vaibhav Deshmukh"
__license__ = "MIT"

from .extractor import PDFExtractor, PDFParseError
from .schema import ExtractionResult, PageResult


def extract_pdf(
    path: str,
    output_format: str = "text",
    output_path: "str | None" = None,
    max_pages: int = 0,
) -> str:
    """
    Extract text from a PDF and optionally write to a file.

    Parameters
    ----------
    path : str
        Path to the input PDF file.
    output_format : str
        ``"text"`` (default), ``"markdown"``, or ``"json"``.
    output_path : str, optional
        If given, write output to this path (UTF-8).
    max_pages : int
        Maximum pages to extract; ``0`` means all pages.

    Returns
    -------
    str
        Extracted content in the requested format.
    """
    from pathlib import Path as _Path

    result = PDFExtractor(path, max_pages=max_pages).extract()

    if output_format == "json":
        out = result.to_json()
    elif output_format == "markdown":
        out = result.to_markdown()
    else:
        out = result.full_text

    if output_path:
        _Path(output_path).write_text(out, encoding="utf-8")

    return out


def _cli() -> None:
    from ._cli import _cli as _real_cli
    _real_cli()


__all__ = [
    "__version__",
    "PDFExtractor",
    "PDFParseError",
    "ExtractionResult",
    "PageResult",
    "extract_pdf",
]
