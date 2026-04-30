# pdfextract

**pdfextract** is a pure-Python library and command-line tool for extracting structured text and metadata from PDF files — no external binaries required.

[![CI](https://github.com/vdeshmukh203/pdfextract/actions/workflows/ci.yml/badge.svg)](https://github.com/vdeshmukh203/pdfextract/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)

---

## Features

- **Pure Python** — no poppler, ghostscript, or Java dependencies
- **Page-tree traversal** — correct document-order extraction via the PDF `/Pages` hierarchy
- **Cross-reference streams** — supports both classic xref tables (PDF 1.0–1.4) and xref streams (PDF 1.5+)
- **Multiple content-stream operators** — `Tj`, `TJ`, `'`, `"` with literal and hex string decoding
- **TJ kerning-gap heuristic** — large negative spacing values are mapped to word spaces
- **Metadata extraction** — Title, Author, Subject, Keywords, Creator, Producer, CreationDate
- **Three output formats** — plain text, Markdown, JSON
- **GUI** — tkinter-based graphical interface (`pdfextract-gui`)
- **Graceful degradation** — non-fatal errors are collected and reported; partially damaged PDFs produce partial output

## Installation

```bash
pip install pdfextract
```

For the graphical interface on Linux, ensure tkinter is available:

```bash
# Debian / Ubuntu
sudo apt-get install python3-tk

# Fedora / RHEL
sudo dnf install python3-tkinter
```

## Quick start

### Python API

```python
from pdfextract import extract_pdf, PDFExtractor

# One-line convenience function
text = extract_pdf("paper.pdf")
md   = extract_pdf("paper.pdf", output_format="markdown")
data = extract_pdf("paper.pdf", output_format="json")

# Lower-level control
result = PDFExtractor("paper.pdf", max_pages=10).extract()
print(f"Pages: {result.page_count}, Words: {result.word_count}")
print(result.metadata)   # {'Title': '...', 'Author': '...', ...}
for page in result.pages:
    print(f"Page {page.page_number}: {page.word_count} words")
```

### Command line

```
usage: pdfextract [-h] [-o FILE] [-f {text,markdown,json}] [-p N] [--version] input

positional arguments:
  input                 Path to the input PDF file.

options:
  -o, --output FILE     Write output to FILE instead of stdout.
  -f, --format          Output format: text (default), markdown, or json.
  -p, --max-pages N     Extract at most N pages (0 = all, the default).
```

Examples:

```bash
pdfextract paper.pdf
pdfextract paper.pdf -f markdown -o paper.md
pdfextract paper.pdf -f json -p 5
```

### Graphical interface

```bash
pdfextract-gui
```

The GUI allows you to browse for a PDF, choose an output format, set a page limit, extract, and save the result — all without touching the command line.

## Output formats

| Format     | Description                                              |
|------------|----------------------------------------------------------|
| `text`     | Plain text, one page per paragraph.                      |
| `markdown` | Metadata section + `## Page N` headings.                 |
| `json`     | Structured JSON with `source`, `metadata`, `pages`, `errors`. |

### JSON schema

```json
{
  "source":     "paper.pdf",
  "page_count": 12,
  "word_count": 4821,
  "metadata":   {"Title": "...", "Author": "..."},
  "errors":     [],
  "pages": [
    {"page": 1, "text": "...", "words": 412, "chars": 2341},
    ...
  ]
}
```

## Known limitations

- **Encrypted PDFs** are not supported; extraction returns an xref error.
- **Object streams** (PDF 1.5 ObjStm) are not decoded; pages stored in object streams will be missing from the output.
- **Font encoding remapping** is not implemented; text is decoded as ISO-8859-1 (Latin-1). CID-keyed fonts and non-Latin scripts may produce garbled output.
- **Reading-order reconstruction** is not performed; words are extracted in the order they appear in the content stream, which may differ from visual reading order in multi-column layouts.

## Running tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Citation

If you use pdfextract in research, please cite:

```bibtex
@article{deshmukh2026pdfextract,
  title   = {pdfextract: Structured extraction of text and metadata from PDF files},
  author  = {Deshmukh, Vaibhav},
  journal = {Journal of Open Source Software},
  year    = {2026}
}
```

## License

MIT © Vaibhav Deshmukh
