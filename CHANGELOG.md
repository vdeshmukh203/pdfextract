# Changelog

All notable changes to pdfextract are documented here.

## [0.1.0] - 2024-01-15

### Added
- Initial release of PDFExtract
- Text extraction with reading-order reconstruction for single and multi-column layouts
- Rule-based table detection with CSV and pandas DataFrame export
- Figure bounding-box detection and captioned image cropping
- Heuristic section header and metadata (title, authors, abstract) parsing
- Batch processing CLI with glob pattern input support
- Output formats: plain text, JSON (structured), and Markdown
- Optional pdfplumber and pymupdf backends selectable at runtime
- Unit tests covering extraction accuracy on sample academic PDFs
- README with installation, CLI usage, and Python API reference
