"""Tests for pdfextract."""
import json
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure the src layout is importable from the repo root.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pdfextract
from pdfextract import PDFExtractor, ExtractionResult, PageResult, PDFParseError, extract_pdf
from pdfextract.extractor import (
    _decode_pdf_string,
    _extract_text_from_stream,
    _parse_xref_table,
    _find_xref_offset,
)
from pdfextract.schema import ExtractionResult as SchemaExtractionResult


# ---------------------------------------------------------------------------
# Minimal syntactically valid PDF for functional tests
# ---------------------------------------------------------------------------

def _make_minimal_pdf(text: str = "Hello PDF") -> bytes:
    """
    Build a minimal, structurally valid single-page PDF containing *text*.
    The content stream uses a simple (text) Tj operator.
    """
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode()
    c_len = len(content)

    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    obj3 = (
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Contents 4 0 R >>\nendobj\n"
    )
    obj4 = (
        b"4 0 obj\n"
        b"<< /Length " + str(c_len).encode() + b" >>\n"
        b"stream\n" + content + b"\nendstream\nendobj\n"
    )

    header = b"%PDF-1.4\n"
    body = obj1 + obj2 + obj3 + obj4
    xref_offset = len(header) + len(body)

    offsets = [
        len(header),
        len(header) + len(obj1),
        len(header) + len(obj1) + len(obj2),
        len(header) + len(obj1) + len(obj2) + len(obj3),
    ]
    xref = b"xref\n0 5\n"
    xref += b"0000000000 65535 f \n"
    for off in offsets:
        xref += ("%010d 00000 n \n" % off).encode()

    trailer = (
        b"trailer\n<< /Size 5 /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_offset).encode() + b"\n%%EOF\n"
    )
    return header + body + xref + trailer


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------

def test_public_api():
    assert hasattr(pdfextract, "extract_pdf")
    assert hasattr(pdfextract, "PDFParseError")
    assert hasattr(pdfextract, "PageResult")
    assert hasattr(pdfextract, "ExtractionResult")
    assert hasattr(pdfextract, "PDFExtractor")
    assert hasattr(pdfextract, "__version__")


def test_version_string():
    assert isinstance(pdfextract.__version__, str)
    parts = pdfextract.__version__.split(".")
    assert len(parts) >= 2


# ---------------------------------------------------------------------------
# _decode_pdf_string
# ---------------------------------------------------------------------------

def test_decode_simple():
    assert _decode_pdf_string(b"hello") == "hello"


def test_decode_escape_sequences():
    assert _decode_pdf_string(b"a\\nb") == "a\nb"
    assert _decode_pdf_string(b"a\\tb") == "a\tb"
    assert _decode_pdf_string(b"\\(paren\\)") == "(paren)"
    assert _decode_pdf_string(b"back\\\\slash") == "back\\slash"


def test_decode_octal_three_digits():
    # \101 = 65 = 'A'
    assert _decode_pdf_string(b"\\101") == "A"


def test_decode_octal_two_digits():
    # \101 should be A; \12 = 10 = LF
    assert _decode_pdf_string(b"\\12x") == "\nx"


def test_decode_octal_one_digit():
    # \0 = null
    assert _decode_pdf_string(b"\\0z") == "\x00z"


def test_decode_utf16be_bom():
    # BOM + UTF-16-BE encoding of "Hi"
    raw = b"\xfe\xff\x00H\x00i"
    from pdfextract.extractor import _pdf_string_to_str
    assert _pdf_string_to_str(raw) == "Hi"


# ---------------------------------------------------------------------------
# Content stream text extraction
# ---------------------------------------------------------------------------

def test_extract_text_simple_tj():
    stream = b"BT (Hello World) Tj ET"
    assert "Hello World" in _extract_text_from_stream(stream)


def test_extract_text_tj_array():
    stream = b"BT [(Foo) 10 (Bar)] TJ ET"
    result = _extract_text_from_stream(stream)
    assert "Foo" in result
    assert "Bar" in result


def test_extract_text_empty_stream():
    assert _extract_text_from_stream(b"") == ""


def test_extract_text_no_bt_et():
    assert _extract_text_from_stream(b"(Text outside BT/ET) Tj") == ""


# ---------------------------------------------------------------------------
# xref parsing
# ---------------------------------------------------------------------------

def test_find_xref_offset():
    data = b"garbage\nstartxref\n1234\n%%EOF"
    assert _find_xref_offset(data) == 1234


def test_find_xref_offset_missing():
    with pytest.raises(PDFParseError):
        _find_xref_offset(b"no xref here")


def test_parse_xref_table_basic():
    xref_block = (
        b"xref\n"
        b"0 3\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
    )
    offsets = _parse_xref_table(xref_block, 0)
    assert offsets[1] == 9
    assert offsets[2] == 58
    assert 0 not in offsets  # free entry


# ---------------------------------------------------------------------------
# Functional end-to-end tests
# ---------------------------------------------------------------------------

def test_extract_returns_extraction_result():
    pdf_bytes = _make_minimal_pdf("Test content")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp = Path(f.name)
    try:
        result = PDFExtractor(tmp).extract()
        assert isinstance(result, ExtractionResult)
    finally:
        tmp.unlink()


