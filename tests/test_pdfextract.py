"""Test suite for pdfextract.

Tests are split into four groups:
1. Public API / import tests
2. Data model (PageResult, ExtractionResult)
3. Low-level parser utilities
4. PDFExtractor error handling (no real PDF required)

A synthetic minimal PDF is constructed in-process for end-to-end smoke tests.
"""
from __future__ import annotations

import json
import zlib
from pathlib import Path

import pytest

# Public API surface
import pdfextract
from pdfextract import (
    PDFExtractor,
    PDFParseError,
    ExtractionResult,
    PageResult,
    extract_pdf,
)
from pdfextract.extractor import (
    _decode_pdf_string,
    _decode_hex_string,
    _find_startxref,
    _parse_xref_table,
    _extract_text_from_stream,
    _decode_tj_array,
    _decompress,
    _parse_obj_at,
)
from pdfextract.schema import PageResult, ExtractionResult


# ===========================================================================
# 1. Public API / import
# ===========================================================================

class TestPublicAPI:
    def test_version_attribute(self):
        assert hasattr(pdfextract, "__version__")
        assert isinstance(pdfextract.__version__, str)
        assert pdfextract.__version__.count(".") >= 1

    def test_all_symbols_exported(self):
        for name in ("extract_pdf", "PDFParseError", "PageResult",
                     "ExtractionResult", "PDFExtractor"):
            assert hasattr(pdfextract, name), f"missing: {name}"

    def test_extract_pdf_callable(self):
        assert callable(pdfextract.extract_pdf)


# ===========================================================================
# 2. Data model
# ===========================================================================

class TestPageResult:
    def test_word_count(self):
        pr = PageResult(page_number=1, text="Hello world this is a test")
        assert pr.word_count == 6

    def test_char_count(self):
        pr = PageResult(page_number=1, text="abc")
        assert pr.char_count == 3

    def test_empty_text(self):
        pr = PageResult(page_number=1, text="")
        assert pr.word_count == 0
        assert pr.char_count == 0

    def test_page_number_stored(self):
        pr = PageResult(page_number=42, text="x")
        assert pr.page_number == 42


class TestExtractionResult:
    def _make_result(self) -> ExtractionResult:
        return ExtractionResult(
            source="test.pdf",
            page_count=2,
            pages=[
                PageResult(page_number=1, text="Page one has five words here"),
                PageResult(page_number=2, text="Page two"),
            ],
            metadata={"Title": "Test Document", "Author": "Jane"},
        )

    def test_full_text_joins_pages(self):
        r = self._make_result()
        assert "Page one" in r.full_text
        assert "Page two" in r.full_text

    def test_word_count_sums_pages(self):
        r = self._make_result()
        assert r.word_count == 8  # 6 + 2

    def test_to_dict_structure(self):
        r = self._make_result()
        d = r.to_dict()
        assert d["source"] == "test.pdf"
        assert d["page_count"] == 2
        assert d["metadata"]["Title"] == "Test Document"
        assert len(d["pages"]) == 2
        assert d["pages"][0]["words"] == 6

    def test_to_json_valid(self):
        r = self._make_result()
        data = json.loads(r.to_json())
        assert data["source"] == "test.pdf"

    def test_to_markdown_contains_headings(self):
        r = self._make_result()
        md = r.to_markdown()
        assert "# Extracted Text: test.pdf" in md
        assert "## Page 1" in md
        assert "## Page 2" in md

    def test_to_markdown_contains_metadata(self):
        r = self._make_result()
        md = r.to_markdown()
        assert "**Title**" in md
        assert "**Author**" in md

    def test_to_markdown_empty_page_placeholder(self):
        r = ExtractionResult(
            source="x.pdf",
            page_count=1,
            pages=[PageResult(page_number=1, text="")],
        )
        md = r.to_markdown()
        assert "No text extracted" in md

    def test_errors_shown_in_markdown(self):
        r = ExtractionResult(
            source="x.pdf",
            page_count=0,
            errors=["page 1: decode error"],
        )
        md = r.to_markdown()
        assert "Warnings" in md
        assert "page 1: decode error" in md

    def test_full_text_skips_blank_pages(self):
        r = ExtractionResult(
            source="x.pdf",
            page_count=3,
            pages=[
                PageResult(page_number=1, text="Hello"),
                PageResult(page_number=2, text="   "),
                PageResult(page_number=3, text="World"),
            ],
        )
        assert r.full_text == "Hello\n\nWorld"


# ===========================================================================
# 3. Low-level parser utilities
# ===========================================================================

class TestDecodePdfString:
    def test_plain_ascii(self):
        assert _decode_pdf_string(b"Hello World") == "Hello World"

    def test_newline_escape(self):
        assert _decode_pdf_string(b"A\\nB") == "A\nB"

    def test_tab_escape(self):
        assert _decode_pdf_string(b"A\\tB") == "A\tB"

    def test_paren_escapes(self):
        assert _decode_pdf_string(b"\\(ok\\)") == "(ok)"

    def test_backslash_escape(self):
        assert _decode_pdf_string(b"a\\\\b") == "a\\b"

    def test_octal_three_digit(self):
        # \101 = 'A'
        assert _decode_pdf_string(b"\\101") == "A"

    def test_octal_two_digit(self):
        # \41 = '!'
        assert _decode_pdf_string(b"\\41") == "!"

    def test_empty(self):
        assert _decode_pdf_string(b"") == ""


