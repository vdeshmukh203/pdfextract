"""Data classes representing PDF extraction results."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class PageResult:
    """Extracted content from a single PDF page.

    Parameters
    ----------
    page_number : int
        1-based page index.
    text : str
        Extracted plain text for this page.
    """

    page_number: int
    text: str
    word_count: int = field(init=False)
    char_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.word_count = len(self.text.split())
        self.char_count = len(self.text)


@dataclass
class ExtractionResult:
    """Full extraction result for a PDF document.

    Parameters
    ----------
    source : str
        Filename or path of the source PDF.
    page_count : int
        Number of pages processed.
    pages : list of PageResult
        Per-page extraction results.
    metadata : dict
        Document metadata from the PDF Info dictionary
        (e.g. Title, Author, Subject, Keywords).
    errors : list of str
        Non-fatal errors encountered during extraction.
    """

    source: str
    page_count: int
    pages: List[PageResult] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """Concatenated text of all pages, separated by double newlines."""
        return "\n\n".join(p.text for p in self.pages if p.text.strip())

    @property
    def word_count(self) -> int:
        """Total word count across all pages."""
        return sum(p.word_count for p in self.pages)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary."""
        return {
            "source": self.source,
            "page_count": self.page_count,
            "word_count": self.word_count,
            "metadata": self.metadata,
            "errors": self.errors,
            "pages": [
                {"page": p.page_number, "text": p.text, "words": p.word_count}
                for p in self.pages
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_markdown(self) -> str:
        """Render as a Markdown document."""
        lines: List[str] = [
            f"# Extracted Text: {self.source}",
            "",
            f"**Pages**: {self.page_count} | **Words**: {self.word_count}",
            "",
        ]
        if self.metadata:
            lines += ["## Metadata", ""]
            for key, val in self.metadata.items():
                lines.append(f"- **{key}**: {val}")
            lines.append("")
        for page in self.pages:
            lines += [f"## Page {page.page_number}", "", page.text, ""]
        return "\n".join(lines)
