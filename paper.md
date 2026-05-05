---
title: 'pdfextract: Pure-Python extraction of text and metadata from PDF files'
tags:
  - Python
  - PDF
  - text extraction
  - scientific computing
  - text mining
authors:
  - name: Vaibhav Deshmukh
    orcid: 0000-0001-6745-7062
    affiliation: 1
affiliations:
  - name: Independent Researcher, Nagpur, India
    index: 1
date: 5 May 2026
bibliography: paper.bib
---

# Summary

`pdfextract` is a pure-Python library and command-line tool for extracting text
and metadata from PDF files without requiring any external binaries or compiled
dependencies. It implements a self-contained PDF parser that reads cross-reference
tables (both classic PDF 1.x tables and PDF 1.5+ cross-reference streams),
decodes FlateDecode content streams, resolves indirect object references, and
extracts UTF-16-BE and Latin-1 encoded text from BT/ET operator blocks. Extracted
content is returned as structured Python objects and can be serialised to plain
text, Markdown, or JSON. An optional tkinter-based graphical interface is bundled
for interactive use.

# Statement of Need

Many scientific workflows require bulk extraction of text from PDF corpora —
for systematic literature reviews, meta-analyses, and NLP corpus construction
[@stodden2016enhancing; @pineau2021improving]. Existing tools often depend on
external binaries (Poppler, Ghostscript), require platform-specific installation,
or carry large transitive dependency trees that complicate reproducible environment
setup [@gao2023reproducibility]. `pdfextract` addresses this by providing a
zero-dependency pure-Python implementation that works wherever Python 3.8+
runs — including locked-down HPC environments, Docker containers, and web-hosted
notebooks. Graceful degradation on encrypted or malformed PDFs (returning partial
results with annotated error lists rather than raising unhandled exceptions)
makes it suitable for untrusted batch input.

The library exposes a stable Python API (`PDFExtractor`, `extract_pdf`) and a
`pdfextract` CLI so it integrates into both script-based and interactive
workflows. The structured `ExtractionResult` dataclass carries per-page text,
word and character counts, and key–value metadata (title, author, creation date),
enabling downstream analysis without bespoke post-processing.

# Implementation

The parser pipeline has four stages:

1. **Cross-reference resolution.** The byte offset of the xref section is
   located via the `startxref` trailer token. Classic `xref` tables are
   parsed line-by-line; PDF 1.5+ cross-reference streams are decoded using
   the `/W` field-width descriptor and FlateDecode decompression.

2. **Object parsing.** Each indirect object is located by its xref-table
   byte offset. Page objects are identified by the `/Type /Page` dictionary
   key (matched via regex to tolerate arbitrary whitespace). The `/Contents`
   key is followed — as a single indirect reference or an array of references
   — to retrieve the associated content stream(s).

3. **Stream decoding.** FlateDecode streams are decompressed with `zlib`.
   The decompressor retries with a raw-deflate window flag (`wbits = -15`)
   when standard decompression fails, recovering many files with missing
   zlib headers.

4. **Text extraction.** PDF literal strings inside BT/ET operator blocks
   are decoded with full support for octal escape sequences (1–3 digits),
   two-character escape sequences, line continuations, and UTF-16-BE BOM
   detection. Both `Tj` (single string) and `TJ` (glyph-spacing array)
   operators are handled.

Metadata (title, author, subject, keywords, creator, producer, creation date)
is extracted from the PDF Info dictionary referenced in the file trailer.

# Acknowledgements

The author used Claude (Anthropic) for drafting portions of this manuscript
and for code-review assistance. All scientific claims and design decisions
are the author's own.

# References