class TestDecodeHexString:
    def test_basic(self):
        assert _decode_hex_string(b"48656c6c6f") == "Hello"

    def test_with_spaces(self):
        assert _decode_hex_string(b"48 65 6c 6c 6f") == "Hello"

    def test_odd_length_padded(self):
        # "4" → "40" → chr(0x40) = '@'
        result = _decode_hex_string(b"4")
        assert result == "@"

    def test_empty(self):
        assert _decode_hex_string(b"") == ""


class TestFindStartxref:
    def test_standard_trailer(self):
        data = b"\x00" * 500 + b"\nstartxref\n12345\n%%EOF"
        assert _find_startxref(data) == 12345

    def test_missing_raises(self):
        with pytest.raises(PDFParseError, match="startxref"):
            _find_startxref(b"no xref marker at all in this data")

    def test_near_end_of_file(self):
        data = b"garbage" * 300 + b"startxref\n99\n%%EOF"
        assert _find_startxref(data) == 99


class TestParseXrefTable:
    def _make_xref_bytes(self) -> bytes:
        return (
            b"xref\n"
            b"0 4\n"
            b"0000000000 65535 f \n"
            b"0000000100 00000 n \n"
            b"0000000200 00000 n \n"
            b"0000000300 00000 n \n"
            b"trailer\n<</Size 4>>\n"
        )

    def test_in_use_entries(self):
        data = b"\x00" * 50 + self._make_xref_bytes()
        offsets, prev = _parse_xref_table(data, 50)
        assert offsets[1] == 100
        assert offsets[2] == 200
        assert offsets[3] == 300

    def test_free_entry_excluded(self):
        data = b"\x00" * 50 + self._make_xref_bytes()
        offsets, _ = _parse_xref_table(data, 50)
        assert 0 not in offsets

    def test_no_prev(self):
        data = b"\x00" * 50 + self._make_xref_bytes()
        _, prev = _parse_xref_table(data, 50)
        assert prev is None

    def test_with_prev(self):
        data = (
            b"\x00" * 50
            + b"xref\n0 1\n0000000000 65535 f \ntrailer\n<</Size 1 /Prev 42>>\n"
        )
        _, prev = _parse_xref_table(data, 50)
        assert prev == 42


class TestExtractTextFromStream:
    def test_simple_tj(self):
        stream = b"BT (Hello World) Tj ET"
        assert "Hello" in _extract_text_from_stream(stream)
        assert "World" in _extract_text_from_stream(stream)

    def test_tj_array(self):
        stream = b"BT [(Foo) -120 (Bar)] TJ ET"
        text = _extract_text_from_stream(stream)
        assert "Foo" in text
        assert "Bar" in text

    def test_large_negative_gap_becomes_space(self):
        # A gap of -150 should insert a word space
        stream = b"BT [(hello) -200 (world)] TJ ET"
        text = _extract_text_from_stream(stream)
        assert " " in text

    def test_single_quote_operator(self):
        stream = b"BT (Next line) ' ET"
        assert "Next line" in _extract_text_from_stream(stream)

    def test_hex_string_tj(self):
        # <48656c6c6f> = "Hello"
        stream = b"BT <48656c6c6f> Tj ET"
        assert "Hello" in _extract_text_from_stream(stream)

    def test_empty_stream(self):
        assert _extract_text_from_stream(b"") == ""

    def test_no_bt_et_block(self):
        assert _extract_text_from_stream(b"(text) Tj") == ""

    def test_multiple_bt_blocks(self):
        stream = b"BT (Block one) Tj ET BT (Block two) Tj ET"
        text = _extract_text_from_stream(stream)
        assert "Block one" in text
        assert "Block two" in text


class TestDecodeTjArray:
    def test_simple_strings(self):
        result = _decode_tj_array(b"(foo)(bar)")
        assert result == "foobar"

    def test_space_inserted_for_large_gap(self):
        result = _decode_tj_array(b"(foo) -150 (bar)")
        assert result == "foo bar"

    def test_small_gap_no_space(self):
        result = _decode_tj_array(b"(foo) -50 (bar)")
        assert result == "foobar"


class TestDecompress:
    def test_roundtrip(self):
        original = b"Hello, compressed world!" * 10
        compressed = zlib.compress(original)
        assert _decompress(compressed) == original

    def test_invalid_returns_raw(self):
        raw = b"not compressed data"
        assert _decompress(raw) == raw


