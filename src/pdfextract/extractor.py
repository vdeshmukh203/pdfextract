"""High-level PDF text and metadata extractor."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Union

from .parser import (
    PDFParseError,
    build_xref,
    dict_get,
    dict_get_refs,
    extract_stream_data,
    extract_text_from_stream,
    parse_obj,
    resolve_indirect,
)
from .schema import ExtractionResult, PageResult


class PDFExtractor:
    """Extract text and metadata from a PDF file without external binaries.

    Parameters
    ----------
    path : str or Path
        Path to the PDF file.
    max_pages : int, optional
        Maximum number of pages to process. ``0`` (default) extracts all pages.

    Examples
    --------
    >>> from pdfextract import PDFExtractor
    >>> result = PDFExtractor("paper.pdf").extract()
    >>> print(result.word_count)
    >>> print(result.metadata.get("Title", ""))
    """

    def __init__(self, path: Union[str, Path], max_pages: int = 0) -> None:
        self.path = Path(path)
        self.max_pages = max_pages
        self._data: bytes = b""
        self._xref: Dict[int, int] = {}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        self._data = self.path.read_bytes()
        if self._data[:4] != b"%PDF":
            raise PDFParseError(f"Not a PDF file: {self.path}")

    def _get_obj(self, obj_id: int) -> Optional[bytes]:
        if obj_id not in self._xref:
            return None
        try:
            return parse_obj(self._data, self._xref[obj_id])
        except PDFParseError:
            return None

    def _resolve(self, ref: str) -> Optional[bytes]:
        return resolve_indirect(self._data, self._xref, ref)

    # ------------------------------------------------------------------
    # Trailer / document catalog
    # ------------------------------------------------------------------

    def _find_root_ref(self) -> Optional[str]:
        """Locate the /Root reference from the file trailer or xref stream."""
        tail = self._data[-4096:].decode("latin-1", errors="replace")
        m = re.search(r"/Root\s+(\d+\s+\d+\s+R)", tail)
        if m:
            return m.group(1)
        # Fallback: search for an xref stream object that carries /Root
        for obj_id in self._xref:
            ob = self._get_obj(obj_id)
            if ob is None:
                continue
            txt = ob.decode("latin-1", errors="replace")
            if "/Type" in txt and "/XRef" in txt:
                m = re.search(r"/Root\s+(\d+\s+\d+\s+R)", txt)
                if m:
                    return m.group(1)
        return None

    def _extract_metadata(self) -> Dict[str, str]:
        """Read the PDF Info dictionary for document-level metadata."""
        tail = self._data[-4096:].decode("latin-1", errors="replace")
        info_m = re.search(r"/Info\s+(\d+\s+\d+\s+R)", tail)
        if not info_m:
            return {}
        info_bytes = self._resolve(info_m.group(1))
        if info_bytes is None:
            return {}

        metadata: Dict[str, str] = {}
        for key in ("Title", "Author", "Subject", "Keywords", "Creator", "Producer"):
            raw = dict_get(info_bytes, key)
            if raw:
                if raw.startswith("(") and raw.endswith(")"):
                    raw = raw[1:-1]
                metadata[key] = raw.strip()
        return metadata

    # ------------------------------------------------------------------
    # Page tree traversal
    # ------------------------------------------------------------------

    def _iter_pages(self, root_ref: str) -> Iterator[bytes]:
        """Recursively yield page object bodies in document order."""
        catalog = self._resolve(root_ref)
        if catalog is None:
            return
        pages_ref = dict_get(catalog, "Pages")
        if pages_ref and re.search(r"\d+\s+\d+\s+R", pages_ref):
            yield from self._walk_page_tree(pages_ref)

    def _walk_page_tree(self, node_ref: str) -> Iterator[bytes]:
        node = self._resolve(node_ref)
        if node is None:
            return
        node_type = dict_get(node, "Type")
        if node_type == "/Page":
            yield node
        else:
            for kid_ref in dict_get_refs(node, "Kids"):
                yield from self._walk_page_tree(kid_ref)

    def _fallback_page_scan(self) -> Iterator[bytes]:
        """Yield page objects found by heuristically scanning all xref entries."""
        for obj_id in sorted(self._xref):
            ob = self._get_obj(obj_id)
            if ob is None:
                continue
            txt = ob.decode("latin-1", errors="replace")
            if "/Type" in txt and "/Page" in txt and "/Pages" not in txt:
                yield ob

    # ------------------------------------------------------------------
    # Content stream text extraction
    # ------------------------------------------------------------------

    def _page_text(self, page_obj: bytes) -> str:
        """Extract text from a page's content stream(s)."""
        contents = dict_get(page_obj, "Contents")
        if contents is None:
            return ""

        if contents.startswith("["):
            refs = re.findall(r"\d+\s+\d+\s+R", contents)
        elif re.search(r"\d+\s+\d+\s+R", contents):
            refs = [contents]
        else:
            return ""

        streams: List[bytes] = []
        for ref in refs:
            obj = self._resolve(ref)
            if obj is not None:
                sd = extract_stream_data(obj)
                if sd:
                    streams.append(sd)

        combined = b"\n".join(streams)
        return extract_text_from_stream(combined) if combined else ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self) -> ExtractionResult:
        """Run extraction and return an :class:`~pdfextract.schema.ExtractionResult`.

        Raises
        ------
        PDFParseError
            If the file is not a valid PDF.

        Returns
        -------
        ExtractionResult
            Contains per-page text, document metadata, and any non-fatal errors.
        """
        self._load()
        result = ExtractionResult(source=self.path.name, page_count=0)
        errors: List[str] = []

        try:
            self._xref = build_xref(self._data)
        except Exception as exc:
            result.errors.append(f"xref error: {exc}")
            return result

        result.metadata = self._extract_metadata()

        root_ref = self._find_root_ref()
        page_src = (
            self._iter_pages(root_ref) if root_ref else self._fallback_page_scan()
        )

        pages: List[PageResult] = []
        for page_num, page_obj in enumerate(page_src, start=1):
            try:
                text = self._page_text(page_obj)
            except Exception as exc:
                errors.append(f"page {page_num}: {exc}")
                text = ""
            pages.append(PageResult(page_number=page_num, text=text))
            if self.max_pages and page_num >= self.max_pages:
                break

        result.pages = pages
        result.page_count = len(pages)
        result.errors = errors
        return result
