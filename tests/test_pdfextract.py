"""Tests for pdfextract.

Covers the data models, string decoders, text extraction from content streams,
and end-to-end extraction from a programmatically generated minimal PDF.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure the src layout is on the path when running without install
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pdfextract
from pdfextract import (
    ExtractionResult,
    PDFExtractor,
    PDFParseError,
    PageResult,
    extract_pdf,
)
from pdfextract.extractor import _extract_text_from_stream
from pdfextract.parser import _decode_hex_string, _decode_literal_string


# ---------------------------------------------------------------------------
# Minimal PDF factory
# ---------------------------------------------------------------------------

def _make_pdf(*page_texts: str) -> bytes:
    """Build a minimal, standards-compliant PDF with one page per *page_texts* entry."""
    objs: dict[int, bytes] = {}
    n_pages = len(page_texts)

    # Object 1: Catalog
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"

    # Object 2: Pages node
    kids = " ".join(f"{3 + i} 0 R" for i in range(n_pages))
    objs[2] = (
        f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode()
    )

    # Page objects and content streams (two objects per page)
    for i, text in enumerate(page_texts):
        page_obj_id = 3 + i
        stream_obj_id = 3 + n_pages + i
        objs[page_obj_id] = (
            f"<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 612 792] "
            f"/Contents {stream_obj_id} 0 R >>".encode()
        )
        stream_body = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET\n".encode()
        objs[stream_obj_id] = (
            b"<< /Length " + str(len(stream_body)).encode() + b" >>\n"
            b"stream\n" + stream_body + b"endstream"
        )

    # --- Serialize ---
    lines: list[bytes] = [b"%PDF-1.4\n"]
    offsets: dict[int, int] = {}

    for obj_id in sorted(objs):
        offsets[obj_id] = sum(len(l) for l in lines)
        lines.append(f"{obj_id} 0 obj\n".encode())
        lines.append(objs[obj_id])
        lines.append(b"\nendobj\n")

    xref_offset = sum(len(l) for l in lines)
    total_objs = max(objs) + 1

    lines.append(b"xref\n")
    lines.append(f"0 {total_objs}\n".encode())
    lines.append(b"0000000000 65535 f \r\n")
    for obj_id in range(1, total_objs):
        off = offsets.get(obj_id, 0)
        lines.append(f"{off:010d} 00000 n \r\n".encode())

    lines.append(b"trailer\n")
    lines.append(f"<< /Size {total_objs} /Root 1 0 R >>\n".encode())
    lines.append(b"startxref\n")
    lines.append(f"{xref_offset}\n".encode())
    lines.append(b"%%EOF\n")

    return b"".join(lines)


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

class TestPublicAPI:
    def test_extract_pdf_importable(self):
        assert callable(extract_pdf)

    def test_pdf_parse_error_is_exception(self):
        assert issubclass(PDFParseError, Exception)

    def test_page_result_in_namespace(self):
        assert PageResult is pdfextract.PageResult

    def test_extraction_result_in_namespace(self):
        assert ExtractionResult is pdfextract.ExtractionResult

    def test_version_string(self):
        assert isinstance(pdfextract.__version__, str)
        assert pdfextract.__version__


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class TestPageResult:
    def test_word_and_char_counts(self):
        p = PageResult(page_number=1, text="Hello World")
        assert p.word_count == 2
        assert p.char_count == 11

    def test_empty_text(self):
        p = PageResult(page_number=1, text="")
        assert p.word_count == 0
        assert p.char_count == 0


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
            metadata={"Title": "Test"},
        )

    def test_full_text_joins_pages(self):
        r = self._make_result()
        assert "Hello World" in r.full_text
        assert "Foo Bar Baz" in r.full_text

    def test_word_count_sums_pages(self):
        r = self._make_result()
        assert r.word_count == 5

    def test_to_dict_structure(self):
        r = self._make_result()
        d = r.to_dict()
        assert d["source"] == "test.pdf"
        assert d["page_count"] == 2
        assert len(d["pages"]) == 2
        assert d["pages"][0]["text"] == "Hello World"

    def test_to_json_valid(self):
        r = self._make_result()
        parsed = json.loads(r.to_json())
        assert parsed["word_count"] == 5

    def test_to_markdown_contains_headers(self):
        r = self._make_result()
        md = r.to_markdown()
        assert "## Page 1" in md
        assert "## Metadata" in md
        assert "**Title**: Test" in md


# ---------------------------------------------------------------------------
# String decoders
# ---------------------------------------------------------------------------

class TestStringDecoders:
    def test_literal_plain(self):
        assert _decode_literal_string(b"Hello") == "Hello"

    def test_literal_escaped_parens(self):
        assert _decode_literal_string(b"a\\(b\\)c") == "a(b)c"

    def test_literal_newline_escape(self):
        assert _decode_literal_string(b"a\\nb") == "a\nb"

    def test_literal_octal(self):
        # octal 110 = 'H', 145 = 'e', 154 = 'l', 157 = 'o'
        assert _decode_literal_string(b"\\110\\145\\154\\154\\157") == "Hello"

    def test_hex_string_basic(self):
        assert _decode_hex_string(b"48656c6c6f") == "Hello"

    def test_hex_string_with_spaces(self):
        assert _decode_hex_string(b"48 65 6c 6c 6f") == "Hello"

    def test_hex_string_odd_length_padded(self):
        # Odd hex digits: spec says pad with 0 on the right
        result = _decode_hex_string(b"4")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Content-stream text extraction
# ---------------------------------------------------------------------------

class TestStreamExtraction:
    def test_simple_tj(self):
        stream = b"BT (Hello World) Tj ET"
        assert "Hello" in _extract_text_from_stream(stream)

    def test_tj_array(self):
        stream = b"BT [(Foo) 20 (Bar)] TJ ET"
        result = _extract_text_from_stream(stream)
        assert "Foo" in result
        assert "Bar" in result

    def test_multiple_bt_blocks(self):
        stream = b"BT (First) Tj ET BT (Second) Tj ET"
        result = _extract_text_from_stream(stream)
        assert "First" in result
        assert "Second" in result

    def test_no_bt_blocks_returns_empty(self):
        stream = b"/F1 12 Tf"
        assert _extract_text_from_stream(stream) == ""

    def test_escaped_string(self):
        stream = rb"BT (Hello\nWorld) Tj ET"
        result = _extract_text_from_stream(stream)
        assert "Hello" in result


# ---------------------------------------------------------------------------
# End-to-end extraction from in-memory PDFs
# ---------------------------------------------------------------------------

class TestExtraction:
    def _write_pdf(self, pdf_bytes: bytes) -> Path:
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.write(pdf_bytes)
        tmp.close()
        return Path(tmp.name)

    def test_single_page_text(self):
        path = self._write_pdf(_make_pdf("Hello World"))
        result = PDFExtractor(str(path)).extract()
        assert result.page_count == 1
        assert "Hello" in result.full_text

    def test_multi_page(self):
        path = self._write_pdf(_make_pdf("Page one", "Page two", "Page three"))
        result = PDFExtractor(str(path)).extract()
        assert result.page_count == 3
        assert "Page one" in result.full_text
        assert "Page three" in result.full_text

    def test_max_pages_limit(self):
        path = self._write_pdf(_make_pdf("A", "B", "C"))
        result = PDFExtractor(str(path), max_pages=2).extract()
        assert result.page_count == 2

    def test_extract_pdf_text_format(self):
        path = self._write_pdf(_make_pdf("Hello extraction"))
        out = extract_pdf(str(path), output_format="text")
        assert "Hello" in out

    def test_extract_pdf_json_format(self):
        path = self._write_pdf(_make_pdf("JSON test"))
        out = extract_pdf(str(path), output_format="json")
        parsed = json.loads(out)
        assert parsed["page_count"] == 1

    def test_extract_pdf_markdown_format(self):
        path = self._write_pdf(_make_pdf("Markdown test"))
        out = extract_pdf(str(path), output_format="markdown")
        assert "## Page 1" in out

    def test_output_written_to_file(self):
        path = self._write_pdf(_make_pdf("Save test"))
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as out_f:
            out_path = out_f.name
        extract_pdf(str(path), output_path=out_path)
        content = Path(out_path).read_text(encoding="utf-8")
        assert "Save" in content

    def test_invalid_file_returns_error(self):
        path = self._write_pdf(b"not a pdf at all")
        result = PDFExtractor(str(path)).extract()
        assert result.errors

    def test_nonexistent_file_returns_error(self):
        result = PDFExtractor("/nonexistent/path/file.pdf").extract()
        assert result.errors

    def test_word_count_accurate(self):
        path = self._write_pdf(_make_pdf("one two three"))
        result = PDFExtractor(str(path)).extract()
        assert result.word_count == 3
