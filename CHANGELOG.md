# Changelog

All notable changes to pdfextract are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-05-05

### Added
- **PDF 1.5+ cross-reference stream support** — the xref parser now handles
  compressed xref streams (`/W` field widths + FlateDecode), in addition to
  classic xref tables.
- **`/Contents` indirect reference resolution** — page content streams are now
  correctly retrieved from their indirect-object references and arrays of
  references, fixing blank-page extraction on virtually all real-world PDFs.
- **Metadata extraction** — the PDF Info dictionary (Title, Author, Subject,
  Keywords, Creator, Producer, CreationDate, ModDate) is extracted and exposed
  via `ExtractionResult.metadata`.
- **UTF-16-BE string decoding** — strings with a `\xfe\xff` BOM are decoded
  correctly, fixing metadata extraction for many modern PDFs.
- **Tkinter GUI** (`pdfextract --gui` / `pdfextract-gui`) — browse for a PDF,
  choose format and page limit, view output in a scrollable pane, save to file.
  Extraction runs on a background thread so the UI stays responsive.
- `ExtractionResult.to_json()` convenience method.
- `ExtractionResult.to_dict()` now includes per-page `chars` field.
- `PDFExtractor` now accepts `pathlib.Path` as well as `str`.
- `extract_pdf` validates `output_format` and raises `ValueError` on bad input.
- `--gui` flag added to the CLI.
- Proper src-layout package structure (`src/pdfextract/`).
- 33 tests covering unit-level (string decoding, xref parsing, stream ops) and
  end-to-end (minimal synthetic PDFs, all output formats, error paths).

### Fixed
- **Octal escape decode bug** — `_decode_pdf_string` previously read exactly
  3 bytes unconditionally; now reads 1–3 digits as the PDF spec requires.
- **Fragile page-type detection** — replaced the string literal search for
  `/Type /Page` with a regex that tolerates arbitrary whitespace.
- **xref window too small** — increased the parse window from 4 KiB to 512 KiB
  to handle large cross-reference tables in books and report PDFs.
- `FileNotFoundError` raised (instead of a silent empty result) when the input
  path does not exist.

### Changed
- Package version bumped to 0.2.0.
- `src/pdfextract/__init__.py` re-written to export the full public API.
- `paper.md` updated to accurately describe the pure-Python implementation
  (removed references to `pdfminer.six`, `camelot`, and pandas DataFrames).

## [0.1.0] - 2024-01-15

### Added
- Initial release: pure-Python PDF parser, BT/ET text extraction, CLI,
  text/Markdown/JSON output formats.
