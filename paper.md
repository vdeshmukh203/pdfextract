---
title: 'pdfextract: Pure-Python structured extraction of text and metadata from scientific PDF documents'
tags:
  - Python
  - PDF
  - extraction
  - NLP
  - scientific-computing
  - text-mining
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
structured text and metadata from scientific PDF documents using only the
Python standard library — no third-party packages or external binaries are
required.  It implements a self-contained PDF parser that reads
cross-reference tables (PDF ≤ 1.4) and cross-reference streams (PDF 1.5+
introduced in the ISO 32000 specification [@iso32000]), decompresses
FlateDecode content streams, and extracts text runs from BT/ET operator
blocks.  Extracted content includes body text with reading-order
reconstruction, document metadata (title, author, subject, keywords,
creation date) recovered from the PDF Info dictionary, and per-page
word and character counts.  Results are serialised as plain text,
Markdown, or JSON.  A tkinter graphical interface is bundled alongside
the CLI entry point, enabling non-programmatic use.

`pdfextract` is designed for reproducible batch processing of paper
corpora in systematic review and meta-analysis pipelines: it has no
installation-time dependencies beyond a CPython ≥ 3.8 interpreter,
produces a deterministic JSON output schema across platforms, and
degrades gracefully — logging non-fatal parse errors per page rather
than aborting — when processing encrypted or structurally malformed
documents.

# Statement of Need

Scientific text mining pipelines require reliable extraction of structured
content from PDF documents, but existing tools either require commercial
licences, depend on large compiled libraries (such as `pdfminer.six` or
`pymupdf`), or produce poorly structured output that requires extensive
post-processing [@gao2023reproducibility].  Dependency-heavy tools
complicate reproducibility in locked-down high-performance computing
environments where installing non-standard packages may be impossible or
require administrative approval.

`pdfextract` fills the gap between trivial `pdftotext`-style wrappers
and full-featured PDF frameworks by providing:

1. **Zero dependencies** — the complete parser is implemented in a single
   Python module using only `re`, `struct`, `zlib`, `json`, `dataclasses`,
   and `pathlib` from the standard library, making installation as simple
   as copying one file.

2. **Structured JSON output** — each extraction yields a consistent
   schema (`source`, `page_count`, `word_count`, `metadata`, `errors`,
   `pages`) that integrates directly with downstream NLP tools without
   bespoke post-processing.

3. **Graceful degradation** — parse errors are captured per page and
   surfaced in the `errors` field rather than raising exceptions, enabling
   bulk processing of heterogeneous corpora where some documents may be
   malformed [@stodden2016enhancing; @pineau2021improving].

4. **Graphical interface** — a bundled tkinter GUI allows domain
   scientists unfamiliar with the command line to extract text
   interactively.

The structured output integrates directly with downstream NLP tools,
enabling reproducible corpus construction for meta-analyses and systematic
literature reviews.

# Acknowledgements

The author used Claude (Anthropic) for drafting portions of this
manuscript and for code generation during development.  All scientific
claims and design decisions are the author's own.

# References
