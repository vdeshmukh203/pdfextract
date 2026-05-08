# Changelog

All notable changes to pdfextract are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-05-08

### Added
- PDF 1.5+ cross-reference stream parsing (`/Type /XRef`) with FlateDecode
  decompression and `/W` field-width decoding
- `/Prev` pointer chaining to handle incremental-update PDFs
- Linear byte-scan fallback for structurally incomplete cross-reference tables
- Proper page-tree traversal via the document catalog (`/Root` → `/Pages`)
  rather than heuristic scanning
- Document metadata extraction from the PDF Info dictionary
  (Title, Author, Subject, Keywords, Creator, Producer)
- Tkinter GUI (`pdfextract-gui` entry point) for interactive extraction
- `pdfextract.gui` module with `launch()` function
- Structured package layout under `src/pdfextract/` with separate modules:
  `parser`, `schema`, `extractor`, `cli`, `gui`
- `ExtractionResult.to_json()` helper method
- `[tool.pytest.ini_options]` with `pythonpath = ["src"]` for running tests
  without installing the package
- 49 unit and integration tests covering the parser, data model, CLI, and a
  synthetically generated minimal PDF

### Changed
- `pyproject.toml` updated to use the `src/` package layout
  (`tool.setuptools.packages.find`)
- CLI entry point changed from `pdfextract:_cli` to `pdfextract.cli:main`
- Version bumped to `0.2.0`
- `pdfextract.py` root file updated with improved single-file standalone
  implementation (all bug fixes backported)

### Fixed
- Octal escape decoding in PDF literal strings now correctly handles 1–3 digit
  sequences instead of always consuming exactly 3 digits
- `OverflowError` no longer raised for octal values outside the Unicode range
- `src/pdfextract/__init__.py` now imports from existing modules instead of
  referencing non-existent submodules
- Page ordering now follows the document page tree instead of xref object ID
  order
- Content stream referenced via an indirect object (most real PDFs) is now
  correctly resolved

## [0.1.0] - 2026-04-23

### Added
- Initial release
- Pure-Python PDF parser: classic cross-reference table parsing, FlateDecode
  stream decompression, BT/ET text extraction
- `PDFExtractor` class with `extract()` method
- `ExtractionResult` and `PageResult` dataclasses
- `extract_pdf()` convenience function
- Output formats: plain text, Markdown, JSON
- Command-line interface (`pdfextract` entry point)
- MIT licence