def test_extract_finds_text():
    pdf_bytes = _make_minimal_pdf("Unique phrase XYZ")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp = Path(f.name)
    try:
        result = PDFExtractor(tmp).extract()
        assert "Unique phrase XYZ" in result.full_text
    finally:
        tmp.unlink()


def test_extract_page_count():
    pdf_bytes = _make_minimal_pdf("Page one")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp = Path(f.name)
    try:
        result = PDFExtractor(tmp).extract()
        assert result.page_count >= 1
    finally:
        tmp.unlink()


def test_extract_word_count():
    pdf_bytes = _make_minimal_pdf("one two three four five")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp = Path(f.name)
    try:
        result = PDFExtractor(tmp).extract()
        assert result.word_count >= 5
    finally:
        tmp.unlink()


def test_extract_max_pages():
    pdf_bytes = _make_minimal_pdf("Content")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp = Path(f.name)
    try:
        result = PDFExtractor(tmp, max_pages=1).extract()
        assert result.page_count <= 1
    finally:
        tmp.unlink()


def test_extract_pdf_text_format():
    pdf_bytes = _make_minimal_pdf("Text format test")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp = Path(f.name)
    try:
        out = extract_pdf(tmp, output_format="text")
        assert isinstance(out, str)
        assert "Text format test" in out
    finally:
        tmp.unlink()


def test_extract_pdf_json_format():
    pdf_bytes = _make_minimal_pdf("JSON test")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp = Path(f.name)
    try:
        out = extract_pdf(tmp, output_format="json")
        data = json.loads(out)
        assert "pages" in data
        assert "word_count" in data
        assert "metadata" in data
    finally:
        tmp.unlink()


def test_extract_pdf_markdown_format():
    pdf_bytes = _make_minimal_pdf("Markdown test")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp = Path(f.name)
    try:
        out = extract_pdf(tmp, output_format="markdown")
        assert "## Page" in out
        assert "Markdown test" in out
    finally:
        tmp.unlink()


def test_extract_pdf_writes_file():
    pdf_bytes = _make_minimal_pdf("Write to file")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        pdf_path = Path(f.name)
    out_path = pdf_path.with_suffix(".txt")
    try:
        extract_pdf(pdf_path, output_format="text", output_path=out_path)
        assert out_path.exists()
        assert "Write to file" in out_path.read_text(encoding="utf-8")
    finally:
        pdf_path.unlink()
        if out_path.exists():
            out_path.unlink()


def test_extract_pdf_invalid_format():
    with pytest.raises(ValueError):
        extract_pdf("any.pdf", output_format="html")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_not_a_pdf():
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"This is not a PDF at all")
        tmp = Path(f.name)
    try:
        with pytest.raises(PDFParseError):
            PDFExtractor(tmp).extract()
    finally:
        tmp.unlink()


def test_file_not_found():
    with pytest.raises(FileNotFoundError):
        PDFExtractor("/nonexistent/path/file.pdf").extract()


def test_corrupt_xref():
    # Valid header but broken xref — should return result with error, not crash.
    bad = b"%PDF-1.4\n1 0 obj\n<< >>\nendobj\nstartxref\n9999999\n%%EOF"
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(bad)
        tmp = Path(f.name)
    try:
        result = PDFExtractor(tmp).extract()
        assert isinstance(result, ExtractionResult)
        assert len(result.errors) > 0
    finally:
        tmp.unlink()


# ---------------------------------------------------------------------------
# ExtractionResult serialisation
# ---------------------------------------------------------------------------

def test_to_dict_schema():
    page = PageResult(page_number=1, text="hello world")
    result = ExtractionResult(
        source="test.pdf", page_count=1, pages=[page], metadata={"Title": "T"}
    )
    d = result.to_dict()
    assert d["source"] == "test.pdf"
    assert d["page_count"] == 1
    assert d["word_count"] == 2
    assert d["metadata"] == {"Title": "T"}
    assert d["pages"][0]["words"] == 2
    assert d["pages"][0]["chars"] == len("hello world")


def test_to_json_is_valid():
    page = PageResult(page_number=1, text="abc")
    result = ExtractionResult(source="x.pdf", page_count=1, pages=[page])
    data = json.loads(result.to_json())
    assert data["source"] == "x.pdf"


def test_to_markdown_contains_headers():
    page = PageResult(page_number=1, text="body text")
    result = ExtractionResult(source="doc.pdf", page_count=1, pages=[page])
    md = result.to_markdown()
    assert "## Page 1" in md
    assert "body text" in md


def test_page_result_counts():
    p = PageResult(page_number=3, text="one two three")
    assert p.word_count == 3
    assert p.char_count == 13


def test_full_text_skips_blank_pages():
    pages = [
        PageResult(page_number=1, text="first"),
        PageResult(page_number=2, text="   "),
        PageResult(page_number=3, text="third"),
    ]
    result = ExtractionResult(source="f.pdf", page_count=3, pages=pages)
    assert "first" in result.full_text
    assert "third" in result.full_text
    assert result.full_text.count("\n\n") == 1  # only one separator between non-blank pages
