---
title: 'pdfextract: Pure-Python text and metadata extraction from PDF documents'
tags:
  - Python
  - PDF
  - text extraction
  - metadata
  - scientific computing
  - text mining
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

`pdfextract` is a pure-Python library and command-line tool for extracting text
and metadata from PDF documents without requiring any external binaries or
native library dependencies.  It implements a subset of the PDF specification
sufficient for the vast majority of scientific papers: cross-reference table
parsing (both classic tables and PDF 1.5+ cross-reference streams), page-tree
traversal via the document catalog, FlateDecode stream decompression, BT/ET
content-stream text extraction, and document-level metadata retrieval from the
PDF Info dictionary.  Extracted content is returned as structured Python objects
and can be serialised to plain text, Markdown, or JSON.  An optional tkinter
graphical interface is provided for interactive use.

# Statement of Need

Scientific text-mining pipelines require reliable extraction of content from PDF
documents, but existing solutions involve trade-offs that complicate
reproducibility.  Tools that wrap native binaries (e.g., poppler, mupdf) impose
system-level dependencies that vary across platforms and package versions,
making environment reproducibility harder to guarantee
[@stodden2016enhancing; @pineau2021improving].  Pure-Python alternatives have
historically been either incomplete or poorly maintained.

`pdfextract` addresses these concerns with a zero-dependency, pure-Python
implementation that gracefully degrades on encrypted or non-standard PDFs
rather than crashing, returning partial results with descriptive error entries.
The consistent JSON output schema integrates directly with downstream NLP tools
and dataset construction pipelines, supporting reproducible corpus preparation
for systematic reviews and meta-analyses [@gao2023reproducibility].

# Implementation

The extraction pipeline proceeds as follows:

1. **Cross-reference parsing.** The file's `startxref` offset is located in the
   final 2 KB of the file.  Both classic cross-reference tables and PDF 1.5+
   cross-reference streams (compressed with FlateDecode) are parsed, following
   `/Prev` pointer chains to handle incremental updates.  A linear byte-scan
   fallback handles structurally incomplete files.

2. **Page tree traversal.** The document catalog is resolved from the trailer's
   `/Root` reference.  The page tree is traversed recursively from the `/Pages`
   node, yielding page objects in document order—a more reliable approach than
   scanning all objects for `/Type /Page` heuristically.

3. **Content stream extraction.** Each page's `/Contents` entry (a direct
   object reference or an array of references) is resolved and decompressed.
   Text is extracted by scanning BT/ET blocks for `Tj` and `TJ` operators, and
   PDF literal strings are decoded including octal escape sequences.

4. **Metadata extraction.** The Info dictionary (referenced by `/Info` in the
   trailer) is parsed to retrieve Title, Author, Subject, Keywords, Creator, and
   Producer fields.

5. **Output serialisation.** Results are returned as typed Python dataclasses
   (`ExtractionResult`, `PageResult`) and can be serialised to plain text,
   Markdown, or JSON through built-in methods.

# Known Limitations

`pdfextract` does not support password-protected PDFs, CIDFont ToUnicode glyph
mapping, objects stored in compressed ObjStm streams (PDF 1.5+ compressed
object streams), or right-to-left scripts.  Scanned image-only PDFs require a
separate OCR step.  These limitations are documented in the project README.

# Acknowledgements

The author used Claude (Anthropic) for assistance during development and
manuscript preparation.  All scientific claims and design decisions are the
author's own.

# References
