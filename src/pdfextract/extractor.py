"""
High-level PDF extraction logic.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional

from .parser import (
    extract_text_from_stream,
    get_page_content_stream,
    get_page_obj_ids,
    load_xref,
    parse_metadata,
    parse_obj,
    extract_stream_bytes,
)
from .schema import ExtractionResult, PDFParseError, PageResult


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

    def __init__(self, path: str | Path, max_pages: int = 0) -> None:
        self.path = Path(path)
        self.max_pages = max_pages
        self._data: bytes = b""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"File not found: {self.path}")
        self._data = self.path.read_bytes()
        if self._data[:4] != b"%PDF":
            raise PDFParseError(f"Not a PDF file: {self.path}")

    def _fallback_page_scan(self, xref: dict) -> List[int]:
        """
        If page tree traversal yields nothing, fall back to scanning all
        objects for /Type /Page entries and return their IDs sorted.
        """
        page_ids: List[int] = []
        for obj_id in sorted(xref):
            try:
                _, body = parse_obj(self._data, xref[obj_id])
            except PDFParseError:
                continue
            if b"/Type" in body and b"/Page" in body:
                # Exclude /Pages (node) — only terminal /Page leaves
                type_m = re.search(rb"/Type\s*/(\w+)", body)
                if type_m and type_m.group(1) == b"Page":
                    page_ids.append(obj_id)
        return page_ids

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def extract(self) -> ExtractionResult:
        """
        Run extraction and return an :class:`ExtractionResult`.

        Errors encountered on individual pages are recorded in
        ``result.errors`` rather than raising exceptions.
        """
        self._load()
        result = ExtractionResult(source=self.path.name, page_count=0)
        errors: List[str] = []

        try:
            xref, trailer = load_xref(self._data)
        except PDFParseError as exc:
            result.errors.append(f"xref error: {exc}")
            return result

        # Metadata
        try:
            result.metadata = parse_metadata(self._data, xref, trailer)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"metadata warning: {exc}")

        # Page IDs in reading order
        page_obj_ids = get_page_obj_ids(self._data, xref, trailer)
        if not page_obj_ids:
            page_obj_ids = self._fallback_page_scan(xref)

        if self.max_pages > 0:
            page_obj_ids = page_obj_ids[: self.max_pages]

        pages: List[PageResult] = []
        for page_num, obj_id in enumerate(page_obj_ids, start=1):
            try:
                stream = get_page_content_stream(self._data, xref, obj_id)
                text = extract_text_from_stream(stream) if stream is not None else ""
            except Exception as exc:  # noqa: BLE001
                errors.append(f"page {page_num} error: {exc}")
                text = ""
            pages.append(PageResult(page_number=page_num, text=text))

        result.pages = pages
        result.page_count = len(pages)
        result.errors = errors
        return result


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def extract_pdf(
    path: str,
    output_format: str = "text",
    output_path: Optional[str] = None,
    max_pages: int = 0,
) -> str:
    """
    Extract text from a PDF and optionally write the result to a file.

    Parameters
    ----------
    path : str
        Input PDF path.
    output_format : str
        ``"text"``, ``"markdown"``, or ``"json"``.
    output_path : str, optional
        If provided, write output to this file path.
    max_pages : int
        Maximum pages to extract; 0 means all pages.

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
