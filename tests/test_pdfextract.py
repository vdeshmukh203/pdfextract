"""
Tests for pdfextract.

Covers unit-level functions (string decoding, stream parsing) and
integration-level extraction using a programmatically constructed
minimal valid PDF so the test suite requires no external files.
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import pdfextract
from pdfextract import (
    ExtractionResult,
    PDFExtractor,
    PDFParseError,
    PageResult,
    _decode_pdf_string,
    _extract_text_from_stream,
    _find_xref_offset,
    _parse_xref_table,
    extract_pdf,
    batch_extract,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_minimal_pdf(text: str = "Hello PDF") -> bytes:
    """
    Build a minimal single-page PDF containing *text* in a BT/ET block.

    All byte offsets in the xref table are computed precisely so the
    resulting bytes constitute a structurally valid PDF 1.4 document.
    """
    content_stream = f"BT /F1 12 Tf 100 700 Td ({text}) Tj ET\n".encode()
    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    obj3 = (
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\n"
        b"endobj\n"
    )
    obj4 = (
        b"4 0 obj\n<< /Length " + str(len(content_stream)).encode() + b" >>\n"
        b"stream\n" + content_stream + b"endstream\nendobj\n"
    )
    obj5 = (
        b"5 0 obj\n"
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n"
        b"endobj\n"
    )

    header = b"%PDF-1.4\n"
    body = header
    offsets: dict = {}
    for i, obj in enumerate([obj1, obj2, obj3, obj4, obj5], start=1):
        offsets[i] = len(body)
        body += obj

    xref_offset = len(body)
    xref = b"xref\n0 6\n0000000000 65535 f \n"
    for i in range(1, 6):
        xref += f"{offsets[i]:010d} 00000 n \n".encode()
    body += xref
    body += (
        b"trailer\n<< /Size 6 /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_offset).encode() + b"\n%%EOF\n"
    )
    return body


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

def test_public_symbols():
    assert hasattr(pdfextract, "extract_pdf")
    assert hasattr(pdfextract, "batch_extract")
    assert hasattr(pdfextract, "PDFParseError")
    assert hasattr(pdfextract, "PDFExtractor")
    assert hasattr(pdfextract, "PageResult")
    assert hasattr(pdfextract, "ExtractionResult")
    assert hasattr(pdfextract, "__version__")


# ---------------------------------------------------------------------------
# _decode_pdf_string
# ---------------------------------------------------------------------------

class TestDecodePDFString:
    def test_plain_ascii(self):
        assert _decode_pdf_string(b"Hello") == "Hello"

    def test_escape_newline(self):
        assert _decode_pdf_string(b"line1\\nline2") == "line1\nline2"

    def test_escape_tab(self):
        assert _decode_pdf_string(b"col1\\tcol2") == "col1\tcol2"

    def test_escape_parens(self):
        assert _decode_pdf_string(b"\\(text\\)") == "(text)"

    def test_escape_backslash(self):
        assert _decode_pdf_string(b"a\\\\b") == "a\\b"

    def test_octal_three_digits(self):
        # \101 = 0x41 = 'A'
        assert _decode_pdf_string(b"\\101") == "A"

    def test_octal_two_digits(self):
        # \101 interpreted as \10 + '1' when only two digits available would be wrong;
        # \12 = 0x0A = newline char (10 decimal)
        result = _decode_pdf_string(b"\\12x")
        assert result == "\nx"

    def test_octal_one_digit(self):
        # \7 = BEL (7)
        result = _decode_pdf_string(b"\\7!")
        assert result == "\x07!"

    def test_empty(self):
        assert _decode_pdf_string(b"") == ""


# ---------------------------------------------------------------------------
# _extract_text_from_stream
# ---------------------------------------------------------------------------

class TestExtractTextFromStream:
    def test_simple_tj(self):
        stream = b"BT (Hello World) Tj ET"
        assert "Hello World" in _extract_text_from_stream(stream)

    def test_tj_array(self):
        stream = b"BT [(Foo) 10 (Bar)] TJ ET"
        text = _extract_text_from_stream(stream)
        assert "Foo" in text
        assert "Bar" in text

    def test_multiple_bt_et_blocks(self):
        stream = b"BT (First) Tj ET some data BT (Second) Tj ET"
        text = _extract_text_from_stream(stream)
        assert "First" in text
        assert "Second" in text

    def test_no_bt_et_returns_empty(self):
        assert _extract_text_from_stream(b"no text operators here") == ""

    def test_empty_stream(self):
        assert _extract_text_from_stream(b"") == ""


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
    def _make(self) -> ExtractionResult:
        pages = [
            PageResult(page_number=1, text="Hello world"),
            PageResult(page_number=2, text="Foo bar baz"),
        ]
        return ExtractionResult(
            source="test.pdf",
            page_count=2,
            pages=pages,
            metadata={"Title": "Test Doc", "Author": "A. Author"},
            errors=[],
        )

    def test_full_text(self):
        er = self._make()
        assert "Hello world" in er.full_text
        assert "Foo bar baz" in er.full_text

    def test_word_count(self):
        er = self._make()
        assert er.word_count == 5  # 2 + 3

    def test_to_dict_keys(self):
        d = self._make().to_dict()
        for key in ("source", "page_count", "word_count", "metadata", "errors", "pages"):
            assert key in d

    def test_to_dict_pages(self):
        d = self._make().to_dict()
        assert len(d["pages"]) == 2
        assert d["pages"][0]["page"] == 1

    def test_to_dict_round_trip(self):
        d = self._make().to_dict()
        assert json.loads(json.dumps(d)) == d

    def test_to_markdown_contains_metadata(self):
        md = self._make().to_markdown()
        assert "Test Doc" in md
        assert "A. Author" in md

    def test_to_markdown_contains_pages(self):
        md = self._make().to_markdown()
        assert "## Page 1" in md
        assert "## Page 2" in md

    def test_skips_empty_pages_in_full_text(self):
        pages = [PageResult(page_number=1, text=""), PageResult(page_number=2, text="data")]
        er = ExtractionResult(source="x.pdf", page_count=2, pages=pages)
        assert er.full_text == "data"


# ---------------------------------------------------------------------------
# Integration: end-to-end extraction with a minimal synthesised PDF
# ---------------------------------------------------------------------------

class TestMinimalPDFExtraction:
    def test_extract_returns_result(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(_make_minimal_pdf("Test content"))
        result = PDFExtractor(str(pdf)).extract()
        assert isinstance(result, ExtractionResult)

    def test_page_count(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(_make_minimal_pdf())
        result = PDFExtractor(str(pdf)).extract()
        assert result.page_count == 1

    def test_text_extracted(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(_make_minimal_pdf("Extraction works"))
        result = PDFExtractor(str(pdf)).extract()
        assert "Extraction works" in result.full_text

    def test_source_name(self, tmp_path):
        pdf = tmp_path / "myfile.pdf"
        pdf.write_bytes(_make_minimal_pdf())
        result = PDFExtractor(str(pdf)).extract()
        assert result.source == "myfile.pdf"

    def test_no_errors_on_valid_pdf(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(_make_minimal_pdf())
        result = PDFExtractor(str(pdf)).extract()
        assert result.errors == []

    def test_max_pages_respected(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(_make_minimal_pdf())
        result = PDFExtractor(str(pdf), max_pages=1).extract()
        assert result.page_count <= 1


# ---------------------------------------------------------------------------
# extract_pdf convenience function
# ---------------------------------------------------------------------------

class TestExtractPDF:
    def test_text_format(self, tmp_path):
        pdf = tmp_path / "t.pdf"
        pdf.write_bytes(_make_minimal_pdf("Quick brown fox"))
        out = extract_pdf(str(pdf), output_format="text")
        assert isinstance(out, str)
        assert "Quick brown fox" in out

    def test_json_format(self, tmp_path):
        pdf = tmp_path / "t.pdf"
        pdf.write_bytes(_make_minimal_pdf("JSON test"))
        out = extract_pdf(str(pdf), output_format="json")
        parsed = json.loads(out)
        assert "pages" in parsed

    def test_markdown_format(self, tmp_path):
        pdf = tmp_path / "t.pdf"
        pdf.write_bytes(_make_minimal_pdf("Markdown test"))
        out = extract_pdf(str(pdf), output_format="markdown")
        assert "## Page" in out

    def test_output_file_written(self, tmp_path):
        pdf = tmp_path / "t.pdf"
        pdf.write_bytes(_make_minimal_pdf("Write to file"))
        out_file = tmp_path / "out.txt"
        extract_pdf(str(pdf), output_path=str(out_file))
        assert out_file.exists()
        assert "Write to file" in out_file.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# batch_extract
# ---------------------------------------------------------------------------

class TestBatchExtract:
    def test_processes_multiple_files(self, tmp_path):
        for name in ("a.pdf", "b.pdf"):
            (tmp_path / name).write_bytes(_make_minimal_pdf(name))
        results = batch_extract(str(tmp_path / "*.pdf"))
        assert len(results) == 2
        assert all(isinstance(r, ExtractionResult) for r in results)

    def test_output_dir_creates_files(self, tmp_path):
        pdf_dir = tmp_path / "pdfs"
        pdf_dir.mkdir()
        out_dir = tmp_path / "out"
        (pdf_dir / "doc.pdf").write_bytes(_make_minimal_pdf("batch test"))
        batch_extract(str(pdf_dir / "*.pdf"), output_format="text", output_dir=str(out_dir))
        assert (out_dir / "doc.txt").exists()

    def test_empty_glob_returns_empty_list(self, tmp_path):
        results = batch_extract(str(tmp_path / "*.pdf"))
        assert results == []


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_not_a_pdf_raises(self, tmp_path):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"This is not a PDF file")
        with pytest.raises(PDFParseError):
            PDFExtractor(str(bad)).extract()

    def test_xref_not_found_returns_error(self, tmp_path):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"%PDF-1.4\nno xref here")
        result = PDFExtractor(str(bad)).extract()
        assert result.errors  # graceful degradation, not an exception

    def test_nonexistent_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            PDFExtractor(str(tmp_path / "ghost.pdf")).extract()
