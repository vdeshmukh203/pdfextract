"""Tests for pdfextract."""
from __future__ import annotations
import io
import sys
import zlib
from pathlib import Path

import pytest

# Ensure src/ is on the path for editable installs and direct runs
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pdfextract
from pdfextract import PDFExtractor, ExtractionResult, PageResult, PDFParseError, extract_pdf
from pdfextract._parser import (
    _decode_pdf_string,
    extract_text_from_stream,
    parse_xref_and_trailer,
    find_xref_offset,
)


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

class TestPublicAPI:
    def test_has_extract_pdf(self):
        assert callable(pdfextract.extract_pdf)

    def test_has_extract_batch(self):
        assert callable(pdfextract.extract_batch)

    def test_has_pdf_parse_error(self):
        assert issubclass(pdfextract.PDFParseError, Exception)

    def test_has_page_result(self):
        assert pdfextract.PageResult is not None

    def test_has_extraction_result(self):
        assert pdfextract.ExtractionResult is not None

    def test_version(self):
        assert hasattr(pdfextract, "__version__")
        assert pdfextract.__version__


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class TestPageResult:
    def test_word_and_char_counts(self):
        pr = PageResult(page_number=1, text="hello world foo")
        assert pr.word_count == 3
        assert pr.char_count == 15

    def test_empty_text(self):
        pr = PageResult(page_number=1, text="")
        assert pr.word_count == 0
        assert pr.char_count == 0


class TestExtractionResult:
    def _make(self) -> ExtractionResult:
        pages = [
            PageResult(page_number=1, text="Hello world"),
            PageResult(page_number=2, text="foo bar baz"),
        ]
        return ExtractionResult(
            source="test.pdf",
            page_count=2,
            pages=pages,
            metadata={"Title": "Test"},
            errors=[],
        )

    def test_full_text(self):
        r = self._make()
        assert "Hello world" in r.full_text
        assert "foo bar baz" in r.full_text

    def test_word_count(self):
        r = self._make()
        assert r.word_count == 5

    def test_to_dict_keys(self):
        d = self._make().to_dict()
        for key in ("source", "page_count", "word_count", "metadata", "errors", "pages"):
            assert key in d

    def test_to_json_valid(self):
        import json
        d = json.loads(self._make().to_json())
        assert d["source"] == "test.pdf"

    def test_to_markdown_contains_header(self):
        md = self._make().to_markdown()
        assert "# Extracted Text" in md
        assert "## Page 1" in md
        assert "Title" in md


# ---------------------------------------------------------------------------
# PDF string decoder
# ---------------------------------------------------------------------------

class TestDecodePDFString:
    def test_plain_ascii(self):
        assert _decode_pdf_string(b"hello") == "hello"

    def test_escape_n(self):
        assert _decode_pdf_string(b"a\\nb") == "a\nb"

    def test_escape_t(self):
        assert _decode_pdf_string(b"a\\tb") == "a\tb"

    def test_escape_parens(self):
        assert _decode_pdf_string(b"\\(hi\\)") == "(hi)"

    def test_octal(self):
        # \101 = 'A'
        assert _decode_pdf_string(b"\\101") == "A"

    def test_empty(self):
        assert _decode_pdf_string(b"") == ""


# ---------------------------------------------------------------------------
# Text stream extraction
# ---------------------------------------------------------------------------

class TestExtractTextFromStream:
    def test_simple_tj(self):
        stream = b"BT (Hello World) Tj ET"
        assert "Hello World" in extract_text_from_stream(stream)

    def test_tj_array(self):
        stream = b"BT [(foo) 10 (bar)] TJ ET"
        result = extract_text_from_stream(stream)
        assert "foo" in result
        assert "bar" in result

    def test_no_duplicate_from_tj_array(self):
        stream = b"BT [(word)] TJ ET"
        result = extract_text_from_stream(stream)
        # "word" should appear exactly once
        assert result.count("word") == 1

    def test_multiple_bt_et(self):
        stream = b"BT (alpha) Tj ET BT (beta) Tj ET"
        result = extract_text_from_stream(stream)
        assert "alpha" in result
        assert "beta" in result

    def test_empty_stream(self):
        assert extract_text_from_stream(b"") == ""

    def test_no_bt_et(self):
        assert extract_text_from_stream(b"(ignored outside BT/ET)") == ""


# ---------------------------------------------------------------------------
# PDFExtractor with a minimal synthetic PDF
# ---------------------------------------------------------------------------

