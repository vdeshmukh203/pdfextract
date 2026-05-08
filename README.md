# pdfextract

[![CI](https://github.com/vdeshmukh203/pdfextract/actions/workflows/ci.yml/badge.svg)](https://github.com/vdeshmukh203/pdfextract/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)

Pure-Python library and CLI for extracting text and metadata from PDF files —
**no external binaries, no native dependencies**.

## Features

- Parses PDF cross-reference tables (classic xref and PDF 1.5+ xref streams)
- Follows `/Prev` chains to reconstruct incremental-update histories
- Traverses the page tree via the document catalog for correct page ordering
- Decompresses FlateDecode (zlib/deflate) content streams
- Extracts text from BT/ET blocks (`Tj` and `TJ` operators)
- Reads document metadata from the PDF Info dictionary
  (Title, Author, Subject, Keywords, Creator, Producer)
- Output formats: plain text, Markdown, JSON
- Graceful degradation on encrypted or malformed PDFs — returns partial
  results rather than crashing
- Interactive GUI (tkinter, standard library)
- Zero run-time dependencies beyond Python ≥ 3.8

## Installation

```bash
pip install pdfextract
```

Or clone and install in editable mode:

```bash
git clone https://github.com/vdeshmukh203/pdfextract
cd pdfextract
pip install -e .
```

## Quick start

### Command line

```bash
# Plain text to stdout
pdfextract paper.pdf

# Markdown to file
pdfextract paper.pdf -f markdown -o paper.md

# JSON (structured, with metadata)
pdfextract paper.pdf -f json -o paper.json

# First 10 pages only
pdfextract paper.pdf -p 10
```

Full usage:

```
usage: pdfextract [-h] [-o FILE] [-f FORMAT] [-p N] input

positional arguments:
  input                 Path to the input PDF file.

options:
  -o, --output FILE     Write output to FILE instead of stdout.
  -f, --format FORMAT   text (default), markdown, or json.
  -p, --max-pages N     Stop after N pages (0 = all pages).
```

### Graphical interface

```bash
pdfextract-gui
```

The GUI lets you browse for a PDF, choose output format and page limit, view
the extracted text, and save the result to a file.

### Python API

```python
from pdfextract import PDFExtractor, extract_pdf

# High-level one-liner
text = extract_pdf("paper.pdf")

# Full result object with per-page data and metadata
result = PDFExtractor("paper.pdf").extract()

print(f"Pages : {result.page_count}")
print(f"Words : {result.word_count}")
print(f"Title : {result.metadata.get('Title', 'n/a')}")
print(f"Author: {result.metadata.get('Author', 'n/a')}")

for page in result.pages:
    print(f"--- Page {page.page_number} ({page.word_count} words) ---")
    print(page.text[:200])

# Save as JSON
import json
with open("output.json", "w") as f:
    json.dump(result.to_dict(), f, indent=2)

# Save as Markdown
with open("output.md", "w") as f:
    f.write(result.to_markdown())
```

### JSON output schema

```json
{
  "source": "paper.pdf",
  "page_count": 12,
  "word_count": 5432,
  "metadata": {
    "Title": "My Paper",
    "Author": "A. Researcher"
  },
  "errors": [],
  "pages": [
    { "page": 1, "text": "...", "words": 450 },
    ...
  ]
}
```

## Running tests

```bash
pip install pytest
pytest
```

## Known limitations

- **Encrypted PDFs**: password-protected files are not supported; extraction
  returns an empty result with an error entry.
- **ObjStm (compressed object streams, PDF 1.5+)**: objects packed into
  compressed object streams are not yet resolved.  Most scientific PDFs
  produced by LaTeX are unaffected.
- **CIDFont / Unicode ToUnicode maps**: glyph-to-character mapping is not
  implemented; text in PDFs that rely on CIDFonts may appear garbled.
- **Right-to-left and vertical scripts**: not supported.
- **Scanned PDFs**: image-only PDFs contain no text layer; use an OCR tool
  (e.g., Tesseract) as a pre-processing step.

## Contributing

Contributions are welcome.  Please open an issue before submitting a pull
request for significant changes.

## License

MIT — see [LICENSE](LICENSE).

## Citation

If you use `pdfextract` in published research, please cite:

```bibtex
@article{deshmukh2026pdfextract,
  title   = {pdfextract: Structured extraction of text and metadata from scientific PDF documents},
  author  = {Deshmukh, Vaibhav},
  journal = {Journal of Open Source Software},
  year    = {2026}
}
```

Or use the metadata in [CITATION.cff](CITATION.cff).
