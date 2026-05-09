# pdfextract

**pdfextract** is a pure-Python library and command-line tool for extracting structured text and metadata from PDF files. It requires no external binaries, no Java runtime, and no compiled extensions — only the Python standard library.

## Features

- Parses PDF cross-reference tables and decompresses FlateDecode content streams
- Extracts text from BT/ET blocks, handling literal strings, hex strings, TJ arrays, and octal escapes
- Recovers document metadata from the PDF Info dictionary (title, author, subject, keywords, creator)
- Outputs plain text, Markdown, or structured JSON
- Degrades gracefully on malformed or encrypted PDFs, returning partial results with structured error messages
- Desktop GUI (Tkinter) for point-and-click extraction
- Batch-friendly CLI with page-limit support

## Installation

```bash
pip install pdfextract
```

Or install from source:

```bash
git clone https://github.com/vdeshmukh203/pdfextract.git
cd pdfextract
pip install -e .
```

Requires Python 3.8 or later. No additional dependencies.

## Quick start

### Python API

```python
import pdfextract

# Simple one-call extraction
text = pdfextract.extract_pdf("paper.pdf")
markdown = pdfextract.extract_pdf("paper.pdf", output_format="markdown")
json_str = pdfextract.extract_pdf("paper.pdf", output_format="json")

# Full result object
extractor = pdfextract.PDFExtractor("paper.pdf", max_pages=10)
result = extractor.extract()

print(result.page_count)          # number of pages found
print(result.word_count)          # total words across all pages
print(result.metadata)            # dict of Info-dictionary fields
print(result.full_text)           # all page text joined by blank lines

for page in result.pages:
    print(f"Page {page.page_number}: {page.word_count} words")
```

### Command-line interface

```
usage: pdfextract [-h] [-o OUTPUT] [-f {text,markdown,json}] [-p N] input

positional arguments:
  input                 Path to input PDF file.

options:
  -o, --output PATH     Write output to this file instead of stdout.
  -f, --format FMT      text (default), markdown, or json.
  -p, --max-pages N     Stop after N pages (0 = all).
```

Examples:

```bash
pdfextract paper.pdf
pdfextract paper.pdf -f markdown -o paper.md
pdfextract paper.pdf -f json -p 5
```

### Desktop GUI

```bash
pdfextract-gui
```

The GUI lets you browse for a PDF, choose format and page limit, preview the extracted text, and save the output — no command line required.

## Output formats

| Format | Description |
|--------|-------------|
| `text` | Plain concatenated text, pages separated by blank lines |
| `markdown` | Heading per page, metadata section, word counts |
| `json` | Structured dict with `source`, `page_count`, `word_count`, `metadata`, `errors`, and `pages` array |

## Limitations

- **Encrypted PDFs** are not supported; the extractor returns an empty result with an error message.
- **CMap / font encoding** is not resolved; text from PDFs that use custom character encodings may appear garbled.
- **Cross-reference streams** (PDF 1.5 compressed xref) are not parsed; only traditional xref tables are supported.
- **Images and vector graphics** are ignored; only text operators are extracted.

## Development

```bash
pip install -e .
pytest
```

## License

MIT — see [LICENSE](LICENSE).

## Citation

If you use `pdfextract` in published research, please cite the accompanying JOSS paper (see [CITATION.cff](CITATION.cff)).