def _make_minimal_pdf(page_text: str = "Hello PDF") -> bytes:
    """Build the smallest valid PDF that pdfextract can parse."""
    # Compress the content stream
    content = f"BT ({page_text}) Tj ET".encode()
    compressed = zlib.compress(content)
    c_len = len(compressed)

    objects: list[bytes] = []

    # 1 0 obj  Catalog
    objects.append(b"1 0 obj\n<</Type /Catalog /Pages 2 0 R>>\nendobj\n")
    # 2 0 obj  Pages
    objects.append(b"2 0 obj\n<</Type /Pages /Kids [3 0 R] /Count 1>>\nendobj\n")
    # 3 0 obj  Page (references content stream 4 0 R)
    objects.append(b"3 0 obj\n<</Type /Page /Parent 2 0 R /Contents 4 0 R>>\nendobj\n")
    # 4 0 obj  Content stream
    obj4_header = f"4 0 obj\n<</Length {c_len} /Filter /FlateDecode>>\nstream\n".encode()
    obj4 = obj4_header + compressed + b"\nendstream\nendobj\n"
    objects.append(obj4)
    # 5 0 obj  Info
    objects.append(b"5 0 obj\n<</Title (Test Document) /Author (Unit Test)>>\nendobj\n")

    body = b"%PDF-1.4\n"
    offsets: list[int] = []
    for obj in objects:
        offsets.append(len(body))
        body += obj

    xref_offset = len(body)
    xref = b"xref\n0 6\n0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n".encode()

    trailer = (
        b"trailer\n<</Size 6 /Root 1 0 R /Info 5 0 R>>\n"
        b"startxref\n" + str(xref_offset).encode() + b"\n%%EOF\n"
    )
    return body + xref + trailer


class TestPDFExtractorSynthetic:
    def setup_method(self):
        self._pdf_bytes = _make_minimal_pdf("Hello PDF")

    def _write_tmp(self, tmp_path: Path) -> Path:
        p = tmp_path / "test.pdf"
        p.write_bytes(self._pdf_bytes)
        return p

    def test_basic_extraction(self, tmp_path):
        p = self._write_tmp(tmp_path)
        result = PDFExtractor(str(p)).extract()
        assert result.page_count == 1
        assert not result.errors

    def test_metadata_extracted(self, tmp_path):
        p = self._write_tmp(tmp_path)
        result = PDFExtractor(str(p)).extract()
        assert result.metadata.get("Title") == "Test Document"
        assert result.metadata.get("Author") == "Unit Test"

    def test_max_pages_respected(self, tmp_path):
        p = self._write_tmp(tmp_path)
        result = PDFExtractor(str(p), max_pages=0).extract()
        assert result.page_count >= 1

    def test_not_a_pdf_raises(self, tmp_path):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"not a pdf file")
        with pytest.raises(PDFParseError):
            PDFExtractor(str(bad)).extract()

    def test_extract_pdf_text(self, tmp_path):
        p = self._write_tmp(tmp_path)
        out = extract_pdf(str(p), output_format="text")
        assert isinstance(out, str)

    def test_extract_pdf_json(self, tmp_path):
        import json
        p = self._write_tmp(tmp_path)
        out = extract_pdf(str(p), output_format="json")
        d = json.loads(out)
        assert "pages" in d

    def test_extract_pdf_markdown(self, tmp_path):
        p = self._write_tmp(tmp_path)
        out = extract_pdf(str(p), output_format="markdown")
        assert "# Extracted Text" in out

    def test_extract_pdf_to_file(self, tmp_path):
        p = self._write_tmp(tmp_path)
        out_file = tmp_path / "out.txt"
        extract_pdf(str(p), output_path=str(out_file))
        assert out_file.exists()
        assert out_file.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Batch extraction
# ---------------------------------------------------------------------------

class TestExtractBatch:
    def test_batch_returns_list(self, tmp_path):
        pdf = _make_minimal_pdf()
        p1 = tmp_path / "a.pdf"
        p2 = tmp_path / "b.pdf"
        p1.write_bytes(pdf)
        p2.write_bytes(pdf)
        results = pdfextract.extract_batch([str(p1), str(p2)])
        assert len(results) == 2
        assert all(isinstance(r, ExtractionResult) for r in results)

    def test_batch_writes_output_dir(self, tmp_path):
        pdf = _make_minimal_pdf()
        p = tmp_path / "doc.pdf"
        p.write_bytes(pdf)
        out_dir = tmp_path / "output"
        pdfextract.extract_batch([str(p)], output_format="text", output_dir=str(out_dir))
        assert (out_dir / "doc.txt").exists()
