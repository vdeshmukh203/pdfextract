# Changelog

All notable changes to pdfextract are documented here.

## [0.2.0] - 2026-05-07

### Fixed
- **Critical**: `PDFExtractor.extract()` previously yielded zero pages for
  every PDF because page dictionary objects do not embed content streams
  directly; the extractor now follows the `/Contents` indirect reference(s)
  to the actual stream objects.
- Cross-reference table parser now reads up to the `trailer` keyword instead
  of an arbitrary fixed window, preventing missed entries in large tables.
- Out-of-bounds `startxref` offsets now raise `PDFParseError` rather than
  silently returning an empty result.
- Octal escape decoding in PDF literal strings now correctly handles 1- and
  2-digit octal sequences.
- `src/pdfextract/__init__.py` previously imported non-existent submodules
  (`.extractor`, `.schema`); the package is now structured correctly.

### Added
- Document metadata extraction from the `/Info` dictionary (title, author,
  subject, creator, producer, keywords, creation date).
- PDF 1.5+ cross-reference stream parsing (`_parse_xref_stream`), supporting
  type-1 (uncompressed) entries.
- Hex string decoding (`<AABBCC>`) in content streams.
- Tkinter GUI (`pdfextract-gui` entry point, `src/pdfextract/gui.py`).
- `--version` flag on the CLI.
- `FileNotFoundError` raised (instead of a raw `PDFParseError`) when the
  input path does not exist.
- Comprehensive test suite with a synthetic in-memory PDF builder covering
  single-page, multi-page, metadata, max-pages, output-format, and error
  handling scenarios.

### Changed
- Package migrated to src layout (`src/pdfextract/`).
- `pyproject.toml` updated to use `setuptools.packages.find` with `src/`.
- Version bumped to `0.2.0`.
- `paper.md` rewritten to accurately describe the pure-Python implementation
  (removed false references to pdfminer.six, camelot, figure extraction, and
  multi-column reading-order reconstruction).

## [0.1.0] - 2024-01-15

### Added
- Initial release with basic pure-Python PDF parser, BT/ET text extraction,
  FlateDecode decompression, and text/markdown/json output formats.
