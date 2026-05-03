"""
Data classes and exceptions for pdfextract.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List


class PDFParseError(Exception):
    """Raised when a PDF cannot be parsed."""


@dataclass
class PageResult:
    """Extraction result for a single page."""

    page_number: int  # 1-based
    text: str
    word_count: int = field(init=False)
    char_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.word_count = len(self.text.split())
        self.char_count = len(self.text)


@dataclass
class ExtractionResult:
    """Aggregated extraction result for an entire PDF."""

    source: str
    page_count: int
    pages: List[PageResult] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text.strip())

    @property
    def word_count(self) -> int:
        return sum(p.word_count for p in self.pages)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "page_count": self.page_count,
            "word_count": self.word_count,
            "metadata": self.metadata,
            "errors": self.errors,
            "pages": [
                {
                    "page": p.page_number,
                    "text": p.text,
                    "words": p.word_count,
                    "chars": p.char_count,
                }
                for p in self.pages
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_markdown(self) -> str:
        lines: List[str] = [
            f"# Extracted Text: {self.source}",
            "",
            f"**Pages**: {self.page_count} | **Words**: {self.word_count}",
            "",
        ]
        if self.metadata:
            lines += ["## Metadata", ""]
            for k, v in self.metadata.items():
                lines.append(f"- **{k}**: {v}")
            lines.append("")
        for page in self.pages:
            lines += [f"## Page {page.page_number}", "", page.text, ""]
        if self.errors:
            lines += ["## Warnings", ""]
            for err in self.errors:
                lines.append(f"- {err}")
        return "\n".join(lines)
