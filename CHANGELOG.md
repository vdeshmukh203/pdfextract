# Changelog

All notable changes to pdfextract are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `src`-layout package structure replacing the single-file module
- `schema.py` — `PageResult` and `ExtractionResult` dataclasses with `to_json()`, `to_markdown()`, and `to_dict()` serialisation
- `extractor.py` — refactored pure-Python PDF parser with improved xref reading (up to 512 KB window), `/Contents` indirect-reference resolution, and hex-string decoding
- `cli.py` — argument parser with `--format`, `--output`, `--max-pages` flags and stderr warnings for extraction errors
- `gui.py` — Tkinter desktop GUI with file browser, format selector, scrollable text preview, and save dialog; extraction runs on a background thread to keep the UI responsive
- Document metadata extraction from the PDF Info dictionary
- 30-test pytest suite covering public API, data model, decode helpers, xref parsing, error handling, and a synthetic end-to-end PDF test
- `pdfextract-gui` console script entry point

### Fixed
- `src/pdfextract/__init__.py` previously imported from non-existent `extractor` and `schema` modules, causing `ImportError` on import
- `_decode_pdf_string` octal-escape handling now correctly advances the index for 1–3 digit sequences
- xref table reader was limited to 4 096 bytes, silently truncating large PDFs
- Page detection regex now uses word-boundary anchors to distinguish `/Type /Page` from `/Type /Pages`
- `_decode_flate` falls back to raw-deflate (`wbits=-15`) before giving up, improving compatibility with non-standard streams

### Changed
- `pyproject.toml` updated from `py-modules = ["pdfextract"]` to `packages.find` pointing at `src/`; entry point updated to `pdfextract.cli:main`
- `paper.md` rewritten to accurately describe the pure-Python implementation (removed erroneous references to `pdfminer.six` and `camelot`)
- `README.md` expanded with installation instructions, API reference, CLI usage, GUI instructions, output format table, and known limitations

## [0.1.0] - 2024-01-15

### Added
- Initial release: single-file `pdfextract.py` with `PDFExtractor`, `PDFParseError`, `PageResult`, `ExtractionResult`, and `extract_pdf` convenience function
- FlateDecode stream decompression via `zlib`
- BT/ET text block parsing with literal string and TJ array support
- Plain text, Markdown, and JSON output formats
- Argument-parser CLI
