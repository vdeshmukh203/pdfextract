"""
pdfextract: Structured text and metadata extraction from PDF files.

Pure-Python PDF parser (no external binaries) that reads cross-reference
tables and streams, traverses the document page tree, decodes content
streams, and outputs plain text, Markdown, or JSON.

Quick start::

    from pdfextract import extract_pdf

    text = extract_pdf("paper.pdf")
    md   = extract_pdf("paper.pdf", output_format="markdown")
    data = extract_pdf("paper.pdf", output_format="json")

For lower-level control::

    from pdfextract import PDFExtractor

    result = PDFExtractor("paper.pdf", max_pages=10).extract()
    print(result.metadata)
    for page in result.pages:
        print(f"Page {page.page_number}: {page.word_count} words")
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .extractor import PDFExtractor, PDFParseError
from .schema import ExtractionResult, PageResult

__version__ = "0.2.0"
__author__ = "Vaibhav Deshmukh"
__license__ = "MIT"

__all__ = [
    "PDFExtractor",
    "PDFParseError",
    "ExtractionResult",
    "PageResult",
    "extract_pdf",
    "__version__",
]


def extract_pdf(
    path: str,
    output_format: str = "text",
    output_path: Optional[str] = None,
    max_pages: int = 0,
) -> str:
    """Extract text from a PDF file.

    Parameters
    ----------
    path:
        Input PDF file path.
    output_format:
        One of ``"text"`` (default), ``"markdown"``, or ``"json"``.
    output_path:
        If given, write the result to this file path (UTF-8 encoding).
    max_pages:
        Maximum number of pages to process.  ``0`` processes all pages.

    Returns
    -------
    str
        Extracted content formatted according to *output_format*.

    Raises
    ------
    PDFParseError
        If *path* is not a valid PDF file.
    OSError
        If *path* cannot be read or *output_path* cannot be written.

    Examples
    --------
    >>> text = extract_pdf("paper.pdf")
    >>> md   = extract_pdf("paper.pdf", output_format="markdown")
    >>> _    = extract_pdf("paper.pdf", output_format="json", output_path="out.json")
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


# Keep the private _cli name for backwards compatibility with the old
# pyproject.toml entry point (pdfextract = "pdfextract:_cli").
def _cli() -> None:  # pragma: no cover
    from .cli import main
    import sys
    sys.exit(main())
