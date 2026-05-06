"""Core PDF extraction engine backed by pdfminer.six."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Union

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTPage, LTTextBox
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfexceptions import PDFException
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import resolve1

from .schema import ExtractionResult, PageResult

logger = logging.getLogger(__name__)


class PDFParseError(Exception):
    """Raised when a PDF file cannot be parsed."""


def _extract_metadata(path: Path) -> Dict[str, str]:
    """Return the PDF Info dictionary as a flat str→str mapping."""
    metadata: Dict[str, str] = {}
    _field_map = {
        "Title": "title",
        "Author": "author",
        "Subject": "subject",
        "Keywords": "keywords",
        "Creator": "creator",
        "Producer": "producer",
        "CreationDate": "creation_date",
        "ModDate": "modification_date",
    }
    try:
        with open(path, "rb") as fh:
            parser = PDFParser(fh)
            doc = PDFDocument(parser)
            info_list = doc.info if doc.info else []
            for info in info_list:
                for pdf_key, out_key in _field_map.items():
                    raw = info.get(pdf_key)
                    if raw is None:
                        continue
                    try:
                        value = resolve1(raw)
                        if isinstance(value, bytes):
                            # UTF-16-BE BOM indicates Unicode encoding
                            if value.startswith(b"\xfe\xff"):
                                decoded = value[2:].decode("utf-16-be", errors="replace")
                            else:
                                decoded = value.decode("latin-1", errors="replace")
                            decoded = decoded.strip("\x00").strip()
                        else:
                            decoded = str(value).strip()
                        if decoded:
                            metadata[out_key] = decoded
                    except Exception:
                        pass
    except (PDFException, OSError):
        pass
    return metadata


def _page_text(page_layout: LTPage) -> str:
    """Extract text from one page in approximate reading order."""
    boxes: List[tuple] = []
    for element in page_layout:
        if isinstance(element, LTTextBox):
            text = element.get_text().strip()
            if text:
                # (−y0, x0) sorts top-to-bottom then left-to-right
                boxes.append((-element.y0, element.x0, text))
    boxes.sort()
    return "\n".join(t for _, _, t in boxes)


class PDFExtractor:
    """
    Extract text and metadata from a PDF file.

    Uses pdfminer.six for layout-aware text extraction that preserves
    reading order across single- and multi-column document layouts.

    Parameters
    ----------
    path : str or Path
        Path to the PDF file.
    max_pages : int, optional
        Maximum number of pages to process (0 = all pages).
    laparams : LAParams, optional
        pdfminer layout analysis parameters. ``None`` uses sensible defaults.
    """

    def __init__(
        self,
        path: Union[str, Path],
        max_pages: int = 0,
        laparams: Optional[LAParams] = None,
    ) -> None:
        self.path = Path(path)
        self.max_pages = max_pages
        self.laparams = laparams or LAParams()

    def extract(self) -> ExtractionResult:
        """
        Run extraction and return an :class:`ExtractionResult`.

        Returns
        -------
        ExtractionResult
            Populated result object; ``errors`` lists non-fatal issues.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        PDFParseError
            If the file is not a valid PDF.
        """
        if not self.path.exists():
            raise FileNotFoundError(f"PDF not found: {self.path}")

        result = ExtractionResult(source=self.path.name, page_count=0)

        # Metadata (best-effort; silently skipped on encrypted files)
        result.metadata = _extract_metadata(self.path)

        pages: List[PageResult] = []
        errors: List[str] = []

        try:
            page_layouts = extract_pages(
                str(self.path),
                laparams=self.laparams,
                maxpages=self.max_pages or 0,
            )
            for page_num, page_layout in enumerate(page_layouts, start=1):
                try:
                    text = _page_text(page_layout)
                except Exception as exc:
                    errors.append(f"page {page_num}: {exc}")
                    text = ""
                pages.append(PageResult(page_number=page_num, text=text))

        except PDFException as exc:
            raise PDFParseError(str(exc)) from exc
        except Exception as exc:
            errors.append(f"extraction error: {exc}")
            logger.exception("Unexpected error during extraction")

        result.pages = pages
        result.page_count = len(pages)
        result.errors = errors
        return result
