"""
Tests for pdfextract.

A minimal but valid PDF is constructed in memory so that the full extraction
pipeline (xref parsing, page-tree traversal, content-stream decoding, metadata
extraction) can be exercised without shipping binary fixtures.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure the src package is importable when running from the repo root.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pdfextract
from pdfextract import (
    ExtractionResult,
    PDFExtractor,
    PDFParseError,
    PageResult,
    extract_pdf,
    __version__,
)


# ---------------------------------------------------------------------------
# Helpers: synthetic PDF construction
# ---------------------------------------------------------------------------


def _build_pdf(
    pages: list[str] | None = None,
    info: dict[str, str] | None = None,
) -> bytes:
    """
    Build a minimal but structurally valid PDF-1.4 document in memory.

    Parameters
    ----------
    pages:
        List of text strings, one per page.  Each string is embedded in a
        simple ``BT ... (text) Tj ET`` content stream.
    info:
        Optional key/value pairs to write into the /Info dictionary.
    """
    if pages is None:
        pages = ["Hello World"]

    parts: list[bytes] = []
    offsets: dict[int, int] = {}

    def _add(obj_id: int, body: bytes) -> None:
        offsets[obj_id] = sum(len(p) for p in parts)
        parts.append(b"%d 0 obj\n" % obj_id + body + b"\nendobj\n")

    parts.append(b"%PDF-1.4\n")

    # Object IDs:
    #   1 = Catalog
    #   2 = Pages
    #   3..3+N-1 = Page objects
    #   3+N..3+2N-1 = Content streams
    #   3+2N = Font (shared)
    #   3+2N+1 = Info (optional)
    n = len(pages)
    page_obj_ids = list(range(3, 3 + n))
    stream_obj_ids = list(range(3 + n, 3 + 2 * n))
    font_obj_id = 3 + 2 * n
    info_obj_id = font_obj_id + 1

    kids = b" ".join(b"%d 0 R" % oid for oid in page_obj_ids)
    _add(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    _add(2, b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % n)

    for i, (page_oid, stream_oid) in enumerate(zip(page_obj_ids, stream_obj_ids)):
        _add(
            page_oid,
            (
                b"<< /Type /Page /Parent 2 0 R "
                b"/MediaBox [0 0 612 792] "
                b"/Contents %d 0 R "
                b"/Resources << /Font << /F1 %d 0 R >> >> >>"
            )
            % (stream_oid, font_obj_id),
        )

    for text, stream_oid in zip(pages, stream_obj_ids):
        # Escape parentheses in the text
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content = (
            b"BT /F1 12 Tf 72 720 Td (" + escaped.encode("latin-1") + b") Tj ET"
        )
        _add(
            stream_oid,
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        )

    _add(
        font_obj_id,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    )

    trailer_extra = b""
    if info:
        info_body = b"<<"
        for k, v in info.items():
            escaped_v = v.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            info_body += b" /" + k.encode() + b" (" + escaped_v.encode("latin-1") + b")"
        info_body += b" >>"
        _add(info_obj_id, info_body)
        trailer_extra = b" /Info %d 0 R" % info_obj_id

    # Cross-reference table
    xref_offset = sum(len(p) for p in parts)
    max_id = info_obj_id if info else font_obj_id
    xref_lines = [b"xref\n0 %d\n" % (max_id + 1)]
    xref_lines.append(b"0000000000 65535 f \n")
    for oid in range(1, max_id + 1):
        off = offsets.get(oid, 0)
        xref_lines.append(b"%010d 00000 n \n" % off)
    parts.append(b"".join(xref_lines))

    parts.append(
        b"trailer\n<< /Size %d /Root 1 0 R%s >>\nstartxref\n%d\n%%%%EOF\n"
        % (max_id + 1, trailer_extra, xref_offset)
    )
    return b"".join(parts)


# ---------------------------------------------------------------------------
# Public API presence
# ---------------------------------------------------------------------------


def test_module_exports_public_api():
    assert hasattr(pdfextract, "extract_pdf")
    assert hasattr(pdfextract, "PDFExtractor")
    assert hasattr(pdfextract, "ExtractionResult")
    assert hasattr(pdfextract, "PageResult")
    assert hasattr(pdfextract, "PDFParseError")
    assert hasattr(pdfextract, "__version__")


def test_version_string():
    assert isinstance(__version__, str)
    parts = __version__.split(".")
    assert len(parts) >= 2
    assert all(p.isdigit() for p in parts)


# ---------------------------------------------------------------------------
# PDFParseError
# ---------------------------------------------------------------------------


def test_not_a_pdf_raises(tmp_path):
    p = tmp_path / "not.pdf"
    p.write_bytes(b"This is not a PDF")
    with pytest.raises(PDFParseError):
        PDFExtractor(str(p)).extract()


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        PDFExtractor(str(tmp_path / "missing.pdf")).extract()


def test_corrupt_xref_returns_error(tmp_path):
    p = tmp_path / "bad.pdf"
    # Valid header, no real structure.
    p.write_bytes(b"%PDF-1.4\nstartxref\n999999\n%%EOF\n")
    result = PDFExtractor(str(p)).extract()
    assert len(result.errors) > 0


# ---------------------------------------------------------------------------
# Single-page extraction
# ---------------------------------------------------------------------------


def test_single_page_text_extracted(tmp_path):
    pdf_bytes = _build_pdf(["Hello World"])
    p = tmp_path / "single.pdf"
    p.write_bytes(pdf_bytes)

    result = PDFExtractor(str(p)).extract()

    assert result.page_count == 1
    assert len(result.pages) == 1
    assert "Hello" in result.pages[0].text
    assert "World" in result.pages[0].text
    assert result.errors == []


def test_page_number_is_one_based(tmp_path):
    p = tmp_path / "t.pdf"
    p.write_bytes(_build_pdf(["Page one"]))
    result = PDFExtractor(str(p)).extract()
    assert result.pages[0].page_number == 1


def test_word_and_char_counts(tmp_path):
    p = tmp_path / "t.pdf"
    p.write_bytes(_build_pdf(["Hello World"]))
    result = PDFExtractor(str(p)).extract()
    page = result.pages[0]
    assert page.word_count == 2
    assert page.char_count == len(page.text)


# ---------------------------------------------------------------------------
# Multi-page extraction
# ---------------------------------------------------------------------------


def test_multi_page_extraction(tmp_path):
    texts = ["First page", "Second page", "Third page"]
    p = tmp_path / "multi.pdf"
    p.write_bytes(_build_pdf(texts))

    result = PDFExtractor(str(p)).extract()

    assert result.page_count == 3
    assert len(result.pages) == 3
    for i, expected in enumerate(texts):
        word = expected.split()[0]
        assert word in result.pages[i].text, (
            f"Expected '{word}' in page {i+1}, got: {result.pages[i].text!r}"
        )


def test_max_pages_limit(tmp_path):
    texts = ["Page one", "Page two", "Page three"]
    p = tmp_path / "maxp.pdf"
    p.write_bytes(_build_pdf(texts))

    result = PDFExtractor(str(p), max_pages=2).extract()

    assert result.page_count == 2


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_metadata_extracted(tmp_path):
    p = tmp_path / "meta.pdf"
    p.write_bytes(_build_pdf(["Content"], info={"Title": "My Paper", "Author": "Jane Doe"}))

    result = PDFExtractor(str(p)).extract()

    assert result.metadata.get("title") == "My Paper"
    assert result.metadata.get("author") == "Jane Doe"


def test_no_metadata_returns_empty_dict(tmp_path):
    p = tmp_path / "nometa.pdf"
    p.write_bytes(_build_pdf(["Content"]))
    result = PDFExtractor(str(p)).extract()
    assert isinstance(result.metadata, dict)


# ---------------------------------------------------------------------------
# ExtractionResult helpers
# ---------------------------------------------------------------------------


def test_full_text_joins_pages(tmp_path):
    p = tmp_path / "ft.pdf"
    p.write_bytes(_build_pdf(["Alpha", "Beta"]))
    result = PDFExtractor(str(p)).extract()
    full = result.full_text
    assert "Alpha" in full
    assert "Beta" in full


def test_word_count_sums_pages(tmp_path):
    p = tmp_path / "wc.pdf"
    p.write_bytes(_build_pdf(["one two", "three four five"]))
    result = PDFExtractor(str(p)).extract()
    assert result.word_count == 5


def test_to_dict_structure(tmp_path):
    p = tmp_path / "d.pdf"
    p.write_bytes(_build_pdf(["Hello"]))
    d = PDFExtractor(str(p)).extract().to_dict()
    assert "source" in d
    assert "page_count" in d
    assert "word_count" in d
    assert "metadata" in d
    assert "errors" in d
    assert "pages" in d
    assert d["pages"][0]["page"] == 1
    assert "word_count" in d["pages"][0]
    assert "char_count" in d["pages"][0]


def test_to_markdown_contains_headings(tmp_path):
    p = tmp_path / "md.pdf"
    p.write_bytes(_build_pdf(["Test content"]))
    md = PDFExtractor(str(p)).extract().to_markdown()
    assert "# Extracted Text:" in md
    assert "## Page 1" in md


# ---------------------------------------------------------------------------
# extract_pdf convenience function
# ---------------------------------------------------------------------------


def test_extract_pdf_text_format(tmp_path):
    p = tmp_path / "ep.pdf"
    p.write_bytes(_build_pdf(["Convenience text"]))
    out = extract_pdf(str(p), output_format="text")
    assert isinstance(out, str)
    assert "Convenience" in out


def test_extract_pdf_json_format(tmp_path):
    p = tmp_path / "epj.pdf"
    p.write_bytes(_build_pdf(["JSON text"]))
    out = extract_pdf(str(p), output_format="json")
    data = json.loads(out)
    assert "pages" in data


def test_extract_pdf_markdown_format(tmp_path):
    p = tmp_path / "epm.pdf"
    p.write_bytes(_build_pdf(["Markdown text"]))
    out = extract_pdf(str(p), output_format="markdown")
    assert "## Page 1" in out


def test_extract_pdf_writes_file(tmp_path):
    p = tmp_path / "write.pdf"
    p.write_bytes(_build_pdf(["Write test"]))
    out_path = tmp_path / "output.txt"
    extract_pdf(str(p), output_path=str(out_path))
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "Write" in content


# ---------------------------------------------------------------------------
# PageResult
# ---------------------------------------------------------------------------


def test_page_result_post_init():
    pr = PageResult(page_number=1, text="one two three")
    assert pr.word_count == 3
    assert pr.char_count == 13


def test_page_result_empty_text():
    pr = PageResult(page_number=2, text="")
    assert pr.word_count == 0
    assert pr.char_count == 0
