"""PDFExtractor: high-level extraction using the low-level parser."""
from __future__ import annotations
import json
from pathlib import Path
from typing import List, Optional

from ._parser import (
    PDFParseError,
    find_xref_offset,
    parse_xref_and_trailer,
    get_page_bodies,
    get_content_stream,
    get_metadata,
    extract_text_from_stream,
)
from .schema import ExtractionResult, PageResult


class PDFExtractor:
    """
    Extract text and metadata from a PDF file.

    Parameters
    ----------
    path : str or Path
        Path to the PDF file.
    max_pages : int
        Stop after this many pages (0 = all pages).
    """

    def __init__(self, path: str, max_pages: int = 0) -> None:
        self.path = Path(path)
        self.max_pages = max_pages
        self._data: bytes = b""

    def _load(self) -> None:
        self._data = self.path.read_bytes()
        if self._data[:4] != b"%PDF":
            raise PDFParseError(f"Not a PDF file: {self.path}")

    def extract(self) -> ExtractionResult:
        """Run extraction and return an ExtractionResult."""
        self._load()
        result = ExtractionResult(source=self.path.name, page_count=0)

        try:
            offset = find_xref_offset(self._data)
            xref, trailer = parse_xref_and_trailer(self._data, offset)
        except PDFParseError as exc:
            result.errors.append(f"xref error: {exc}")
            return result

        result.metadata = get_metadata(self._data, xref, trailer)

        page_bodies = get_page_bodies(self._data, xref, trailer)
        if self.max_pages:
            page_bodies = page_bodies[: self.max_pages]

        pages: List[PageResult] = []
        errors: List[str] = []
        for i, page_body in enumerate(page_bodies, 1):
            try:
                stream = get_content_stream(self._data, xref, page_body)
                text = extract_text_from_stream(stream) if stream else ""
            except Exception as exc:
                errors.append(f"page {i} error: {exc}")
                text = ""
            pages.append(PageResult(page_number=i, text=text))

        result.pages = pages
        result.page_count = len(pages)
        result.errors = errors
        return result


def extract_pdf(
    path: str,
    output_format: str = "text",
    output_path: Optional[str] = None,
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
        Write output to this path instead of returning.
    max_pages : int
        Maximum pages to extract (0 = all).

    Returns
    -------
    str
        Extracted content in the requested format.
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


def extract_batch(
    paths: List[str],
    output_format: str = "text",
    output_dir: Optional[str] = None,
    max_pages: int = 0,
) -> List[ExtractionResult]:
    """
    Extract text from multiple PDFs.

    Parameters
    ----------
    paths : list of str
        Input PDF paths.
    output_format : str
        ``"text"``, ``"markdown"``, or ``"json"``.
    output_dir : str, optional
        Directory to write output files; filenames mirror input stems.
    max_pages : int
        Maximum pages per PDF (0 = all).

    Returns
    -------
    list of ExtractionResult
    """
    out_dir = Path(output_dir) if output_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for path in paths:
        result = PDFExtractor(path, max_pages=max_pages).extract()
        results.append(result)
        if out_dir:
            stem = Path(path).stem
            ext = {"text": ".txt", "markdown": ".md", "json": ".json"}.get(
                output_format, ".txt"
            )
            if output_format == "json":
                content = result.to_json()
            elif output_format == "markdown":
                content = result.to_markdown()
            else:
                content = result.full_text
            (out_dir / (stem + ext)).write_text(content, encoding="utf-8")
    return results
