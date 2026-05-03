# pdfextract

**Pure-Python PDF text and metadata extractor** — no external binaries or
third-party packages required.

[![Tests](https://github.com/vdeshmukh203/pdfextract/actions/workflows/ci.yml/badge.svg)](https://github.com/vdeshmukh203/pdfextract/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Features

- Parses classic xref tables **and** PDF 1.5+ cross-reference streams
- Follows `/Prev` chains for incrementally-updated documents
- Traverses the PDF **Pages tree** for correct reading order
- FlateDecode (zlib/deflate) stream decompression with raw-deflate fallback
- Extracts `Info` dictionary metadata (Title, Author, Subject, …)
- Output formats: plain text, Markdown, JSON
- **Browser-based GUI** — one command, opens in your default browser
- Zero non-standard dependencies (pure standard library)
- Graceful degradation: per-page errors collected, not raised

## Installation

```bash
pip install pdfextract
```

Requires Python 3.8 or later.

## Quick start

### CLI

```bash
# plain text to stdout
pdfextract paper.pdf

# Markdown to file
pdfextract paper.pdf -f markdown -o paper.md

# JSON (first 10 pages only)
pdfextract paper.pdf -f json -p 10 -o paper.json

# Launch the browser GUI
pdfextract --gui
```

### Python API

```python
from pdfextract import PDFExtractor, extract_pdf

# High-level convenience function
text = extract_pdf("paper.pdf")
md   = extract_pdf("paper.pdf", output_format="markdown")
js   = extract_pdf("paper.pdf", output_format="json", max_pages=5)

# Full result object
result = PDFExtractor("paper.pdf").extract()
print(f"{result.page_count} pages, {result.word_count} words")
print(result.metadata.get("Title", "—"))
for page in result.pages:
    print(f"Page {page.page_number}: {page.word_count} words")
```

## GUI

```bash
pdfextract --gui          # auto-selects a free port starting at 8765
pdfextract --gui --port 9000
```

The GUI opens in your default web browser.  Select a PDF file, choose an
output format, and click **Extract**.  Results can be copied to the clipboard
or downloaded as a file.

## CLI reference

```
usage: pdfextract [-h] [--version] [-o FILE] [-f FMT] [-p N] [--gui] [--port PORT]
                  [input]

positional arguments:
  input                 Path to input PDF file (omit when using --gui)

options:
  -o, --output FILE     Write output to FILE instead of stdout
  -f, --format FMT      text (default) | markdown | json
  -p, --max-pages N     Stop after N pages (0 = all)
  --gui                 Launch the browser-based GUI
  --port PORT           Port for --gui (default: auto-selected)
  --version             Show version and exit
```

## Development

```bash
git clone https://github.com/vdeshmukh203/pdfextract
cd pdfextract
pip install -e .
pytest
```

## License

MIT — see [LICENSE](LICENSE).
