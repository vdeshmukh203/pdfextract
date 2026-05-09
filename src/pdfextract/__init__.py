"""
pdfextract: Structured scientific PDF content extraction tool.

Parses PDF documents and extracts text with page-level structure, document
metadata, and optional table/section detection. Output is available as plain
text, Markdown, or structured JSON for downstream text mining pipelines.
"""

__version__ = "0.1.0"
__author__ = "Vaibhav Deshmukh"
__license__ = "MIT"

from .extractor import PDFExtractor, PDFParseError
from .schema import ExtractionResult, PageResult

__all__ = [
    "PDFExtractor",
    "PDFParseError",
    "ExtractionResult",
    "PageResult",
    "extract_pdf",
]


def extract_pdf(
    path: str,
    output_format: str = "text",
    output_path: str | None = None,
    max_pages: int = 0,
) -> str:
    """
    Extract text from a PDF and optionally write to a file.

    Parameters
    ----------
    path : str
        Input PDF path.
    output_format : str
        ``"text"``, ``"markdown"``, or ``"json"``.
    output_path : str, optional
        If given, write output to this path.
    max_pages : int
        Maximum pages to extract (0 = all).

    Returns
    -------
    str
        Extracted content in the requested format.
    """
    from pathlib import Path

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
