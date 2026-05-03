# Changelog

All notable changes to pdfextract are documented here.

## [0.2.0] - 2026-05-03

### Added
- Browser-based GUI (`pdfextract --gui` / `pdfextract-gui`) built on the
  standard-library `http.server`; no additional dependencies required.
- `ExtractionResult.to_json()` method for explicit JSON serialisation.
- `ExtractionResult.to_markdown()` now includes a `## Warnings` section when
  parse errors were collected.
- `__main__.py` entry point enabling `python -m pdfextract`.
- `pdfextract-gui` console script entry point.
- `--port` CLI option for the GUI server.
- `--version` CLI flag.
- Proper `src`-layout packaging (`src/pdfextract/`).

### Fixed
- **Double-counted text**: strings inside `[…] TJ` array arguments were
  emitted twice by the original `_extract_text_from_stream` implementation.
  Text is now extracted once per BT/ET block via a single regex pass.
- **Wrong page order**: the extractor previously iterated objects by object ID,
  which does not match document reading order.  The parser now traverses the
  PDF Pages tree (`/Type /Pages` → `/Kids`) to obtain page object IDs in the
  correct sequence, with a fallback to object-ID scan for malformed documents.
- **No xref chain following**: incremental PDF updates record earlier xref
  tables via `/Prev` pointers.  The new `load_xref` function follows the full
  `/Prev` chain so that all object offsets are resolved.
- **No xref stream support**: PDF 1.5+ documents use binary cross-reference
  streams instead of xref tables.  The parser now handles both formats.
- **No metadata extraction**: `ExtractionResult.metadata` was always empty.
  The `parse_metadata` function now resolves the `Info` dictionary and
  populates standard fields (Title, Author, Subject, etc.).
- **Octal escape handling**: `_decode_pdf_string` now correctly handles 1–3
  octal digit sequences and masks values to 0–255.
- **Broken `src/pdfextract/` package**: the `__init__.py` imported from
  non-existent `.extractor` and `.schema` modules.  All modules are now
  implemented and the package imports correctly.
- Removed root-level `pdfextract.py` that shadowed the package.
- Replaced deprecated `cgi` module in GUI with query-parameter + raw-body
  approach compatible with Python 3.13.

## [0.1.0] - 2024-01-15

### Added
- Initial release of pdfextract
- Pure-Python PDF text extraction
- CLI with `--format` and `--max-pages` options
- Output formats: plain text, JSON, and Markdown
