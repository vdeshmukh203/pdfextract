# Changelog

All notable changes to pdfextract are documented here.

## [0.2.0] - 2026-04-29

### Changed
- Reorganised into a proper `src/pdfextract/` package layout (`parser.py`,
  `extractor.py`, `schema.py`, `gui.py`) for clarity and installability.
- `pyproject.toml` updated to use the `src` layout and expose a
  `pdfextract-gui` console script entry point.
- Version bumped to 0.2.0.

### Added
- **Tkinter GUI** (`pdfextract --gui` / `pdfextract-gui`): file picker, format
  selection, max-pages spinbox, background-threaded extraction with progress
  bar, output text area, save-as dialog, and per-extraction word/page summary.
- `PDFParser` now traverses the `/Pages` object tree (catalog → pages node →
  leaf pages) for correct page ordering, falling back to a linear xref scan
  for malformed documents.
- Support for PDF 1.5+ cross-reference streams in addition to classic xref
  tables; `/Prev`-chained xref entries are merged with correct precedence.
- `/Contents` arrays (multiple content streams per page) are now concatenated
  before text extraction.
- Hex-encoded strings (`<4865...>`) in TJ operator arrays are now decoded.
- `ExtractionResult.to_json()` convenience method added.
- `src/pdfextract/__main__.py` added so `python -m pdfextract` works.
- 34 unit and integration tests covering data models, string decoders,
  stream parsing, and end-to-end extraction from programmatically generated
  minimal PDFs.

### Fixed
- `src/pdfextract/__init__.py` previously imported from non-existent
  `.extractor` and `.schema` submodules, causing `ImportError` on import.
- `_find_xref_offset` now anchors the regex to `%%EOF` first before falling
  back, avoiding false matches in binary content.
- Octal escape sequences in literal strings longer than three digits now
  consume exactly three digits per the PDF specification.

## [0.1.0] - 2024-01-15

### Added
- Initial release: pure-Python PDF parser, BT/ET text extraction, JSON/
  Markdown/text output, CLI (`pdfextract`).
