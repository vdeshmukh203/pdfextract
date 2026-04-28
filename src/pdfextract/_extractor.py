"""High-level PDF extraction API."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from ._parser import (
    PDFParseError,
    extract_metadata,
    find_xref_offset,
    iter_page_streams,
    parse_xref_table,
    read_pdf_bytes,
)
from ._schema import ExtractionResult, PageResult
from ._text import extract_text_from_stream


class PDFExtractor:
    """Extract text and metadata from a PDF file without external binaries.

    Parameters
    ----------
    path:
        Path to the PDF file.
    max_pages:
        Stop after this many pages (0 = unlimited).
    """

    def __init__(self, path: str, max_pages: int = 0) -> None:
        self.path = Path(path)
        self.max_pages = max_pages
        self._data: bytes = b""

    def extract(self) -> ExtractionResult:
        """Run extraction and return an :class:`ExtractionResult`."""
        result = ExtractionResult(source=self.path.name, page_count=0)

        try:
            self._data = read_pdf_bytes(self.path)
        except (PDFParseError, OSError) as exc:
            result.errors.append(f"load error: {exc}")
            return result

        try:
            xref_offset = find_xref_offset(self._data)
            xref = parse_xref_table(self._data, xref_offset)
        except PDFParseError as exc:
            result.errors.append(f"xref error: {exc}")
            return result

        result.metadata = extract_metadata(self._data, xref)

        pages: List[PageResult] = []
        for page_num, stream in iter_page_streams(self._data, xref, self.max_pages):
            if not stream:
                pages.append(PageResult(page_number=page_num, text=""))
                continue
            try:
                text = extract_text_from_stream(stream)
            except Exception as exc:
                result.errors.append(f"page {page_num} text error: {exc}")
                text = ""
            pages.append(PageResult(page_number=page_num, text=text))

        result.pages = pages
        result.page_count = len(pages)
        return result


def extract_pdf(
    path: str,
    output_format: str = "text",
    output_path: Optional[str] = None,
    max_pages: int = 0,
) -> str:
    """Extract text from a PDF and optionally write it to a file.

    Parameters
    ----------
    path:
        Input PDF path.
    output_format:
        ``"text"``, ``"markdown"``, or ``"json"``.
    output_path:
        If provided, write the output to this file path.
    max_pages:
        Maximum number of pages to extract (0 = all).

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
