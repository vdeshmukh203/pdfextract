"""
Tests for pdfextract.

Covers:
- Public API surface and version string
- PageResult and ExtractionResult data-model behaviour
- PDF literal-string decoding (octal escapes, common sequences)
- Content-stream text extraction (Tj and TJ operators)
- Cross-reference table parsing and the scan fallback
- Integration with a synthetically generated minimal valid PDF
- CLI argument parsing
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Allow running without an installed package (src layout)
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pdfextract
from pdfextract import ExtractionResult, PageResult, PDFExtractor, PDFParseError, extract_pdf
from pdfextract.parser import (
    build_xref,
    decode_pdf_string,
    extract_text_from_stream,
    find_xref_offset,
)


# ---------------------------------------------------------------------------
# Minimal-PDF factory
# ---------------------------------------------------------------------------


def _build_minimal_pdf(text: str = "Hello World") -> bytes:
    """Build a syntactically valid single-page PDF in memory for testing."""
    content = f"BT /F1 12 Tf 100 700 Td ({text}) Tj ET\n".encode()

    obj1 = b"<</Type /Catalog /Pages 2 0 R>>"
    obj2 = b"<</Type /Pages /Kids [3 0 R] /Count 1>>"
    obj3 = (
        b"<</Type /Page /MediaBox [0 0 612 792]"
        b" /Contents 4 0 R /Parent 2 0 R>>"
    )
    obj4 = (
        b"<</Length " + str(len(content)).encode() + b">>\n"
        b"stream\n" + content + b"\nendstream"
    )

    header = b"%PDF-1.4\n"
    parts: list = [header]
    offsets: dict = {}

    for idx, body in enumerate([obj1, obj2, obj3, obj4], start=1):
        offsets[idx] = len(b"".join(parts))
        parts.append(f"{idx} 0 obj\n".encode() + body + b"\nendobj\n")

    xref_offset = len(b"".join(parts))
    xref = b"xref\n0 5\n0000000000 65535 f\r\n"
    for idx in range(1, 5):
        xref += f"{offsets[idx]:010d} 00000 n\r\n".encode()
    parts.append(xref)
    parts.append(
        b"trailer\n<</Size 5 /Root 1 0 R>>\nstartxref\n"
        + str(xref_offset).encode()
        + b"\n%%EOF\n"
    )
    return b"".join(parts)


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------


class TestPublicAPI:
    def test_extract_pdf_callable(self):
        assert callable(pdfextract.extract_pdf)

    def test_required_public_names(self):
        for name in ("PDFExtractor", "PDFParseError", "ExtractionResult", "PageResult"):
            assert hasattr(pdfextract, name), f"Missing public name: {name}"

    def test_version_is_nonempty_string(self):
        assert isinstance(pdfextract.__version__, str)
        assert pdfextract.__version__


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class TestPageResult:
    def test_word_count(self):
        assert PageResult(page_number=1, text="foo bar baz").word_count == 3

    def test_char_count(self):
        assert PageResult(page_number=1, text="hello").char_count == 5

    def test_empty_text(self):
        pr = PageResult(page_number=1, text="")
        assert pr.word_count == 0
        assert pr.char_count == 0


class TestExtractionResult:
    @pytest.fixture
    def result(self):
        return ExtractionResult(
            source="test.pdf",
            page_count=2,
            pages=[
                PageResult(page_number=1, text="foo bar"),
                PageResult(page_number=2, text="baz"),
            ],
            metadata={"Title": "Demo Paper", "Author": "J. Doe"},
        )

    def test_full_text_joins_pages(self, result):
        ft = result.full_text
        assert "foo bar" in ft
        assert "baz" in ft

    def test_full_text_skips_blank_pages(self):
        er = ExtractionResult(
            source="x.pdf",
            page_count=2,
            pages=[
                PageResult(page_number=1, text="   "),
                PageResult(page_number=2, text="real"),
            ],
        )
        assert er.full_text == "real"

    def test_word_count_sum(self, result):
        assert result.word_count == 3  # "foo bar" + "baz"

    def test_to_dict_structure(self, result):
        d = result.to_dict()
        assert d["source"] == "test.pdf"
        assert d["page_count"] == 2
        assert len(d["pages"]) == 2
        assert d["metadata"]["Title"] == "Demo Paper"

    def test_to_json_round_trips(self, result):
        d = json.loads(result.to_json())
        assert d["source"] == "test.pdf"
        assert d["word_count"] == 3

    def test_to_markdown_contains_page_headers(self, result):
        md = result.to_markdown()
        assert "## Page 1" in md
        assert "## Page 2" in md

    def test_to_markdown_contains_metadata(self, result):
        md = result.to_markdown()
        assert "## Metadata" in md
        assert "**Title**" in md
        assert "Demo Paper" in md

    def test_errors_field_defaults_empty(self):
        er = ExtractionResult(source="f.pdf", page_count=0)
        assert er.errors == []


# ---------------------------------------------------------------------------
# PDF literal string decoding
# ---------------------------------------------------------------------------


class TestDecodePDFString:
    def test_plain_ascii(self):
        assert decode_pdf_string(b"Hello") == "Hello"

    def test_newline_escape(self):
        assert decode_pdf_string(b"a\\nb") == "a\nb"

    def test_tab_escape(self):
        assert decode_pdf_string(b"a\\tb") == "a\tb"

    def test_paren_escapes(self):
        assert decode_pdf_string(b"\\(ok\\)") == "(ok)"

    def test_backslash_escape(self):
        assert decode_pdf_string(b"a\\\\b") == "a\\b"

    def test_three_digit_octal(self):
        # \110\145\154\154\157 == "Hello"
        assert decode_pdf_string(b"\\110\\145\\154\\154\\157") == "Hello"

    def test_one_digit_octal(self):
        assert decode_pdf_string(b"\\7") == "\x07"

    def test_two_digit_octal(self):
        assert decode_pdf_string(b"\\40") == " "

    def test_unknown_escape_passthrough(self):
        # Unknown escape: \z → 'z'
        assert decode_pdf_string(b"\\z") == "z"

    def test_empty_string(self):
        assert decode_pdf_string(b"") == ""


# ---------------------------------------------------------------------------
# Content-stream text extraction
# ---------------------------------------------------------------------------


class TestExtractTextFromStream:
    def test_simple_tj(self):
        assert "Hello World" in extract_text_from_stream(b"BT (Hello World) Tj ET")

    def test_tj_array(self):
        result = extract_text_from_stream(b"BT [(Foo) 0 (Bar)] TJ ET")
        assert "Foo" in result
        assert "Bar" in result

    def test_ignores_content_outside_bt_et(self):
        assert extract_text_from_stream(b"(text) Tj") == ""

    def test_multiple_bt_et_blocks(self):
        stream = b"BT (First) Tj ET some-ops BT (Second) Tj ET"
        result = extract_text_from_stream(stream)
        assert "First" in result
        assert "Second" in result

    def test_empty_stream(self):
        assert extract_text_from_stream(b"") == ""

    def test_strips_whitespace_tokens(self):
        result = extract_text_from_stream(b"BT (  ) Tj ET")
        assert result == ""


# ---------------------------------------------------------------------------
# Cross-reference parsing
# ---------------------------------------------------------------------------


class TestXref:
    def test_find_xref_offset(self):
        data = b"... startxref\n12345\n%%EOF"
        assert find_xref_offset(data) == 12345

    def test_find_xref_offset_missing_raises(self):
        with pytest.raises(PDFParseError):
            find_xref_offset(b"no startxref here")

    def test_build_xref_scan_fallback(self):
        # No valid xref table — fallback scan locates the object
        data = b"%PDF-1.4\n1 0 obj\n<</Type /Catalog>>\nendobj\nstartxref\n999\n%%EOF"
        xref = build_xref(data)
        assert 1 in xref

    def test_build_xref_classic_table(self, tmp_path):
        pdf_bytes = _build_minimal_pdf()
        xref = build_xref(pdf_bytes)
        # Objects 1–4 should be present
        for obj_id in range(1, 5):
            assert obj_id in xref, f"Object {obj_id} missing from xref"


# ---------------------------------------------------------------------------
# Integration: minimal PDF round-trip
# ---------------------------------------------------------------------------


class TestMinimalPDF:
    def test_returns_extraction_result(self, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(_build_minimal_pdf("Hello JOSS"))
        result = PDFExtractor(str(pdf_file)).extract()
        assert isinstance(result, ExtractionResult)

    def test_page_count_is_one(self, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(_build_minimal_pdf())
        result = PDFExtractor(str(pdf_file)).extract()
        assert result.page_count == 1

    def test_text_extracted(self, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(_build_minimal_pdf("JOSS review"))
        result = PDFExtractor(str(pdf_file)).extract()
        assert "JOSS review" in result.full_text

    def test_max_pages_limits_output(self, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(_build_minimal_pdf())
        result = PDFExtractor(str(pdf_file), max_pages=1).extract()
        assert result.page_count <= 1

    def test_non_pdf_raises_parse_error(self, tmp_path):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"this is not a pdf")
        with pytest.raises(PDFParseError):
            PDFExtractor(str(bad)).extract()

    def test_extract_pdf_text_format(self, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(_build_minimal_pdf("plain text"))
        out = extract_pdf(str(pdf_file), output_format="text")
        assert isinstance(out, str)

    def test_extract_pdf_json_format(self, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(_build_minimal_pdf())
        out = extract_pdf(str(pdf_file), output_format="json")
        d = json.loads(out)
        assert "pages" in d
        assert "source" in d

    def test_extract_pdf_markdown_format(self, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(_build_minimal_pdf())
        out = extract_pdf(str(pdf_file), output_format="markdown")
        assert "## Page" in out

    def test_extract_pdf_writes_output_file(self, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(_build_minimal_pdf())
        out_file = tmp_path / "out.txt"
        extract_pdf(str(pdf_file), output_path=str(out_file))
        assert out_file.exists()
        assert out_file.read_text(encoding="utf-8") is not None

    def test_errors_list_is_empty_on_valid_pdf(self, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(_build_minimal_pdf())
        result = PDFExtractor(str(pdf_file)).extract()
        assert result.errors == []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCLI:
    def test_main_is_callable(self):
        from pdfextract.cli import main
        assert callable(main)

    def test_help_exits_zero(self, capsys):
        from pdfextract.cli import main
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "pdfextract" in out.lower()

    def test_text_output(self, tmp_path, capsys):
        from pdfextract.cli import main
        pdf_file = tmp_path / "t.pdf"
        pdf_file.write_bytes(_build_minimal_pdf("cli test"))
        main([str(pdf_file)])
        out = capsys.readouterr().out
        assert "cli test" in out

    def test_json_output(self, tmp_path, capsys):
        from pdfextract.cli import main
        pdf_file = tmp_path / "t.pdf"
        pdf_file.write_bytes(_build_minimal_pdf())
        main([str(pdf_file), "-f", "json"])
        out = capsys.readouterr().out
        d = json.loads(out)
        assert "pages" in d

    def test_write_to_file(self, tmp_path):
        from pdfextract.cli import main
        pdf_file = tmp_path / "t.pdf"
        out_file = tmp_path / "out.txt"
        pdf_file.write_bytes(_build_minimal_pdf())
        main([str(pdf_file), "-o", str(out_file)])
        assert out_file.exists()
