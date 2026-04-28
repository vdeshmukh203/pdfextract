"""Tests for pdfextract.

Covers: string decoding (including octal escapes), content-stream text
extraction, xref parsing, data-class serialisation, and a full round-trip
extraction using a minimal in-memory PDF.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure the src layout is importable when running pytest from the repo root.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pdfextract
from pdfextract._text import decode_pdf_string, extract_text_from_stream
from pdfextract._parser import (
    PDFParseError,
    find_xref_offset,
    parse_xref_table,
    is_page_object,
)
from pdfextract._schema import ExtractionResult, PageResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_minimal_pdf(page_text: bytes = b"Hello World") -> bytes:
    """Build a minimal valid PDF with one page containing *page_text*."""
    stream_content = b"BT /F1 12 Tf 100 700 Td (" + page_text + b") Tj ET"
    stream_len = len(stream_content)

    parts: list[bytes] = []
    offsets: dict[int, int] = {}

    parts.append(b"%PDF-1.4\n")

    offsets[1] = sum(len(p) for p in parts)
    parts.append(b"1 0 obj\n<</Type /Catalog /Pages 2 0 R>>\nendobj\n")

    offsets[2] = sum(len(p) for p in parts)
    parts.append(b"2 0 obj\n<</Type /Pages /Kids [3 0 R] /Count 1>>\nendobj\n")

    offsets[3] = sum(len(p) for p in parts)
    parts.append(
        b"3 0 obj\n"
        b"<</Type /Page /MediaBox [0 0 612 792] /Contents 4 0 R /Parent 2 0 R>>\n"
        b"endobj\n"
    )

    offsets[4] = sum(len(p) for p in parts)
    parts.append(
        b"4 0 obj\n<</Length " + str(stream_len).encode() + b">>\n"
        b"stream\n" + stream_content + b"\nendstream\nendobj\n"
    )

    xref_offset = sum(len(p) for p in parts)

    xref_lines = [b"xref\n", b"0 5\n", b"0000000000 65535 f \n"]
    for i in range(1, 5):
        xref_lines.append(str(offsets[i]).zfill(10).encode() + b" 00000 n \n")
    parts.extend(xref_lines)

    parts.append(
        b"trailer\n<</Size 5 /Root 1 0 R>>\n"
        b"startxref\n" + str(xref_offset).encode() + b"\n%%EOF\n"
    )

    return b"".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def test_public_api():
    assert hasattr(pdfextract, "extract_pdf")
    assert hasattr(pdfextract, "PDFExtractor")
    assert hasattr(pdfextract, "PDFParseError")
    assert hasattr(pdfextract, "PageResult")
    assert hasattr(pdfextract, "ExtractionResult")


# ---------------------------------------------------------------------------
# decode_pdf_string
# ---------------------------------------------------------------------------

class TestDecodePDFString:
    def test_plain_ascii(self):
        assert decode_pdf_string(b"Hello") == "Hello"

    def test_escape_newline(self):
        assert decode_pdf_string(b"a\\nb") == "a\nb"

    def test_escape_tab(self):
        assert decode_pdf_string(b"a\\tb") == "a\tb"

    def test_escape_paren(self):
        assert decode_pdf_string(b"a\\(b\\)c") == "a(b)c"

    def test_escape_backslash(self):
        assert decode_pdf_string(b"a\\\\b") == "a\\b"

    def test_octal_three_digits(self):
        # \101 = 65 = 'A'
        assert decode_pdf_string(b"\\101") == "A"

    def test_octal_two_digits(self):
        # \101 without third digit: \10 = 8 = backspace char
        assert decode_pdf_string(b"\\10x") == "\x08x"

    def test_octal_one_digit(self):
        # \1 = chr(1)
        assert decode_pdf_string(b"\\1z") == "\x01z"

    def test_octal_overflow_masked(self):
        # \377 = 255 & 0xFF = 255 → latin-1 char
        assert decode_pdf_string(b"\\377") == chr(0xFF)

    def test_line_continuation(self):
        # backslash followed by newline is ignored
        assert decode_pdf_string(b"hel\\\nlo") == "hello"

    def test_line_continuation_crlf(self):
        assert decode_pdf_string(b"hel\\\r\nlo") == "hello"

    def test_unknown_escape_passthrough(self):
        # Unknown escape sequences: emit the character after backslash
        assert decode_pdf_string(b"\\q") == "q"

    def test_empty(self):
        assert decode_pdf_string(b"") == ""


# ---------------------------------------------------------------------------
# extract_text_from_stream
# ---------------------------------------------------------------------------

class TestExtractTextFromStream:
    def test_simple_tj(self):
        stream = b"BT (Hello World) Tj ET"
        assert "Hello" in extract_text_from_stream(stream)
        assert "World" in extract_text_from_stream(stream)

    def test_tj_array(self):
        stream = b"BT [(Hello) 20 ( World)] TJ ET"
        text = extract_text_from_stream(stream)
        assert "Hello" in text
        assert "World" in text

    def test_no_duplication(self):
        # Strings inside a TJ array must appear exactly once.
        stream = b"BT [(Foo)] TJ ET"
        text = extract_text_from_stream(stream)
        assert text.count("Foo") == 1

    def test_multiple_bt_blocks(self):
        stream = b"BT (First) Tj ET BT (Second) Tj ET"
        text = extract_text_from_stream(stream)
        assert "First" in text
        assert "Second" in text

    def test_empty_stream(self):
        assert extract_text_from_stream(b"") == ""

    def test_no_bt_et(self):
        assert extract_text_from_stream(b"(No markers here)") == ""


# ---------------------------------------------------------------------------
# Parser: xref and page detection
# ---------------------------------------------------------------------------

class TestXref:
    def test_find_xref_offset(self):
        pdf = _make_minimal_pdf()
        offset = find_xref_offset(pdf)
        assert offset > 0
        assert pdf[offset:offset + 4] == b"xref"

    def test_parse_xref_returns_dict(self):
        pdf = _make_minimal_pdf()
        offset = find_xref_offset(pdf)
        xref = parse_xref_table(pdf, offset)
        assert isinstance(xref, dict)
        assert len(xref) > 0

    def test_xref_objects_have_valid_offsets(self):
        pdf = _make_minimal_pdf()
        offset = find_xref_offset(pdf)
        xref = parse_xref_table(pdf, offset)
        for obj_id, byte_off in xref.items():
            assert 0 <= byte_off < len(pdf)

    def test_no_startxref_raises(self):
        with pytest.raises(PDFParseError, match="startxref"):
            find_xref_offset(b"not a pdf at all")


class TestPageDetection:
    def test_detects_page_type_with_space(self):
        assert is_page_object(b"<</Type /Page /MediaBox [0 0 612 792]>>")

    def test_detects_page_type_without_space(self):
        assert is_page_object(b"<</Type/Page/MediaBox[0 0 612 792]>>")

    def test_rejects_non_page(self):
        assert not is_page_object(b"<</Type /Pages /Kids [3 0 R] /Count 1>>")

    def test_rejects_pages_type(self):
        # /Pages is NOT /Page
        assert not is_page_object(b"<</Type /Pages>>")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class TestPageResult:
    def test_word_count(self):
        pr = PageResult(page_number=1, text="one two three")
        assert pr.word_count == 3

    def test_char_count(self):
        pr = PageResult(page_number=1, text="hello")
        assert pr.char_count == 5

    def test_empty_text(self):
        pr = PageResult(page_number=1, text="")
        assert pr.word_count == 0
        assert pr.char_count == 0


class TestExtractionResult:
    def _make_result(self) -> ExtractionResult:
        pages = [
            PageResult(page_number=1, text="Hello World"),
            PageResult(page_number=2, text="Foo Bar Baz"),
        ]
        return ExtractionResult(
            source="test.pdf",
            page_count=2,
            pages=pages,
            metadata={"Title": "Test Doc"},
        )

    def test_full_text(self):
        r = self._make_result()
        assert "Hello World" in r.full_text
        assert "Foo Bar Baz" in r.full_text

    def test_word_count(self):
        r = self._make_result()
        assert r.word_count == 5  # 2 + 3

    def test_to_dict_keys(self):
        d = self._make_result().to_dict()
        for key in ("source", "page_count", "word_count", "metadata", "errors", "pages"):
            assert key in d

    def test_to_json_valid(self):
        j = self._make_result().to_json()
        parsed = json.loads(j)
        assert parsed["source"] == "test.pdf"
        assert parsed["page_count"] == 2

    def test_to_markdown_contains_headers(self):
        md = self._make_result().to_markdown()
        assert "# Extracted Text" in md
        assert "## Page 1" in md
        assert "## Page 2" in md
        assert "## Metadata" in md

    def test_errors_in_markdown(self):
        r = self._make_result()
        r.errors = ["something went wrong"]
        md = r.to_markdown()
        assert "## Warnings" in md
        assert "something went wrong" in md


# ---------------------------------------------------------------------------
# Full round-trip extraction
# ---------------------------------------------------------------------------

class TestFullExtraction:
    def test_extract_hello_world(self):
        pdf_bytes = _make_minimal_pdf(b"Hello World")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf_bytes)
            tmp_path = f.name

        result = pdfextract.PDFExtractor(tmp_path).extract()
        Path(tmp_path).unlink(missing_ok=True)

        assert result.page_count == 1
        assert "Hello" in result.full_text
        assert "World" in result.full_text
        assert result.word_count >= 2

    def test_extract_returns_extraction_result(self):
        pdf_bytes = _make_minimal_pdf()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf_bytes)
            tmp_path = f.name

        result = pdfextract.PDFExtractor(tmp_path).extract()
        Path(tmp_path).unlink(missing_ok=True)

        assert isinstance(result, pdfextract.ExtractionResult)

    def test_extract_pdf_text_format(self):
        pdf_bytes = _make_minimal_pdf(b"ScienceText")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf_bytes)
            tmp_path = f.name

        out = pdfextract.extract_pdf(tmp_path, output_format="text")
        Path(tmp_path).unlink(missing_ok=True)

        assert "ScienceText" in out

    def test_extract_pdf_json_format(self):
        pdf_bytes = _make_minimal_pdf(b"JsonTest")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf_bytes)
            tmp_path = f.name

        out = pdfextract.extract_pdf(tmp_path, output_format="json")
        Path(tmp_path).unlink(missing_ok=True)

        parsed = json.loads(out)
        assert "pages" in parsed
        full = " ".join(p["text"] for p in parsed["pages"])
        assert "JsonTest" in full

    def test_extract_pdf_markdown_format(self):
        pdf_bytes = _make_minimal_pdf(b"MarkdownTest")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf_bytes)
            tmp_path = f.name

        out = pdfextract.extract_pdf(tmp_path, output_format="markdown")
        Path(tmp_path).unlink(missing_ok=True)

        assert "## Page 1" in out
        assert "MarkdownTest" in out

    def test_extract_pdf_max_pages(self):
        # max_pages=0 means all; we just check it doesn't crash.
        pdf_bytes = _make_minimal_pdf()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf_bytes)
            tmp_path = f.name

        result = pdfextract.PDFExtractor(tmp_path, max_pages=1).extract()
        Path(tmp_path).unlink(missing_ok=True)

        assert result.page_count <= 1

    def test_extract_pdf_writes_output_file(self, tmp_path):
        pdf_bytes = _make_minimal_pdf(b"FileWrite")
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(pdf_bytes)
        out_file = tmp_path / "out.txt"

        pdfextract.extract_pdf(str(pdf_file), output_path=str(out_file))

        assert out_file.exists()
        assert "FileWrite" in out_file.read_text(encoding="utf-8")

    def test_not_pdf_file_error(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"This is not a PDF")
            tmp_path = f.name

        result = pdfextract.PDFExtractor(tmp_path).extract()
        Path(tmp_path).unlink(missing_ok=True)

        assert result.errors  # graceful degradation; errors recorded
        assert result.page_count == 0

    def test_missing_file_error(self):
        result = pdfextract.PDFExtractor("/nonexistent/path/file.pdf").extract()
        assert result.errors
        assert result.page_count == 0
