# Changelog

All notable changes to pdfextract are documented here.

## [0.2.0] - 2026-04-28

### Added
- Proper `src` layout: code split into `_schema`, `_parser`, `_text`, `_extractor`, `_cli` submodules
- Tkinter GUI (`pdfextract-gui` entry point; also `pdfextract --gui`)
- `python -m pdfextract` support via `__main__.py`
- `ExtractionResult.to_json()` convenience method
- Metadata extraction from PDF `/Info` dictionary (Title, Author, Subject, etc.)
- 46-test suite covering string decoding, xref parsing, page detection, data classes, and full round-trip extraction
- `--version` CLI flag

### Fixed
- **TJ array double-counting**: strings inside `[…] TJ` arrays were previously included twice in output; now handled by dedicated `TJ`-specific pass only
- **Octal escape decode**: `int(bytes, 8)` fails in Python 3; corrected to decode bytes to latin-1 string first; also now supports 1–3 digit sequences per ISO 32000-1
- **xref buffer truncation**: xref table read window increased from 4096 B to 512 KB
- **Page object detection**: now uses `re.compile(rb"/Type\s*/Page\b")` to match both `/Type /Page` and `/Type/Page` (no space)
- **Content stream lookup**: page objects reference content via `/Contents N 0 R`; extractor now follows this reference instead of looking for an inline stream in the page dictionary
- **Cross-reference stream detection**: PDF 1.5+ xref streams are now detected and reported with a clear error message rather than silently failing
- **`src/pdfextract/__init__.py`**: previously imported from non-existent `.extractor` and `.schema` modules; corrected to match actual package structure

### Changed
- `pyproject.toml` updated to use `[tool.setuptools.packages.find]` `where = ["src"]` layout
- `paper.md` rewritten to accurately describe the pure-Python implementation (removed incorrect references to `pdfminer.six` and `camelot`)
- `paper.bib` trimmed to only the three references cited in `paper.md`
- `CITATION.cff` updated to v0.2.0 with ORCID

## [0.1.0] - 2024-01-15

### Added
- Initial release of pdfextract
- Pure-Python PDF parser (xref table, indirect objects, FlateDecode streams)
- BT/ET content-stream text extraction
- Output formats: plain text, JSON, Markdown
- CLI entry point `pdfextract`
