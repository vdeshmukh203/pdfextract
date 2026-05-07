# pdfextract

Pure-Python library and CLI for extracting text and metadata from PDF files —
no external binaries, no compiled dependencies.

## Features

- Parses PDF 1.x cross-reference tables and PDF 1.5+ cross-reference streams
- Walks the page tree to enumerate pages in document order
- Decompresses FlateDecode (zlib) content streams
- Decodes text from `BT`/`ET` operator blocks (literal and hex strings)
- Extracts document metadata from the `/Info` dictionary
- Output formats: plain text, Markdown, JSON
- Tkinter GUI (`pdfextract-gui`) for interactive use
- Graceful degradation on malformed or encrypted PDFs

## Installation

```bash
pip install pdfextract
```

Requires Python ≥ 3.8.  No third-party packages are needed.  The GUI
requires Tkinter, which ships with most Python distributions (on Debian/Ubuntu
install `python3-tk` if it is missing).

## Command-line usage

```bash
# Print extracted text to stdout
pdfextract paper.pdf

# Write Markdown to a file
pdfextract paper.pdf -f markdown -o paper.md

# Write structured JSON (per-page text + metadata)
pdfextract paper.pdf -f json -o paper.json

# Limit to the first 10 pages
pdfextract paper.pdf -p 10

# Show version
pdfextract --version

# Launch the graphical interface
pdfextract-gui
```

## Python API

```python
from pdfextract import PDFExtractor, extract_pdf

# Full control via PDFExtractor
result = PDFExtractor("paper.pdf", max_pages=0).extract()
print(result.page_count)          # number of pages found
print(result.word_count)          # total word count
print(result.metadata)            # dict of /Info keys (title, author, …)
print(result.full_text)           # concatenated page text
print(result.pages[0].text)       # text of the first page
print(result.errors)              # list of non-fatal parse warnings

# JSON output
import json
print(json.dumps(result.to_dict(), indent=2))

# Markdown output
print(result.to_markdown())

# One-liner convenience function
text = extract_pdf("paper.pdf", output_format="text")
extract_pdf("paper.pdf", output_format="json", output_path="out.json")
```

### `ExtractionResult` fields

| Field | Type | Description |
|-------|------|-------------|
| `source` | `str` | Filename of the input PDF |
| `page_count` | `int` | Number of pages extracted |
| `pages` | `List[PageResult]` | Per-page results |
| `metadata` | `Dict[str, str]` | Document metadata from `/Info` |
| `errors` | `List[str]` | Non-fatal parsing warnings |
| `full_text` | `str` (property) | All page text joined by blank lines |
| `word_count` | `int` (property) | Total word count |

### `PageResult` fields

| Field | Type | Description |
|-------|------|-------------|
| `page_number` | `int` | 1-based page number |
| `text` | `str` | Extracted text |
| `word_count` | `int` | Word count for this page |
| `char_count` | `int` | Character count for this page |

## Limitations

- Encrypted PDFs are not supported.
- Only FlateDecode compression is decompressed; other filters pass raw bytes.
- Object streams (PDF 1.5+, type-2 xref entries) are not yet supported,
  which may cause incomplete extraction from some modern PDFs.
- Text position and reading order are not reconstructed; multi-column
  layouts may produce interleaved text.
- Ligatures and non-Latin encodings may not render correctly without a
  font encoding map.

## Running tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Citation

If you use `pdfextract` in your research, please cite it using the metadata
in `CITATION.cff`.

## License

MIT — see `LICENSE`.
