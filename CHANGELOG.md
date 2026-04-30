# Changelog

All notable changes to pdfextract are documented here.
Versions follow [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-04-30

### Added
- `src/` package layout with dedicated sub-modules:
  `schema.py`, `extractor.py`, `cli.py`, `gui.py`
- Tkinter-based graphical interface (`pdfextract-gui` command)
  with threaded extraction, format selector, page-limit spinner,
  progress bar, and save-output dialog
- Cross-reference stream (PDF 1.5+) parser (`_parse_xref_stream`)
- `/Prev` chain traversal for incremental-update PDFs
- Document-order page extraction via proper `/Pages` tree traversal
  (`_collect_page_ids`, `_find_pages_root`); no longer relies on
  heuristic object-ID ordering
- Metadata extraction from the `/Info` dictionary
  (Title, Author, Subject, Keywords, Creator, Producer, CreationDate)
- `ExtractionResult.to_json()` method
- `ExtractionResult.to_markdown()` now includes a **Warnings** section
  when non-fatal errors occurred
- `chars` field in the JSON `pages` array
- TJ kerning-gap heuristic: negative offsets < −100 text-space units
  are mapped to a word space
- Support for multiple `/Contents` streams per page (array form)
- `PDFExtractor` now raises `PDFParseError` for missing files
- 61-test test suite covering data model, low-level utilities,
  error handling, and an end-to-end smoke test with a
  synthetically constructed minimal PDF
- `pyproject.toml` now includes `[tool.pytest.ini_options]`
  with `pythonpath = ["src"]` for zero-config test discovery

### Fixed
- `_parse_xref_table`: raised the read window from 4 096 B to 1 MiB,
  preventing truncation of large xref tables
- `_find_startxref`: now searches the last 2 048 bytes (was 1 024)
- `_decode_pdf_string`: octal escape now strictly matches 1–3 octal
  digits to avoid `int(..., 8)` failures on non-octal characters
- `_extract_text_from_stream`: BT/ET regex uses word boundaries
  (`\bBT\b … \bET\b`) to prevent false matches on operator names
- Page order is now the PDF document order, not xref object-ID order

### Changed
- Script entry point changed from `pdfextract:_cli` (root module)
  to `pdfextract.cli:main` (package sub-module)
- `pyproject.toml` switched from `py-modules` to `packages.find`
  with `where = ["src"]`
- Version bumped from 0.1.0 to 0.2.0

## [0.1.0] - 2026-04-23

### Added
- Initial release: pure-Python PDF text extractor
- Classic xref table parsing
- FlateDecode (zlib) stream decompression
- `Tj` / `TJ` operator handling; literal and hex string decoding
- `PageResult` and `ExtractionResult` data model
- `extract_pdf()` convenience function
- CLI (`pdfextract`)
- Output formats: plain text, Markdown, JSON