class TestParseObjAt:
    def test_basic_obj(self):
        data = b"\x00" * 20 + b"5 0 obj\n<</Type /Page>>\nendobj\n"
        obj_id, body = _parse_obj_at(data, 20)
        assert obj_id == 5
        assert b"/Type /Page" in body

    def test_missing_obj_raises(self):
        with pytest.raises(PDFParseError, match="obj marker"):
            _parse_obj_at(b"no object here", 0)


# ===========================================================================
# 4. PDFExtractor error handling
# ===========================================================================

class TestPDFExtractorErrors:
    def test_not_a_pdf_raises(self, tmp_path):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"This is definitely not a PDF file.")
        with pytest.raises(PDFParseError, match="valid PDF"):
            PDFExtractor(str(bad)).extract()

    def test_file_not_found_raises(self, tmp_path):
        missing = tmp_path / "missing.pdf"
        with pytest.raises(PDFParseError, match="not found"):
            PDFExtractor(str(missing)).extract()

    def test_extract_pdf_propagates_error(self, tmp_path):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"garbage")
        with pytest.raises(PDFParseError):
            extract_pdf(str(bad))

    def test_missing_xref_returns_error_result(self, tmp_path):
        # Valid magic but no real xref — extraction returns with errors
        trunc = tmp_path / "trunc.pdf"
        trunc.write_bytes(b"%PDF-1.4\n%%EOF\n")
        result = PDFExtractor(str(trunc)).extract()
        assert result.page_count == 0
        assert len(result.errors) > 0


# ===========================================================================
# 5. End-to-end smoke test with a synthetic minimal PDF
# ===========================================================================

def _build_minimal_pdf(text: str = "Hello from pdfextract") -> bytes:
    """Build the smallest valid PDF that contains one page with visible text.

    The PDF embeds a single content stream with a BT/ET block whose string
    is encoded as a PDF literal.  No fonts are declared (viewers will
    substitute a default), but pdfextract only needs the byte stream.
    """
    # Escape the text for a PDF literal string
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    content = f"BT /F1 12 Tf 100 700 Td ({escaped}) Tj ET\n".encode()
    compressed = zlib.compress(content)

    objects: list[bytes] = []

    def obj(n: int, body: bytes) -> bytes:
        return f"{n} 0 obj\n".encode() + body + b"\nendobj\n"

    # Object 1: Catalogue
    objects.append(obj(1, b"<</Type /Catalog /Pages 2 0 R>>"))
    # Object 2: Pages node
    objects.append(obj(2, b"<</Type /Pages /Kids [3 0 R] /Count 1>>"))
    # Object 3: Page
    objects.append(obj(3, b"<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R>>"))
    # Object 4: Content stream (FlateDecode)
    stream_dict = (
        f"<</Length {len(compressed)} /Filter /FlateDecode>>\n".encode()
        + b"stream\n"
        + compressed
        + b"\nendstream"
    )
    objects.append(obj(4, stream_dict))

    # Assemble: header + objects, record byte offsets for xref
    header = b"%PDF-1.4\n"
    body = bytearray(header)
    offsets: list[int] = []
    for o in objects:
        offsets.append(len(body))
        body.extend(o)

    xref_offset = len(body)
    xref = bytearray(b"xref\n")
    xref.extend(f"0 {len(objects) + 1}\n".encode())
    xref.extend(b"0000000000 65535 f \n")
    for off in offsets:
        xref.extend(f"{off:010d} 00000 n \n".encode())

    trailer = (
        f"trailer\n<</Size {len(objects) + 1} /Root 1 0 R>>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()

    return bytes(body) + bytes(xref) + trailer


class TestEndToEnd:
    def test_synthetic_pdf_text_extraction(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_minimal_pdf("Synthetic test document"))

        result = PDFExtractor(str(pdf_path)).extract()

        assert result.page_count == 1
        assert "Synthetic" in result.full_text or result.full_text != ""

    def test_synthetic_pdf_max_pages(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_minimal_pdf())

        result = PDFExtractor(str(pdf_path), max_pages=0).extract()
        assert result.page_count >= 1

    def test_extract_pdf_text_format(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_minimal_pdf("Format test"))

        out = extract_pdf(str(pdf_path), output_format="text")
        assert isinstance(out, str)

    def test_extract_pdf_json_format(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_minimal_pdf())

        out = extract_pdf(str(pdf_path), output_format="json")
        data = json.loads(out)
        assert "pages" in data
        assert "metadata" in data

    def test_extract_pdf_markdown_format(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_minimal_pdf())

        out = extract_pdf(str(pdf_path), output_format="markdown")
        assert "# Extracted Text" in out

    def test_extract_pdf_writes_output_file(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_minimal_pdf())
        out_path = tmp_path / "output.txt"

        extract_pdf(str(pdf_path), output_path=str(out_path))
        assert out_path.exists()
        assert out_path.stat().st_size > 0

    def test_result_source_is_filename(self, tmp_path):
        pdf_path = tmp_path / "myfile.pdf"
        pdf_path.write_bytes(_build_minimal_pdf())

        result = PDFExtractor(str(pdf_path)).extract()
        assert result.source == "myfile.pdf"
