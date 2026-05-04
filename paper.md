---
title: 'pdfextract: A pure-Python library for structured text and metadata extraction from PDF files'
tags:
  - Python
  - PDF
  - text extraction
  - metadata
  - scientific computing
  - reproducibility
authors:
  - name: Vaibhav Deshmukh
    orcid: 0000-0001-6745-7062
    affiliation: 1
affiliations:
  - name: Independent Researcher, Nagpur, India
    index: 1
date: 23 April 2026
bibliography: paper.bib
---

# Summary

`pdfextract` is a pure-Python library and command-line tool for extracting
structured text and document metadata from PDF files.  It implements a
self-contained PDF parser using only the Python standard library—requiring no
external binaries, C extensions, or third-party packages—and produces output
in plain text, Markdown, or JSON format.  The library reads PDF
cross-reference tables (including incremental-update chains), decompresses
`FlateDecode` (zlib/deflate) content streams, resolves indirect `/Contents`
object references, parses BT/ET text blocks with correct handling of literal
strings, octal escapes, and TJ array operators, and extracts document
metadata from the PDF `Info` dictionary.  A Tkinter-based graphical interface
is included for interactive use.

# Statement of Need

Scientific text-mining workflows—systematic reviews, meta-analyses, corpus
construction—require reliable, scriptable extraction of text and bibliographic
metadata from large collections of PDF documents.  Existing general-purpose
libraries either require compiled C/C++ extensions that complicate deployment
in restricted environments (e.g., HPC clusters, container images), carry
commercial or restrictive licences, or lack a stable Python API suitable for
integration into automated pipelines [@nist2015pdf; @pdftextsurvey2019].

`pdfextract` fills the gap of a *zero-dependency*, *pure-Python* extractor
that is trivially installable with `pip` and auditable without a C toolchain.
Its consistent JSON output schema—covering source filename, page count, word
count, per-page text, and Info-dictionary metadata—integrates directly with
downstream NLP tools and data-management frameworks, enabling reproducible
corpus construction [@stodden2016enhancing; @pineau2021improving].  Graceful
degradation on encrypted or malformed documents (errors are recorded in a
structured field rather than silently discarded or raised as unhandled
exceptions) is essential for robustness when processing heterogeneous paper
corpora at scale [@gundersen2018state].

# Implementation

## PDF parsing

`pdfextract` implements a minimal but correct subset of the PDF 1.x
specification [@adobepdf2008]:

- **Cross-reference table parsing**: The `startxref` offset is located by
  scanning the last 2 KiB of the file.  The classical xref table is parsed
  from a 1 MiB buffer (preventing truncation of large tables), and the
  `/Prev` trailer key is followed to merge all revisions in an
  incremental-update chain.
- **Object extraction**: Indirect objects are located by their byte offsets
  from the xref table and extracted with a 128 KiB window.
- **Stream decompression**: `FlateDecode` streams are decompressed with
  Python's built-in `zlib` module, with fallback handling for truncated or
  raw-deflate streams.
- **Page discovery**: Page objects are identified by the regex
  `/Type\s*/Page\b`.  Content streams are resolved via the page object's
  `/Contents` key, which may be a single indirect reference or an array of
  references; in the latter case the streams are concatenated before parsing.

## Text extraction

Text is extracted from PDF content streams by locating BT/ET operator
blocks and collecting all literal strings within them.  The `_decode_pdf_string`
function correctly handles:

- Standard escape sequences (`\n`, `\r`, `\t`, `\(`, `\)`, `\\`).
- Octal character escapes of 1–3 digits (`\ooo`).
- Raw latin-1 bytes for non-escaped characters.

Both `Tj` (single string) and `TJ` (array with inter-character spacing
adjustments) operators are supported.

## Metadata

The PDF `Info` dictionary is located via the trailer's `/Info` reference
and parsed to extract `Title`, `Author`, `Subject`, `Keywords`, `Creator`,
`Producer`, `CreationDate`, and `ModDate` fields.  Both literal-string and
hex-string (including UTF-16 BE) encodings are handled.

## Output formats

Three output formats are supported:

- **Plain text**: all page texts joined by blank lines.
- **Markdown**: metadata header followed by per-page `## Page N` sections.
- **JSON**: a structured, round-trippable representation of the complete
  `ExtractionResult` object.

## Batch processing

The `batch_extract` function accepts a glob pattern and processes all
matching PDF files, optionally writing per-file output to a designated
directory.  This enables automated pipeline use without shell scripting.

## Graphical interface

An optional Tkinter GUI (`pdfextract gui`) provides file selection, format
choice, page-limit control, a metadata panel, and a scrollable output area
with a save-to-file function.  The GUI is implemented in `pdfextract_gui.py`
and runs in a background thread to keep the interface responsive during
extraction.

# Acknowledgements

The author used Claude (Anthropic) for code review and drafting portions of
this manuscript.  All design decisions and scientific claims are the author's own.

# References
