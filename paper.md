---
title: 'pdfextract: Structured extraction of text and metadata from PDF documents'
tags:
  - Python
  - PDF
  - text extraction
  - NLP
  - scientific computing
  - text mining
authors:
  - name: Vaibhav Deshmukh
    orcid: 0000-0001-6745-7062
    affiliation: 1
affiliations:
  - name: Independent Researcher, Nagpur, India
    index: 1
date: 06 May 2026
bibliography: paper.bib
---

# Summary

`pdfextract` is a Python library and command-line tool for extracting structured
text and metadata from PDF documents. It uses `pdfminer.six` [@shinyama2022pdfminer]
for layout-aware text extraction, preserving reading order across single- and
multi-column document layouts. Extracted content includes full document text
with page-level segmentation, word and character statistics per page, and
document metadata (title, author, creation date, and other PDF Info fields)
parsed from the PDF header. Output is available in plain text, Markdown, or JSON
format, supporting both interactive and batch-processing workflows. An optional
graphical interface built with `tkinter` provides a point-and-click alternative
to the command-line tool.

# Statement of Need

Systematic literature reviews and corpus-based NLP studies require reliable
extraction of text from large collections of PDF documents
[@stodden2016enhancing; @pineau2021improving]. Existing tools either depend on
commercial software, require system-level binary dependencies
(e.g., `poppler`, `ghostscript`) that complicate reproducible environment setup,
or produce unstructured output that requires significant post-processing before
it can be used in a pipeline [@gao2023reproducibility]. `pdfextract` addresses
these constraints by providing a pure-Python package with a single runtime
dependency (`pdfminer.six`), a consistent JSON output schema suitable for
downstream NLP tools, and graceful degradation on malformed or encrypted
documents rather than silent data loss. The JSON schema records extraction
warnings alongside content, enabling auditable corpus construction.

# Implementation

`pdfextract` is structured as an installable Python package with four public
components:

1. **`PDFExtractor`** — the core extraction class. It opens the PDF with
   `pdfminer.six`, iterates over page layouts, and sorts text boxes in
   approximate reading order (top-to-bottom, left-to-right). Metadata is
   extracted from the PDF Info dictionary and decoded from either Latin-1 or
   UTF-16-BE, the two encodings mandated by the PDF specification
   [@adobepdf2008].

2. **`ExtractionResult` / `PageResult`** — immutable dataclass schema holding
   extracted text, per-page statistics, metadata, and a list of non-fatal
   warnings. The schema serialises to JSON, Markdown, or plain text.

3. **CLI** (`pdfextract`) — an `argparse`-based interface supporting format
   selection (`text`, `markdown`, `json`), page limits, and optional file output.

4. **GUI** (`pdfextract-gui`) — a `tkinter` interface for interactive use,
   with file browsing, format selection, threaded extraction to keep the
   interface responsive, and output saving.

# Acknowledgements

The author used Claude (Anthropic) for assistance with portions of the
implementation and manuscript. All design decisions and scientific claims are
the author's own.

# References
