"""
Tests for pdfextract.

Coverage includes:
- Public API surface (imports, classes, functions)
- PDF string decoding (octal, common escapes)
- Text extraction from synthetic content streams
- ExtractionResult serialisation (dict, JSON, Markdown)
- PDFExtractor error handling (missing file, non-PDF bytes)
- xref table parsing
- Page tree traversal helpers
- Metadata parsing
- GUI module importability
"""
from __future__ import annotations

import io
import json
import struct
import tempfile
import zlib
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Package-level imports
# ---------------------------------------------------------------------------

def test_public_api_exports():
    import pdfextract
    for name in ["extract_pdf", "PDFExtractor", "ExtractionResult",
                 "PageResult", "PDFParseError", "__version__"]:
        assert hasattr(pdfextract, name), f"missing export: {name}"


def test_version_string():
    import pdfextract
    assert isinstance(pdfextract.__version__, str)
    assert pdfextract.__version__  # non-empty


# ---------------------------------------------------------------------------
# schema: PageResult
# ---------------------------------------------------------------------------

def test_page_result_counts():
    from pdfextract import PageResult
    p = PageResult(page_number=1, text="hello world test")
    assert p.word_count == 3
    assert p.char_count == 16
    assert p.page_number == 1


def test_page_result_empty_text():
    from pdfextract import PageResult
    p = PageResult(page_number=2, text="")
    assert p.word_count == 0
    assert p.char_count == 0


# ---------------------------------------------------------------------------
# schema: ExtractionResult
# ---------------------------------------------------------------------------

def test_extraction_result_full_text():
    from pdfextract import ExtractionResult, PageResult
    r = ExtractionResult(
        source="test.pdf",
        page_count=2,
        pages=[PageResult(1, "Page one."), PageResult(2, "Page two.")],
    )
    assert "Page one." in r.full_text
    assert "Page two." in r.full_text
    assert r.word_count == 4


def test_extraction_result_skips_blank_pages():
    from pdfextract import ExtractionResult, PageResult
    r = ExtractionResult(
        source="test.pdf",
        page_count=3,
        pages=[PageResult(1, "Hello"), PageResult(2, "   "), PageResult(3, "World")],
    )
    assert "   " not in r.full_text


def test_extraction_result_to_dict():
    from pdfextract import ExtractionResult, PageResult
    r = ExtractionResult(
        source="doc.pdf", page_count=1,
        pages=[PageResult(1, "Some text")],
        metadata={"Title": "Test"},
    )
    d = r.to_dict()
    assert d["source"] == "doc.pdf"
    assert d["page_count"] == 1
    assert d["metadata"]["Title"] == "Test"
    assert d["pages"][0]["text"] == "Some text"


def test_extraction_result_to_json():
    from pdfextract import ExtractionResult, PageResult
    r = ExtractionResult(
        source="doc.pdf", page_count=1,
        pages=[PageResult(1, "text")],
    )
    payload = json.loads(r.to_json())
    assert payload["source"] == "doc.pdf"


def test_extraction_result_to_markdown():
    from pdfextract import ExtractionResult, PageResult
    r = ExtractionResult(
        source="paper.pdf", page_count=2,
        pages=[PageResult(1, "Intro"), PageResult(2, "Conclusion")],
        metadata={"Author": "Alice"},
    )
    md = r.to_markdown()
    assert "# Extracted Text: paper.pdf" in md
    assert "**Author**: Alice" in md
    assert "## Page 1" in md
    assert "Intro" in md


def test_extraction_result_markdown_with_warnings():
    from pdfextract import ExtractionResult, PageResult
    r = ExtractionResult(
        source="bad.pdf", page_count=0,
        errors=["page 1 error: foo"],
    )
    md = r.to_markdown()
    assert "## Warnings" in md
    assert "page 1 error" in md


# ---------------------------------------------------------------------------
# parser: PDF string decoding
# ---------------------------------------------------------------------------

def test_decode_pdf_string_plain():
    from pdfextract.parser import _decode_pdf_string
    assert _decode_pdf_string(b"Hello") == "Hello"


def test_decode_pdf_string_newline_escape():
    from pdfextract.parser import _decode_pdf_string
    assert _decode_pdf_string(b"line1\\nline2") == "line1\nline2"


def test_decode_pdf_string_octal():
    from pdfextract.parser import _decode_pdf_string
    # \101 = 65 = 'A'
    assert _decode_pdf_string(b"\\101") == "A"


def test_decode_pdf_string_escaped_parens():
    from pdfextract.parser import _decode_pdf_string
    assert _decode_pdf_string(b"\\(hello\\)") == "(hello)"


def test_decode_pdf_string_backslash():
    from pdfextract.parser import _decode_pdf_string
    assert _decode_pdf_string(b"a\\\\b") == "a\\b"


