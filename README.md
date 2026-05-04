# pdfextract

[![CI](https://github.com/vdeshmukh203/pdfextract/actions/workflows/ci.yml/badge.svg)](https://github.com/vdeshmukh203/pdfextract/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)

**pdfextract** is a pure-Python library and command-line tool for extracting
structured text and metadata from PDF files. It requires no external binaries
or third-party packages and works on any platform where Python 3.8+ runs.

---

## Features

- **Pure Python** — zero mandatory third-party dependencies; only the Python
  standard library (`re`, `zlib`, `json`, `pathlib`) is used.
- **Incremental-update support** — follows the `startxref` / `/Prev` chain so
  updated and revised PDFs are handled correctly.
- **FlateDecode decompression** — transparently decompresses `zlib`/`deflate`
  content streams.
- **`/Contents` reference resolution** — follows single-object and array-form
  `Contents` references, the normal structure of well-formed PDF pages.
- **Metadata extraction** — reads the PDF `Info` dictionary for `Title`,
  `Author`, `Subject`, `Keywords`, `Creator`, `Producer`, and date fields;
  handles both literal-string and UTF-16 BE hex-string encodings.
- **Three output formats** — plain text, Markdown (with metadata header and
  per-page sections), and JSON (structured, round-trippable).
- **Batch mode** — process entire directory trees with a single glob pattern.
- **Graceful degradation** — encrypted or structurally malformed PDFs return
  an `ExtractionResult` with an `errors` list rather than raising uncaught
  exceptions.
- **Graphical interface** — an optional Tkinter GUI (`pdfextract gui`) provides
  a file picker, format selector, metadata panel, and scrollable output viewer.

---

## Installation

```bash
pip install pdfextract
```

For the graphical interface, Tkinter must be available (it ships with the
official Python installers on macOS and Windows; on Debian/Ubuntu install
`python3-tk`):

```bash
# Debian / Ubuntu
sudo apt-get install python3-tk
```

### From source

```bash
git clone https://github.com/vdeshmukh203/pdfextract.git
cd pdfextract
pip install -e .
```

---

## Quick start

### Command line

```bash
# Plain text to stdout
pdfextract extract paper.pdf

# Markdown file
pdfextract extract paper.pdf -f markdown -o paper.md

# JSON
pdfextract extract paper.pdf -f json -o paper.json

# Only first 5 pages
pdfextract extract paper.pdf -p 5

# Batch: all PDFs in a directory → individual .txt files
pdfextract batch "papers/*.pdf" -d output/

# Launch GUI
pdfextract gui
```

Legacy single-argument invocation is still accepted for backward compatibility:

```bash
pdfextract paper.pdf
pdfextract paper.pdf -f json -o paper.json
```

### Python API

```python
import pdfextract

# Simple one-call extraction
text = pdfextract.extract_pdf("paper.pdf")
json_str = pdfextract.extract_pdf("paper.pdf", output_format="json")
markdown = pdfextract.extract_pdf("paper.pdf", output_format="markdown",
                                   output_path="paper.md")

# Full result object
extractor = pdfextract.PDFExtractor("paper.pdf", max_pages=10)
result = extractor.extract()

print(result.source)          # filename
print(result.page_count)      # number of pages processed
print(result.word_count)      # total word count
print(result.metadata)        # dict of PDF Info fields
print(result.errors)          # list of non-fatal errors

for page in result.pages:
    print(f"Page {page.page_number}: {page.word_count} words")
    print(page.text)

# Serialize
import json
with open("output.json", "w") as f:
    json.dump(result.to_dict(), f, indent=2)

# Batch extraction
results = pdfextract.batch_extract(
    "corpus/*.pdf",
    output_format="json",
    output_dir="extracted/",
    max_pages=0,   # all pages
)
print(f"Processed {len(results)} files")
```

---

## API reference

### `extract_pdf(path, output_format="text", output_path=None, max_pages=0) → str`

Convenience wrapper that creates a `PDFExtractor`, runs extraction, and
returns the formatted string.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str` | — | Input PDF path. |
| `output_format` | `str` | `"text"` | `"text"`, `"markdown"`, or `"json"`. |
| `output_path` | `str \| None` | `None` | If given, write output to this file. |
| `max_pages` | `int` | `0` | Stop after this many pages (0 = all). |

### `batch_extract(pattern, output_format="text", output_dir=None, max_pages=0) → list[ExtractionResult]`

Process all PDFs matching a glob pattern.

| Parameter | Type | Description |
|-----------|------|-------------|
| `pattern` | `str` | Glob pattern, e.g. `"papers/*.pdf"`. |
| `output_format` | `str` | `"text"`, `"markdown"`, or `"json"`. |
| `output_dir` | `str \| None` | Directory for per-file output files. |
| `max_pages` | `int` | Per-file page limit (0 = all). |

### `class PDFExtractor(path, max_pages=0)`

Low-level extractor. Call `.extract()` to get an `ExtractionResult`.

### `class ExtractionResult`

| Attribute / property | Type | Description |
|----------------------|------|-------------|
| `source` | `str` | Source filename. |
| `page_count` | `int` | Number of pages extracted. |
| `pages` | `list[PageResult]` | Per-page results. |
| `metadata` | `dict[str, str]` | PDF Info dictionary fields. |
| `errors` | `list[str]` | Non-fatal parse errors. |
| `full_text` | `str` (property) | All page text joined by blank lines. |
| `word_count` | `int` (property) | Total word count across all pages. |
| `to_dict()` | `dict` | JSON-serialisable representation. |
| `to_markdown()` | `str` | Markdown-formatted output. |

### `class PageResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| `page_number` | `int` | 1-based page index. |
| `text` | `str` | Extracted text for this page. |
| `word_count` | `int` | Word count (set automatically). |
| `char_count` | `int` | Character count (set automatically). |

### `exception PDFParseError`

Raised when the file does not start with `%PDF` or is otherwise structurally
unreadable.

---

## Limitations

- **Encryption**: Password-protected PDFs are not supported; an error entry is
  recorded in `ExtractionResult.errors`.
- **Cross-reference streams** (PDF 1.5+ compressed xref): only classic
  cross-reference tables are currently parsed. Most PDFs produced by common
  tools include a classic xref table for compatibility.
- **Text rendering order**: text is extracted in object-scan order, not visual
  reading order; multi-column layouts may interleave columns.
- **CIDFont / Type0 fonts**: multi-byte encoded text (common in CJK documents)
  may not decode correctly with the current latin-1 fallback.

---

## Running the tests

```bash
pip install pytest
pytest tests/
```

The test suite uses a programmatically constructed minimal PDF so no external
fixture files are required.

---

## Contributing

Bug reports and pull requests are welcome at
<https://github.com/vdeshmukh203/pdfextract/issues>.

---

## Citation

If you use pdfextract in research, please cite:

```bibtex
@software{deshmukh2025pdfextract,
  author  = {Deshmukh, Vaibhav},
  title   = {pdfextract: Pure-Python structured text and metadata extractor for PDF files},
  year    = {2025},
  url     = {https://github.com/vdeshmukh203/pdfextract},
  license = {MIT}
}
```

---

## License

MIT — see [LICENSE](LICENSE).
