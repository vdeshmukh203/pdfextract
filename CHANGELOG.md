# Changelog

All notable changes to pdfextract are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Tkinter-based graphical user interface (`pdfextract_gui.py`); launch with
  `pdfextract gui` or `python pdfextract_gui.py`.  Runs extraction in a
  background thread to keep the UI responsive.
- `batch_extract()` API function and `pdfextract batch <glob>` CLI subcommand
  for processing multiple PDFs in a single call.
- `pdfextract extract` CLI subcommand (single-file, explicit); legacy
  positional invocation remains supported.
- `--version` flag to the CLI (`pdfextract --version`).
- `pdfextract-gui` console script entry point in `pyproject.toml`.

### Changed
- **`_decode_pdf_string`**: fixed octal escape parsing to correctly handle
  1–3 digit sequences without overreading; now uses a proper scan loop
  instead of a fixed 3-byte slice.
- **`_get_page_streams`**: refactored into `_get_page_streams` +
  `_resolve_page_stream`; the resolver now follows the page object's
  `/Contents` key (single indirect reference *and* array form) to load the
  actual content stream object, fixing extraction on all standard PDFs.
- **xref buffer**: enlarged from 4 096 to 1 048 576 bytes (1 MiB) to prevent
  truncation of large cross-reference tables.
- **Incremental update support**: `_collect_xref` now walks the full `/Prev`
  chain and merges all revisions, giving correct results on updated PDFs.
- **Page detection regex**: changed from a fragile `b"/Type /Page" in body`
  substring check to the compiled regex `/Type\s*/Page\b`, which is robust to
  varying whitespace.
- **Object parser window**: enlarged from 65 536 to 131 072 bytes (128 KiB).
- **`_extract_stream`**: uses `\bendstream\b` word-boundary pattern to avoid
  false matches inside stream data.
- **`src/pdfextract/__init__.py`**: fixed broken imports (previously referenced
  non-existent `.extractor` and `.schema` sub-modules); now re-exports the
  full public API from the top-level `pdfextract` module.
- **`pyproject.toml`**: added `pdfextract_gui` to `py-modules`; added
  `pdfextract-gui` console script; added `dev` optional dependency group;
  added `[tool.pytest.ini_options]` section; listed Python 3.8–3.12
  classifiers.

### Removed
- Unused `_TEXT_OPS` compiled regex (dead code).

## [0.1.0] - 2025-01-01

### Added
- Initial release: pure-Python PDF cross-reference table parser.
- FlateDecode (zlib) stream decompression with raw-deflate fallback.
- BT/ET text block extraction supporting `Tj` and `TJ` operators.
- PDF `Info` dictionary metadata extraction (Title, Author, Subject, etc.).
- `ExtractionResult` and `PageResult` data classes with `to_dict()` and
  `to_markdown()` serialisation.
- `extract_pdf()` convenience function.
- CLI (`pdfextract`) with `--format` and `--max-pages` options.
- MIT licence.
