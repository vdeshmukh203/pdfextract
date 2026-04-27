"""
Functional tests for pdfextract.

Tests cover string decoding, stream decompression, xref table parsing,
text extraction from synthesised content streams, and end-to-end extraction
on minimal valid PDFs constructed in memory.
"""
import io
import json
import sys
import tempfile
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import pdfextract
from pdfextract import (
    ExtractionResult,
    PDFExtractor,
    PDFParseError,
    PageResult,
    extract_pdf,
    _decode_pdf_string,
    _decode_hex_string,
    _decode_flate,
    _extract_text_from_stream,
    _parse_xref_table,
    _find_xref_offset,
)


# ---------------------------------------------------------------------------
# Helpers — minimal in-memory PDF construction
# ---------------------------------------------------------------------------

def _make_pdf(text: str = "Hello World", info: dict | None = None) -> bytes:
    """
    Build a minimal single-page PDF containing *text* and optional metadata.

    The returned bytes constitute a spec-compliant PDF 1.4 document that
    can be round-tripped through PDFExtractor.
    """
    # Escape the text for a PDF literal string
    escaped = (
        text
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )
    content = ("BT /F1 12 Tf 72 720 Td (%s) Tj ET" % escaped).encode()
    length = len(content)

    # Optional Info dictionary (obj 5)
    info_obj = b""
    info_ref = b""
    if info:
        lines = ["5 0 obj\n<<"]
        for k, v in info.items():
            # Escape value as a PDF literal string
            v_esc = v.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            lines.append("/%s (%s)" % (k, v_esc))
        lines.append(">>\nendobj\n")
        info_obj = "\n".join(lines).encode()
        info_ref = b"/Info 5 0 R"

    obj1 = b"1 0 obj\n<</Type/Catalog/Pages 2 0 R>>\nendobj\n"
    obj2 = b"2 0 obj\n<</Type/Pages/Kids[3 0 R]/Count 1>>\nendobj\n"
    obj3 = b"3 0 obj\n<</Type/Page/Parent 2 0 R/Contents 4 0 R>>\nendobj\n"
    obj4 = (
        b"4 0 obj\n<</Length " + str(length).encode() + b">>\nstream\n"
        + content
        + b"\nendstream\nendobj\n"
    )

    header = b"%PDF-1.4\n"
    body = b""
    offsets: dict[int, int] = {}
    obj_list = [(1, obj1), (2, obj2), (3, obj3), (4, obj4)]
    if info_obj:
        obj_list.append((5, info_obj))

    for oid, obj in obj_list:
        offsets[oid] = len(header) + len(body)
        body += obj

    xref_pos = len(header) + len(body)
    n_objs = len(obj_list) + 1  # +1 for the free entry (obj 0)
    xref = b"xref\n0 %d\n" % n_objs
    xref += b"0000000000 65535 f\r\n"
    for i in range(1, n_objs):
        xref += ("%010d 00000 n\r\n" % offsets[i]).encode()

    size = n_objs
    trailer = (
        b"trailer\n<</Size " + str(size).encode() + b"/Root 1 0 R"
        + (b" " + info_ref if info_ref else b"")
        + b">>\n"
    )
    startxref = ("startxref\n%d\n%%%%EOF\n" % xref_pos).encode()

    return header + body + xref + trailer + startxref


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

def test_public_symbols():
    assert hasattr(pdfextract, "extract_pdf")
    assert hasattr(pdfextract, "PDFExtractor")
    assert hasattr(pdfextract, "PDFParseError")
    assert hasattr(pdfextract, "PageResult")
    assert hasattr(pdfextract, "ExtractionResult")


# ---------------------------------------------------------------------------
# _decode_pdf_string
# ---------------------------------------------------------------------------

def test_decode_simple_ascii():
    assert _decode_pdf_string(b"Hello") == "Hello"


def test_decode_octal_escape():
    # \110 = 0x48 = 'H', \145 = 'e', \154 = 'l', \154 = 'l', \157 = 'o'
    assert _decode_pdf_string(b"\\110\\145\\154\\154\\157") == "Hello"


def test_decode_standard_escapes():
    assert _decode_pdf_string(b"line1\\nline2") == "line1\nline2"
    assert _decode_pdf_string(b"tab\\there") == "tab\there"
    assert _decode_pdf_string(b"\\(paren\\)") == "(paren)"


def test_decode_utf16_bom():
    # BOM + UTF-16BE encoding of "Hi"
    payload = b"\xfe\xff\x00H\x00i"
    assert _decode_pdf_string(payload) == "Hi"


