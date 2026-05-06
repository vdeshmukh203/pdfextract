# Changelog

All notable changes to pdfextract are documented here.

## [0.2.0] - 2026-05-06

### Added
- Replaced the hand-rolled pure-Python PDF parser with `pdfminer.six` for
  layout-aware, reading-order-preserving text extraction
- `ExtractionResult.to_json()` method for direct JSON serialisation
- `ExtractionResult` now records `char_count` per page alongside `word_count`
- `ExtractionResult.to_markdown()` now includes a **Warnings** section when
  non-fatal extraction errors were encountered
- Graphical user interface (`pdfextract.gui`, entry-point `pdfextract-gui`)
  built with `tkinter`; threaded extraction keeps the UI responsive
- `PDFExtractor` now accepts a `pathlib.Path` argument in addition to `str`
- CLI: `--gui` flag launches the GUI from the command line; invoking
  `pdfextract` without a positional argument also opens the GUI
- CLI: `--version` flag
- `project.urls` and `project.gui-scripts` added to `pyproject.toml`
- Comprehensive pytest test suite covering data models, extractor, CLI, and
  the `extract_pdf` convenience function

### Changed
- Package restructured to `src/` layout (`src/pdfextract/`)
- Version bumped to `0.2.0`
- `pyproject.toml`: `pdfminer.six>=20220319` added as a runtime dependency
- `paper.md` updated to accurately describe the implemented features and
  cite the correct dependencies

### Removed
- Root-level `pdfextract.py` single-file module (superseded by the package)

## [0.1.0] - 2026-04-23

### Added
- Initial release
- Pure-Python PDF text extraction (cross-reference table parser, FlateDecode
  decompression, BT/ET content stream tokeniser)
- Output formats: plain text, Markdown, JSON
- CLI entry point (`pdfextract`)
- Basic pytest tests
