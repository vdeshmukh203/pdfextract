# pdfextract

[![CI](https://github.com/vdeshmukh203/pdfextract/actions/workflows/ci.yml/badge.svg)](https://github.com/vdeshmukh203/pdfextract/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org)

Pure-Python structured text and metadata extractor for PDF files — no external
binaries, no system dependencies, no compiled extensions.

---

## Features

- Parse PDF cross-reference tables and indirect objects
- Decode FlateDecode (zlib) content streams
- Extract visible text from `Tj` (single-string) and `TJ` (array) operators
- Correct handling of backslash escapes and 1–3 digit octal sequences
- Extract document metadata from the `/Info` dictionary (Title, Author, …)
- Output as **plain text**, **Markdown**, or **JSON**
- Tkinter **GUI** with file browser, format selector, and save dialog
- Graceful degradation on malformed / encrypted / PDF 1.5+ cross-reference-stream PDFs

---

## Installation

```bash
pip install pdfextract
```

Or install from source:

```bash
git clone https://github.com/vdeshmukh203/pdfextract
cd pdfextract
pip install -e .
```

Requires Python ≥ 3.8 and no third-party packages.

---

## Quick start

### Python API

```python
from pdfextract import extract_pdf, PDFExtractor

# One-shot helper — returns a string
text = extract_pdf("paper.pdf")

# Full result object
result = PDFExtractor("paper.pdf").extract()
print(f"{result.page_count} pages, {result.word_count} words")
print(result.metadata)          # {"Title": "...", "Author": "..."}

# Serialise
markdown = result.to_markdown()
data     = result.to_dict()     # plain dict
json_str = result.to_json()     # pretty-printed JSON string

# Per-page access
for page in result.pages:
    print(f"Page {page.page_number}: {page.word_count} words")
    print(page.text)
```

### Command-line interface

```bash
# Plain text to stdout
pdfextract paper.pdf

# Markdown to file
pdfextract paper.pdf -f markdown -o paper.md

# JSON, first 10 pages only
pdfextract paper.pdf -f json -p 10 -o paper.json

# Launch the GUI
pdfextract --gui
# or
pdfextract-gui
```

```
usage: pdfextract [-h] [-o OUTPUT] [-f {text,markdown,json}] [-p N] [--gui] [--version]
                  [input]

Extract structured text and metadata from PDF files.

positional arguments:
  input                 Path to input PDF file.

optional arguments:
  -o OUTPUT             Output file path.
  -f {text,markdown,json}
                        Output format (default: text).
  -p N                  Stop after N pages (default: 0 = all pages).
  --gui                 Launch the graphical user interface.
  --version             Show version and exit.
```

### GUI

```bash
pdfextract-gui
# or
python -m pdfextract --gui
```

The GUI provides a file-browser button, format and max-pages controls, a
scrollable output area, and a save-to-file dialog.  Extraction runs on a
background thread so the window remains responsive.

---

## Output formats

| Format | Description |
|--------|-------------|
| `text` | Plain concatenated text, one blank line between pages |
| `markdown` | Heading per page; metadata table; warnings section |
| `json` | Structured dict with `source`, `page_count`, `word_count`, `metadata`, `errors`, and `pages` array |

### JSON schema

```json
{
  "source": "paper.pdf",
  "page_count": 10,
  "word_count": 4321,
  "metadata": {"Title": "...", "Author": "..."},
  "errors": [],
  "pages": [
    {"page": 1, "text": "...", "words": 312},
    ...
  ]
}
```

---

## Limitations

| Limitation | Notes |
|------------|-------|
| PDF 1.5+ cross-reference streams | Detected and reported; classic xref tables only |
| Encrypted PDFs | Not supported; load error recorded in `result.errors` |
| CIDFont / ToUnicode encodings | Characters may appear as latin-1 approximations |
| Multi-column layout | No reading-order reconstruction; text follows object order |

---

## Development

```bash
pip install -e ".[dev]"   # installs pytest
pytest tests/ -v
```

---

## Citation

If you use `pdfextract` in your research, please cite:

```bibtex
@software{deshmukh2026pdfextract,
  author  = {Deshmukh, Vaibhav},
  title   = {pdfextract: Pure-Python structured text and metadata extraction from PDF files},
  year    = {2026},
  url     = {https://github.com/vdeshmukh203/pdfextract},
  license = {MIT}
}
```

---

## License

MIT — see [LICENSE](LICENSE).
