# pdfextract

Pure-Python extraction of text and metadata from PDF files — no external
binaries required.

## Features

- Parses classic PDF 1.x cross-reference tables **and** PDF 1.5+ xref streams
- Decodes FlateDecode content streams (`zlib`, with raw-deflate fallback)
- Resolves `/Contents` indirect references and arrays
- Handles Latin-1, octal escapes, and UTF-16-BE encoded strings
- Extracts PDF Info metadata (title, author, subject, keywords, dates)
- Outputs plain text, Markdown, or JSON
- CLI and Python API
- Optional tkinter GUI (`pdfextract --gui`)
- Zero runtime dependencies (Python ≥ 3.8 standard library only)

## Installation

```bash
pip install pdfextract
```

Or run directly from the repository without installation:

```bash
python pdfextract.py document.pdf
```

## CLI usage

```
pdfextract [-h] [-o FILE] [-f {text,markdown,json}] [-p N] [--gui] input

positional arguments:
  input                 Path to the input PDF file

options:
  -o, --output FILE     Write output to FILE (default: stdout)
  -f, --format FORMAT   Output format: text, markdown, json  (default: text)
  -p, --max-pages N     Process at most N pages (0 = all)
  --gui                 Launch the graphical interface
```

### Examples

```bash
# Extract plain text to stdout
pdfextract paper.pdf

# Write JSON output to a file
pdfextract paper.pdf -f json -o paper.json

# Extract only the first 5 pages as Markdown
pdfextract paper.pdf -f markdown -p 5

# Launch the GUI
pdfextract --gui
```

## Python API

```python
from pdfextract import PDFExtractor, extract_pdf

# Full control via the class
extractor = PDFExtractor("paper.pdf", max_pages=10)
result = extractor.extract()

print(result.page_count)         # number of pages found
print(result.word_count)         # total word count
print(result.metadata)           # dict of PDF Info fields
print(result.full_text)          # concatenated page text
print(result.pages[0].text)      # text for page 1

# Convenience function
text = extract_pdf("paper.pdf", output_format="text")
json_str = extract_pdf("paper.pdf", output_format="json")
md = extract_pdf("paper.pdf", output_format="markdown",
                 output_path="paper.md")
```

### `ExtractionResult` fields

| Field | Type | Description |
|-------|------|-------------|
| `source` | `str` | Filename |
| `page_count` | `int` | Number of pages extracted |
| `word_count` | `int` | Total word count (all pages) |
| `pages` | `List[PageResult]` | Per-page results |
| `metadata` | `Dict[str, str]` | PDF Info dictionary |
| `errors` | `List[str]` | Non-fatal parse errors |

### `PageResult` fields

| Field | Type | Description |
|-------|------|-------------|
| `page_number` | `int` | 1-based page index |
| `text` | `str` | Extracted text |
| `word_count` | `int` | Words on this page |
| `char_count` | `int` | Characters on this page |

## GUI

```bash
pdfextract --gui
# or
python -m pdfextract.gui
```

The GUI lets you browse for a PDF, choose the output format, set a page
limit, view the extracted text in a scrollable pane, and save the result
to a file.

## Limitations

- Encrypted PDFs are not supported (returns an error entry; no crash).
- Right-to-left and CJK text may not be rendered in reading order.
- Images and vector graphics are not extracted.
- Ligatures encoded as private-use Unicode codepoints may appear as
  replacement characters unless a ToUnicode map is present.

## Running tests

```bash
pip install pytest
pytest tests/ -v
```

## Citation

If you use `pdfextract` in research, please cite it using the metadata in
[CITATION.cff](CITATION.cff).

## License

MIT — see [LICENSE](LICENSE).
