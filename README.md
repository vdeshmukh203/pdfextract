# pdfextract

Pure-Python PDF text and metadata extractor — no external binaries required.

Reads cross-reference tables, resolves page-content object references, decodes
FlateDecode streams, and outputs plain text, Markdown, or JSON. Ships with a
command-line interface and a Tkinter GUI.

## Installation

```bash
pip install .
```

Requires Python ≥ 3.8. No third-party runtime dependencies.

## CLI

```bash
# Single file — print to stdout
pdfextract paper.pdf

# Save as Markdown
pdfextract paper.pdf -f markdown -o paper.md

# JSON output, first 5 pages only
pdfextract paper.pdf -f json -p 5 -o paper.json

# Batch — write .txt files into ./out/
pdfextract *.pdf -o out/
```

```
usage: pdfextract [-h] [-o OUTPUT] [-f {text,markdown,json}] [-p N] input [input ...]
```

## GUI

```bash
pdfextract-gui
```

Opens a desktop window: browse for a PDF, choose format, click **Extract**,
then **Save** the result.

## Python API

```python
from pdfextract import PDFExtractor, extract_pdf, extract_batch

# Simple one-liner
text = extract_pdf("paper.pdf")

# Full result object
result = PDFExtractor("paper.pdf").extract()
print(result.metadata)          # {'Title': '...', 'Author': '...'}
print(result.page_count)
print(result.pages[0].text)
print(result.to_markdown())

# Batch
results = extract_batch(["a.pdf", "b.pdf"], output_format="json", output_dir="out/")
```

### ExtractionResult

| Attribute | Type | Description |
|-----------|------|-------------|
| `source` | `str` | Filename |
| `page_count` | `int` | Number of pages extracted |
| `pages` | `list[PageResult]` | Per-page text and word counts |
| `metadata` | `dict[str, str]` | PDF Info dictionary (Title, Author, …) |
| `errors` | `list[str]` | Non-fatal parse warnings |
| `full_text` | `str` | All pages joined |
| `word_count` | `int` | Total words |
| `to_dict()` | | JSON-serialisable dict |
| `to_json()` | | JSON string |
| `to_markdown()` | | Markdown string |

## Limitations

- Encrypted PDFs are not supported.
- Cross-reference streams (PDF 1.5+, common in newer tools) fall back to an
  object-scan heuristic; text is still extracted in most cases.
- CIDFont / ToUnicode glyph mapping is not implemented; non-Latin text may
  appear garbled.

## Testing

```bash
pip install pytest
pytest tests/
```

## License

MIT — see [LICENSE](LICENSE).
