---
title: 'pdfextract: A pure-Python library for structured text and metadata extraction from PDF documents'
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
date: 07 May 2026
bibliography: paper.bib
---

# Summary

`pdfextract` is a Python library and command-line tool for extracting text and
metadata from PDF documents without any external binary dependencies.  The
library implements a self-contained PDF parser that locates the
cross-reference table (or cross-reference stream for PDF 1.5+ documents),
walks the page tree to enumerate pages in document order, decompresses
FlateDecode content streams using the Python standard-library `zlib` module,
decodes text from `BT`/`ET` operator blocks, and extracts document metadata
from the `/Info` dictionary.  Output can be emitted as plain text, Markdown,
or structured JSON, and a Tkinter-based graphical interface is included for
interactive use.

# Statement of Need

Text mining of scientific literature increasingly relies on automated
extraction of content from PDF documents, yet integrating existing tools
often requires native binary dependencies (e.g., Poppler), licenced software,
or complex installation procedures that impede reproducibility in research
pipelines [@stodden2016enhancing; @pineau2021improving].  `pdfextract`
addresses this by providing a zero-dependency, pure-Python implementation
suitable for deployment in restricted computing environments (HPC clusters,
containers, offline workstations) and for educational use, where inspecting
the source code of the parser is itself instructive.

The library targets batch extraction workflows: it exposes a stable Python
API (`PDFExtractor`, `extract_pdf`) alongside a `pdfextract` CLI, both of
which return a structured `ExtractionResult` object carrying per-page text,
word and character counts, document metadata, and any parsing errors
encountered.  Graceful degradation on malformed or encrypted PDFs—recording
errors rather than raising uncaught exceptions—makes the library robust for
processing large, heterogeneous corpora [@gundersen2018state].

# Implementation

The parsing pipeline consists of four stages:

1. **Cross-reference resolution.** The file trailer's `startxref` pointer is
   located in the final 2 KB of the file.  Classic cross-reference tables
   (`xref` keyword) and PDF 1.5+ cross-reference streams are both handled,
   producing a mapping from object ID to byte offset.

2. **Page tree traversal.** Starting from the document catalog (`/Root`) the
   library walks the `/Pages` tree recursively, collecting leaf page object
   IDs in document order.  This correctly handles multi-level page trees and
   avoids the common mistake of iterating raw object IDs, which does not
   preserve reading order.

3. **Content stream decoding.** Each page object's `/Contents` entry (a
   single indirect reference or an array of references) is dereferenced and
   the corresponding stream objects are read and decompressed.  FlateDecode
   (zlib/deflate) compression is supported; other filters are left undecoded
   with the raw bytes passed through.

4. **Text extraction.** Text is gathered from `BT`/`ET` operator blocks.
   Both literal strings (decoded with full octal-escape and backslash-escape
   handling) and hex strings are supported.

Document metadata (title, author, subject, creator, producer, keywords,
creation date) is extracted from the `/Info` dictionary when present in the
trailer.

# Acknowledgements

The author used Claude (Anthropic) for drafting portions of this manuscript.
All scientific claims and design decisions are the author's own.

# References