def test_decode_backslash_at_eof():
    # Trailing backslash should not crash
    result = _decode_pdf_string(b"abc\\")
    assert result.startswith("abc")


# ---------------------------------------------------------------------------
# _decode_hex_string
# ---------------------------------------------------------------------------

def test_hex_decode_basic():
    assert _decode_hex_string(b"48656c6c6f") == "Hello"


def test_hex_decode_odd_length():
    # Odd-length hex — trailing nibble treated as 0
    result = _decode_hex_string(b"4")
    assert isinstance(result, str)


def test_hex_decode_whitespace_ignored():
    assert _decode_hex_string(b"48 65 6c 6c 6f") == "Hello"


def test_hex_decode_utf16():
    # BOM + "Hi" in UTF-16BE: feff 0048 0069 = 6 bytes = 12 hex chars
    assert _decode_hex_string(b"feff00480069") == "Hi"


# ---------------------------------------------------------------------------
# _decode_flate
# ---------------------------------------------------------------------------

def test_decode_flate_valid():
    raw = zlib.compress(b"hello world")
    assert _decode_flate(raw) == b"hello world"


def test_decode_flate_raw_deflate():
    # zlib.compress(data)[2:-4] = raw deflate stream
    raw = zlib.compress(b"hello")[2:-4]
    assert _decode_flate(raw) == b"hello"


def test_decode_flate_garbage():
    # Should return the original bytes unchanged rather than raise
    result = _decode_flate(b"not compressed data")
    assert isinstance(result, bytes)


# ---------------------------------------------------------------------------
# _extract_text_from_stream
# ---------------------------------------------------------------------------

def test_extract_tj():
    stream = b"BT (Hello World) Tj ET"
    assert "Hello" in _extract_text_from_stream(stream)
    assert "World" in _extract_text_from_stream(stream)


def test_extract_tj_array():
    stream = b"BT [(Hello) -200 ( World)] TJ ET"
    result = _extract_text_from_stream(stream)
    assert "Hello" in result
    assert "World" in result


def test_extract_hex_string():
    # <48656c6c6f> = "Hello"
    stream = b"BT <48656c6c6f> Tj ET"
    assert "Hello" in _extract_text_from_stream(stream)


def test_no_double_counting():
    # Text inside a TJ array must appear exactly once
    stream = b"BT [(Alpha) -100 (Beta)] TJ ET"
    result = _extract_text_from_stream(stream)
    assert result.count("Alpha") == 1
    assert result.count("Beta") == 1


def test_extract_multiple_bt_blocks():
    stream = b"BT (Page one) Tj ET some garbage BT (Page two) Tj ET"
    result = _extract_text_from_stream(stream)
    assert "Page one" in result
    assert "Page two" in result


def test_extract_quote_operator():
    # ' operator: move to next line and show string
    stream = b"BT (first line) ' ET"
    result = _extract_text_from_stream(stream)
    assert "first line" in result


def test_extract_no_text():
    assert _extract_text_from_stream(b"") == ""
    assert _extract_text_from_stream(b"q Q q Q") == ""


# ---------------------------------------------------------------------------
# _parse_xref_table
# ---------------------------------------------------------------------------

def test_parse_xref_table():
    # Hand-crafted xref block
    xref_bytes = (
        b"xref\n"
        b"0 3\n"
        b"0000000000 65535 f\r\n"
        b"0000000009 00000 n\r\n"
        b"0000000058 00000 n\r\n"
    )
    result = _parse_xref_table(xref_bytes, 0)
    assert result[1] == 9
    assert result[2] == 58
    assert 0 not in result  # free entry excluded


def test_find_xref_offset():
    data = b"%" + b"PDF-1.4\n" + b"some content\n" + b"startxref\n42\n%%EOF\n"
    assert _find_xref_offset(data) == 42


def test_find_xref_offset_missing():
    with pytest.raises(PDFParseError, match="startxref"):
        _find_xref_offset(b"not a pdf")


# ---------------------------------------------------------------------------
# PageResult and ExtractionResult
# ---------------------------------------------------------------------------

def test_page_result_counts():
    p = PageResult(page_number=1, text="hello world foo")
    assert p.word_count == 3
    assert p.char_count == 15


def test_page_result_empty():
    p = PageResult(page_number=1, text="")
    assert p.word_count == 0
    assert p.char_count == 0


