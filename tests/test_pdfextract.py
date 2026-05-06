"""Tests for pdfextract."""
from __future__ import annotations

import json
import struct
import tempfile
import zlib
from pathlib import Path

import pytest

import pdfextract
from pdfextract import (
    ExtractionResult,
    PDFExtractor,
    PDFParseError,
    PageResult,
    extract_pdf,
)
from pdfextract.schema import ExtractionResult, PageResult


# ---------------------------------------------------------------------------
# Minimal valid PDF factory
# ---------------------------------------------------------------------------

def _make_pdf(text: str = "Hello World") -> bytes:
    """Build a minimal single-page PDF with the given text string."""
    encoded = text.encode("latin-1", errors="replace")
    content = b"BT /F1 12 Tf 72 720 Td (" + encoded + b") Tj ET"
    content_len = len(content)

    lines: list[bytes] = []
    offsets: dict[int, int] = {}

    def add(line: bytes) -> None:
        lines.append(line)

    def obj(n: int, data: bytes) -> None:
        offsets[n] = sum(len(l) for l in lines)
        add(f"{n} 0 obj\n".encode())
        add(data + b"\n")
        add(b"endobj\n")

    add(b"%PDF-1.4\n")
    obj(1, b"<</Type /Catalog /Pages 2 0 R>>")
    obj(2, b"<</Type /Pages /Kids [3 0 R] /Count 1>>")
    obj(
        3,
        b"<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>>",
    )
    obj(4, f"<</Length {content_len}>>\nstream\n".encode() + content + b"\nendstream")
    obj(5, b"<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>")

    xref_offset = sum(len(l) for l in lines)
    add(b"xref\n")
    add(f"0 {len(offsets) + 1}\n".encode())
    add(b"0000000000 65535 f \n")
    for i in range(1, len(offsets) + 1):
        add(f"{offsets[i]:010d} 00000 n \n".encode())
    add(b"trailer\n")
    add(f"<</Size {len(offsets) + 1} /Root 1 0 R>>\n".encode())
    add(b"startxref\n")
    add(f"{xref_offset}\n".encode())
    add(b"%%EOF\n")

    return b"".join(lines)


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Write a minimal PDF to a temporary file and return its path."""
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(_make_pdf("Hello World"))
    return pdf_path


@pytest.fixture
def multipage_pdf(tmp_path: Path) -> Path:
    """Two-page PDF (reuse same content stream on each page)."""
    content = b"BT /F1 12 Tf 72 720 Td (Page content) Tj ET"
    clen = len(content)

    lines: list[bytes] = []
    offsets: dict[int, int] = {}

    def add(b: bytes) -> None:
        lines.append(b)

    def obj(n: int, data: bytes) -> None:
        offsets[n] = sum(len(l) for l in lines)
        add(f"{n} 0 obj\n".encode())
        add(data + b"\n")
        add(b"endobj\n")

    add(b"%PDF-1.4\n")
    obj(1, b"<</Type /Catalog /Pages 2 0 R>>")
    obj(2, b"<</Type /Pages /Kids [3 0 R 6 0 R] /Count 2>>")
    # page 1
    obj(3, b"<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>>")
    obj(4, f"<</Length {clen}>>\nstream\n".encode() + content + b"\nendstream")
    obj(5, b"<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>")
    # page 2
    obj(6, b"<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>>")

    xref_offset = sum(len(l) for l in lines)
    add(b"xref\n")
    add(f"0 {len(offsets) + 1}\n".encode())
    add(b"0000000000 65535 f \n")
    for i in range(1, len(offsets) + 1):
        add(f"{offsets[i]:010d} 00000 n \n".encode())
    add(b"trailer\n")
    add(f"<</Size {len(offsets) + 1} /Root 1 0 R>>\n".encode())
    add(b"startxref\n")
    add(f"{xref_offset}\n".encode())
    add(b"%%EOF\n")

    pdf_path = tmp_path / "multi.pdf"
    pdf_path.write_bytes(b"".join(lines))
    return pdf_path


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

class TestPublicAPI:
    def test_extract_pdf_in_namespace(self):
        assert callable(pdfextract.extract_pdf)

    def test_classes_exported(self):
        assert pdfextract.PDFExtractor is PDFExtractor
        assert pdfextract.ExtractionResult is ExtractionResult
        assert pdfextract.PageResult is PageResult
        assert pdfextract.PDFParseError is PDFParseError

    def test_version_string(self):
        assert isinstance(pdfextract.__version__, str)
        parts = pdfextract.__version__.split(".")
        assert len(parts) >= 2


# ---------------------------------------------------------------------------
# PageResult
# ---------------------------------------------------------------------------

class TestPageResult:
    def test_word_count(self):
        pr = PageResult(page_number=1, text="hello world foo")
        assert pr.word_count == 3

    def test_char_count(self):
        pr = PageResult(page_number=1, text="abc")
        assert pr.char_count == 3

    def test_empty_text(self):
        pr = PageResult(page_number=1, text="")
        assert pr.word_count == 0
        assert pr.char_count == 0


# ---------------------------------------------------------------------------
# ExtractionResult
# ---------------------------------------------------------------------------

class TestExtractionResult:
    def _make_result(self) -> ExtractionResult:
        pages = [
            PageResult(page_number=1, text="Hello world"),
            PageResult(page_number=2, text="Second page"),
        ]
        return ExtractionResult(
            source="test.pdf",
            page_count=2,
            pages=pages,
            metadata={"title": "Test"},
        )

    def test_full_text_joins_pages(self):
        result = self._make_result()
        assert "Hello world" in result.full_text
        assert "Second page" in result.full_text

    def test_word_count_aggregates(self):
        result = self._make_result()
        assert result.word_count == 4  # "Hello world" + "Second page"

    def test_to_dict_structure(self):
        result = self._make_result()
        d = result.to_dict()
        assert d["source"] == "test.pdf"
        assert d["page_count"] == 2
        assert d["word_count"] == 4
        assert len(d["pages"]) == 2
        assert d["pages"][0]["page"] == 1

    def test_to_json_valid(self):
        result = self._make_result()
        parsed = json.loads(result.to_json())
        assert parsed["source"] == "test.pdf"

    def test_to_markdown_contains_headers(self):
        result = self._make_result()
        md = result.to_markdown()
        assert "# Extracted Text" in md
        assert "## Page 1" in md
        assert "## Page 2" in md
        assert "## Metadata" in md

    def test_to_markdown_no_metadata_section_when_empty(self):
        result = ExtractionResult(source="x.pdf", page_count=0)
        assert "## Metadata" not in result.to_markdown()

    def test_errors_in_markdown(self):
        result = ExtractionResult(
            source="x.pdf",
            page_count=0,
            errors=["page 1: something went wrong"],
        )
        assert "Warnings" in result.to_markdown()


# ---------------------------------------------------------------------------
# PDFExtractor
# ---------------------------------------------------------------------------

class TestPDFExtractor:
    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            PDFExtractor("/nonexistent/path/file.pdf").extract()

    def test_non_pdf_raises(self, tmp_path: Path):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"not a pdf at all")
        with pytest.raises(PDFParseError):
            PDFExtractor(str(bad)).extract()

    def test_extracts_from_valid_pdf(self, sample_pdf: Path):
        result = PDFExtractor(str(sample_pdf)).extract()
        assert isinstance(result, ExtractionResult)
        assert result.page_count >= 1

    def test_source_name(self, sample_pdf: Path):
        result = PDFExtractor(str(sample_pdf)).extract()
        assert result.source == sample_pdf.name

    def test_max_pages_limits_output(self, multipage_pdf: Path):
        result = PDFExtractor(str(multipage_pdf), max_pages=1).extract()
        assert result.page_count == 1

    def test_accepts_path_object(self, sample_pdf: Path):
        result = PDFExtractor(sample_pdf).extract()
        assert result.page_count >= 1


# ---------------------------------------------------------------------------
# extract_pdf convenience function
# ---------------------------------------------------------------------------

class TestExtractPDF:
    def test_returns_string(self, sample_pdf: Path):
        out = extract_pdf(str(sample_pdf))
        assert isinstance(out, str)

    def test_json_format_is_valid(self, sample_pdf: Path):
        out = extract_pdf(str(sample_pdf), output_format="json")
        parsed = json.loads(out)
        assert "pages" in parsed

    def test_markdown_format_contains_header(self, sample_pdf: Path):
        out = extract_pdf(str(sample_pdf), output_format="markdown")
        assert out.startswith("# Extracted Text")

    def test_writes_to_output_path(self, sample_pdf: Path, tmp_path: Path):
        out_file = tmp_path / "out.txt"
        extract_pdf(str(sample_pdf), output_path=str(out_file))
        assert out_file.exists()
        assert out_file.stat().st_size > 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCLI:
    def test_cli_help(self):
        from pdfextract._cli import _build_parser
        parser = _build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--help"])
        assert exc_info.value.code == 0

    def test_cli_missing_file_returns_error(self):
        from pdfextract._cli import main
        code = main(["/nonexistent/file.pdf"])
        assert code != 0

    def test_cli_text_output(self, sample_pdf: Path):
        from pdfextract._cli import main
        code = main([str(sample_pdf)])
        assert code == 0

    def test_cli_json_output(self, sample_pdf: Path, tmp_path: Path):
        out_file = tmp_path / "out.json"
        from pdfextract._cli import main
        code = main([str(sample_pdf), "-f", "json", "-o", str(out_file)])
        assert code == 0
        assert out_file.exists()
        parsed = json.loads(out_file.read_text())
        assert "pages" in parsed

    def test_cli_max_pages(self, multipage_pdf: Path):
        from pdfextract._cli import main
        code = main([str(multipage_pdf), "-p", "1"])
        assert code == 0
