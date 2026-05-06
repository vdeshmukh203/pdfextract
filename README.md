# pdfextract

[![CI](https://github.com/vdeshmukh203/pdfextract/actions/workflows/ci.yml/badge.svg)](https://github.com/vdeshmukh203/pdfextract/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)

**pdfextract** is a Python library and command-line tool for extracting structured text and metadata from PDF documents. It uses [pdfminer.six](https://github.com/pdfminer/pdfminer.six) for layout-aware text extraction that preserves reading order across single- and multi-column layouts.

## Features

- Layout-aware text extraction (preserves reading order)
- PDF metadata extraction (title, author, creation date, …)
- Output formats: plain text, Markdown, JSON
- Page-level statistics (word count, character count)
- Command-line interface (`pdfextract`)
- Graphical user interface (tkinter, `pdfextract-gui`)
- Python API for programmatic use

## Installation

```bash
pip install pdfextract
```

For the graphical interface, ensure `tkinter` is available:

```bash
# Debian/Ubuntu
sudo apt install python3-tk

# macOS (Homebrew)
brew install python-tk
```

## Quick Start

### Python API

```python
from pdfextract import extract_pdf, PDFExtractor

# Simple one-liner
text = extract_pdf("paper.pdf")

# JSON output
json_str = extract_pdf("paper.pdf", output_format="json")

# Fine-grained control
extractor = PDFExtractor("paper.pdf", max_pages=5)
result = extractor.extract()
print(f"Pages: {result.page_count}, Words: {result.word_count}")
print(result.metadata)          # dict of PDF Info fields
for page in result.pages:
    print(f"--- Page {page.page_number} ---")
    print(page.text)
```

### Command-Line Interface

```bash
# Extract to stdout (plain text)
pdfextract paper.pdf

# Write Markdown to file
pdfextract paper.pdf -f markdown -o paper.md

# Write JSON to file, limit to first 10 pages
pdfextract paper.pdf -f json -p 10 -o paper.json

# Show help
pdfextract --help
```

### Graphical Interface

Launch without arguments (or with `--gui`) to open the GUI:

```bash
pdfextract
# or
pdfextract-gui
# or
pdfextract --gui
```

The GUI lets you browse for a PDF, select an output format, run extraction, and save the result.

## Output Formats

| Format     | Description                                    |
|------------|------------------------------------------------|
| `text`     | Plain text, pages separated by blank lines     |
| `markdown` | Markdown with page headers and metadata table  |
| `json`     | Structured JSON with per-page text and stats   |

### JSON schema

```json
{
  "source": "paper.pdf",
  "page_count": 10,
  "word_count": 4500,
  "metadata": {"title": "...", "author": "..."},
  "errors": [],
  "pages": [
    {"page": 1, "text": "...", "words": 450, "chars": 2800}
  ]
}
```

## API Reference

### `extract_pdf(path, output_format="text", output_path=None, max_pages=0)`

Convenience function. Returns extracted content as a string.

### `PDFExtractor(path, max_pages=0, laparams=None)`

Class-based extractor. Call `.extract()` to get an `ExtractionResult`.

### `ExtractionResult`

| Attribute / Property | Type              | Description                        |
|----------------------|-------------------|------------------------------------|
| `source`             | `str`             | Filename of the source PDF         |
| `page_count`         | `int`             | Number of pages extracted          |
| `pages`              | `List[PageResult]`| Per-page results                   |
| `metadata`           | `Dict[str, str]`  | PDF Info dictionary                |
| `errors`             | `List[str]`       | Non-fatal warnings                 |
| `full_text`          | `str` (property)  | All pages joined                   |
| `word_count`         | `int` (property)  | Total word count                   |
| `to_dict()`          | `dict`            | Serialisable representation        |
| `to_json()`          | `str`             | JSON string                        |
| `to_markdown()`      | `str`             | Markdown string                    |

## Development

```bash
git clone https://github.com/vdeshmukh203/pdfextract
cd pdfextract
pip install -e ".[dev]"
pytest tests/ -v
```

## Citation

If you use pdfextract in research, please cite:

```bibtex
@software{deshmukh2025pdfextract,
  author  = {Deshmukh, Vaibhav},
  title   = {pdfextract: Structured text and metadata extraction from PDF documents},
  year    = {2025},
  url     = {https://github.com/vdeshmukh203/pdfextract},
  license = {MIT}
}
```

## License

MIT — see [LICENSE](LICENSE).