def test_extraction_result_full_text():
    r = ExtractionResult(source="t.pdf", page_count=2)
    r.pages = [PageResult(1, "foo"), PageResult(2, "bar")]
    assert "foo" in r.full_text
    assert "bar" in r.full_text


def test_extraction_result_word_count():
    r = ExtractionResult(source="t.pdf", page_count=1)
    r.pages = [PageResult(1, "one two three")]
    assert r.word_count == 3


def test_extraction_result_to_dict():
    r = ExtractionResult(source="t.pdf", page_count=1)
    r.pages = [PageResult(1, "hello")]
    d = r.to_dict()
    assert d["source"] == "t.pdf"
    assert d["page_count"] == 1
    assert d["pages"][0]["text"] == "hello"
    assert d["word_count"] == 1


def test_extraction_result_to_markdown():
    r = ExtractionResult(source="t.pdf", page_count=1)
    r.pages = [PageResult(1, "hello")]
    md = r.to_markdown()
    assert "# Extracted Text" in md
    assert "Page 1" in md
    assert "hello" in md


def test_extraction_result_to_markdown_with_metadata():
    r = ExtractionResult(source="t.pdf", page_count=1)
    r.pages = [PageResult(1, "body")]
    r.metadata = {"title": "My Paper", "author": "J. Doe"}
    md = r.to_markdown()
    assert "My Paper" in md
    assert "J. Doe" in md


# ---------------------------------------------------------------------------
# End-to-end extraction on synthetic PDFs
# ---------------------------------------------------------------------------

def test_end_to_end_basic(tmp_path):
    pdf_bytes = _make_pdf("Hello World")
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_bytes(pdf_bytes)

    result = PDFExtractor(str(pdf_file)).extract()
    assert result.page_count == 1
    assert "Hello" in result.full_text
    assert "World" in result.full_text
    assert result.errors == []


def test_end_to_end_multiword(tmp_path):
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_bytes(_make_pdf("The quick brown fox"))
    result = PDFExtractor(str(pdf_file)).extract()
    assert result.word_count >= 4


def test_end_to_end_max_pages(tmp_path):
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_bytes(_make_pdf("Only one page anyway"))
    result = PDFExtractor(str(pdf_file), max_pages=1).extract()
    assert result.page_count == 1


def test_end_to_end_metadata(tmp_path):
    pdf_file = tmp_path / "meta.pdf"
    pdf_file.write_bytes(_make_pdf("body", info={"Title": "My Paper", "Author": "A. Author"}))
    result = PDFExtractor(str(pdf_file)).extract()
    assert result.metadata.get("title") == "My Paper"
    assert result.metadata.get("author") == "A. Author"


def test_end_to_end_not_a_pdf(tmp_path):
    not_pdf = tmp_path / "fake.pdf"
    not_pdf.write_bytes(b"this is not a pdf file")
    with pytest.raises(PDFParseError):
        PDFExtractor(str(not_pdf)).extract()


def test_end_to_end_file_not_found():
    with pytest.raises(FileNotFoundError):
        PDFExtractor("/nonexistent/path/file.pdf").extract()


# ---------------------------------------------------------------------------
# extract_pdf convenience function
# ---------------------------------------------------------------------------

def test_extract_pdf_text(tmp_path):
    pdf_file = tmp_path / "t.pdf"
    pdf_file.write_bytes(_make_pdf("Science is great"))
    out = extract_pdf(str(pdf_file), output_format="text")
    assert "Science" in out


def test_extract_pdf_json(tmp_path):
    pdf_file = tmp_path / "t.pdf"
    pdf_file.write_bytes(_make_pdf("JSON test"))
    out = extract_pdf(str(pdf_file), output_format="json")
    data = json.loads(out)
    assert "page_count" in data
    assert "pages" in data


def test_extract_pdf_markdown(tmp_path):
    pdf_file = tmp_path / "t.pdf"
    pdf_file.write_bytes(_make_pdf("Markdown test"))
    out = extract_pdf(str(pdf_file), output_format="markdown")
    assert out.startswith("#")
    assert "Page 1" in out


def test_extract_pdf_writes_file(tmp_path):
    pdf_file = tmp_path / "t.pdf"
    out_file = tmp_path / "out.txt"
    pdf_file.write_bytes(_make_pdf("Write test"))
    extract_pdf(str(pdf_file), output_path=str(out_file))
    assert out_file.exists()
    assert "Write" in out_file.read_text(encoding="utf-8")