def test_decode_pdf_string_high_octal():
    from pdfextract.parser import _decode_pdf_string
    # \377 = 255 → chr(255) = 'ÿ'
    result = _decode_pdf_string(b"\\377")
    assert ord(result) == 255


# ---------------------------------------------------------------------------
# parser: text extraction from synthetic content streams
# ---------------------------------------------------------------------------

def _make_stream(bt_content: bytes) -> bytes:
    return b"BT\n" + bt_content + b"\nET"


def test_extract_text_simple_tj():
    from pdfextract.parser import extract_text_from_stream
    stream = _make_stream(b"(Hello World) Tj")
    text = extract_text_from_stream(stream)
    assert "Hello" in text
    assert "World" in text


def test_extract_text_tj_array():
    from pdfextract.parser import extract_text_from_stream
    stream = _make_stream(b"[(foo) (bar)] TJ")
    text = extract_text_from_stream(stream)
    assert "foo" in text
    assert "bar" in text


def test_extract_text_no_duplicate_tj():
    """Strings in TJ arrays must not be emitted twice."""
    from pdfextract.parser import extract_text_from_stream
    stream = _make_stream(b"[(dup)] TJ")
    text = extract_text_from_stream(stream)
    assert text.count("dup") == 1


def test_extract_text_multiple_bt_blocks():
    from pdfextract.parser import extract_text_from_stream
    stream = b"BT (First) Tj ET\nBT (Second) Tj ET"
    text = extract_text_from_stream(stream)
    assert "First" in text
    assert "Second" in text


def test_extract_text_empty_stream():
    from pdfextract.parser import extract_text_from_stream
    assert extract_text_from_stream(b"") == ""


def test_extract_text_no_bt_et():
    from pdfextract.parser import extract_text_from_stream
    # Content without BT/ET produces no text
    text = extract_text_from_stream(b"(some text) Tj")
    assert text == ""


# ---------------------------------------------------------------------------
# parser: xref table
# ---------------------------------------------------------------------------

def test_parse_xref_table_basic():
    from pdfextract.parser import _parse_xref_table
    # Minimal valid xref table
    data = (
        b"xref\n"
        b"0 3\n"
        b"0000000000 65535 f \n"
        b"0000000100 00000 n \n"
        b"0000000200 00000 n \n"
        b"trailer\n<<\n/Size 3\n>>\n"
    )
    offsets, trailer = _parse_xref_table(data, 0)
    assert offsets[1] == 100
    assert offsets[2] == 200
    assert 0 not in offsets  # free object excluded


def test_parse_xref_table_free_entries_excluded():
    from pdfextract.parser import _parse_xref_table
    data = (
        b"xref\n"
        b"0 2\n"
        b"0000000000 65535 f \n"
        b"0000000050 00000 n \n"
        b"trailer\n<<>>\n"
    )
    offsets, _ = _parse_xref_table(data, 0)
    assert 0 not in offsets
    assert offsets[1] == 50


# ---------------------------------------------------------------------------
# parser: object parsing
# ---------------------------------------------------------------------------

def test_parse_obj_basic():
    from pdfextract.parser import parse_obj
    data = b"1 0 obj\n<</Type /Page>>\nendobj\n"
    obj_id, body = parse_obj(data, 0)
    assert obj_id == 1
    assert b"/Type /Page" in body


def test_parse_obj_not_found():
    from pdfextract.parser import parse_obj
    from pdfextract import PDFParseError
    with pytest.raises(PDFParseError, match="obj"):
        parse_obj(b"garbage data", 0)


# ---------------------------------------------------------------------------
# parser: stream extraction
# ---------------------------------------------------------------------------

def test_extract_stream_no_compression():
    from pdfextract.parser import extract_stream_bytes
    obj = b"1 0 obj\n<</Length 5>>\nstream\nhello\nendstream\nendobj"
    result = extract_stream_bytes(obj)
    assert result == b"hello\n"


def test_extract_stream_flate():
    from pdfextract.parser import extract_stream_bytes
    payload = b"compressed text"
    compressed = zlib.compress(payload)
    obj = (
        b"1 0 obj\n<</Filter /FlateDecode /Length "
        + str(len(compressed)).encode()
        + b">>\nstream\n"
        + compressed
        + b"\nendstream\nendobj"
    )
    result = extract_stream_bytes(obj)
    assert result == payload


def test_extract_stream_missing():
    from pdfextract.parser import extract_stream_bytes
    assert extract_stream_bytes(b"<</Type /Page>>") is None


# ---------------------------------------------------------------------------
# PDFExtractor: error handling
# ---------------------------------------------------------------------------

def test_extractor_file_not_found():
    from pdfextract import PDFExtractor
    with pytest.raises(FileNotFoundError):
        PDFExtractor("/no/such/file.pdf").extract()


def test_extractor_not_a_pdf():
    from pdfextract import PDFExtractor, PDFParseError
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"not a pdf file at all")
        tmp = f.name
    try:
        with pytest.raises(PDFParseError):
            PDFExtractor(tmp).extract()
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_extractor_corrupt_pdf_returns_errors():
    from pdfextract import PDFExtractor
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4\ngarbage\n")
        tmp = f.name
    try:
        result = PDFExtractor(tmp).extract()
        # Should not raise; errors collected in result.errors
        assert isinstance(result.errors, list)
    finally:
        Path(tmp).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Minimal synthetic PDF (round-trip smoke test)
# ---------------------------------------------------------------------------

def _build_minimal_pdf(text: str = "Hello PDF") -> bytes:
    """
    Build the smallest valid PDF containing one page with a single text string.
    Uses a classic xref table so no external library is needed.
    """
    encoded = text.encode("latin-1", errors="replace")
    content = b"BT /F1 12 Tf 72 720 Td (" + encoded + b") Tj ET"
    compressed = zlib.compress(content)

    objs: dict[int, bytes] = {}

    # obj 1: Catalog
    objs[1] = b"<</Type /Catalog /Pages 2 0 R>>"
    # obj 2: Pages
    objs[2] = b"<</Type /Pages /Kids [3 0 R] /Count 1>>"
    # obj 3: Page
    objs[3] = b"<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>>"
    # obj 4: Content stream
    objs[4] = (
        b"<</Filter /FlateDecode /Length " + str(len(compressed)).encode() + b">>\n"
        b"stream\n" + compressed + b"\nendstream"
    )
    # obj 5: Font (minimal)
    objs[5] = b"<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>"

    body = b"%PDF-1.4\n"
    offsets: dict[int, int] = {}
    for oid in sorted(objs):
        offsets[oid] = len(body)
        body += f"{oid} 0 obj\n".encode() + objs[oid] + b"\nendobj\n"

    xref_offset = len(body)
    n = max(objs) + 1
    xref = f"xref\n0 {n}\n".encode()
    xref += b"0000000000 65535 f \n"
    for oid in range(1, n):
        xref += f"{offsets[oid]:010d} 00000 n \n".encode()

    trailer = (
        f"trailer\n<</Size {n} /Root 1 0 R>>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()

    return body + xref + trailer


def test_synthetic_pdf_basic_extraction():
    from pdfextract import PDFExtractor
    pdf = _build_minimal_pdf("Hello PDF world")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf)
        tmp = f.name
    try:
        result = PDFExtractor(tmp).extract()
        assert result.page_count == 1
        assert "Hello" in result.full_text
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_synthetic_pdf_max_pages():
    """max_pages=0 returns all pages; max_pages=1 caps at one."""
    from pdfextract import PDFExtractor
    # Build a tiny 1-page PDF; max_pages cap is at least consistent
    pdf = _build_minimal_pdf("Word count test")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf)
        tmp = f.name
    try:
        r_all = PDFExtractor(tmp, max_pages=0).extract()
        r_one = PDFExtractor(tmp, max_pages=1).extract()
        assert r_all.page_count >= r_one.page_count
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_extract_pdf_convenience_text():
    from pdfextract import extract_pdf
    pdf = _build_minimal_pdf("Convenience function test")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf)
        tmp = f.name
    try:
        out = extract_pdf(tmp, output_format="text")
        assert isinstance(out, str)
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_extract_pdf_json_output():
    from pdfextract import extract_pdf
    pdf = _build_minimal_pdf("JSON output test")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf)
        tmp = f.name
    try:
        out = extract_pdf(tmp, output_format="json")
        payload = json.loads(out)
        assert "pages" in payload
        assert "page_count" in payload
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_extract_pdf_markdown_output():
    from pdfextract import extract_pdf
    pdf = _build_minimal_pdf("Markdown output test")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf)
        tmp = f.name
    try:
        out = extract_pdf(tmp, output_format="markdown")
        assert out.startswith("# Extracted Text:")
        assert "## Page 1" in out
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_extract_pdf_write_to_file():
    from pdfextract import extract_pdf
    pdf = _build_minimal_pdf("Write to file test")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf)
        tmp_in = f.name
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        tmp_out = f.name
    try:
        extract_pdf(tmp_in, output_format="text", output_path=tmp_out)
        content = Path(tmp_out).read_text(encoding="utf-8")
        assert isinstance(content, str)
    finally:
        Path(tmp_in).unlink(missing_ok=True)
        Path(tmp_out).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# GUI module importability
# ---------------------------------------------------------------------------

def test_gui_module_importable():
    from pdfextract import gui  # noqa: F401
    assert hasattr(gui, "run_gui")
