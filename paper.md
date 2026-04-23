---
title: 'pdfextract: Structured extraction of text, tables, and figures from scientific PDF documents'
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

`pdfextract` is a Python library and command-line tool for structured extraction of content from scientific PDF documents. It combines PDF parsing (via `pdfminer.six`), table detection (via heuristic whitespace analysis and `camelot`), and figure boundary detection (via bounding-box analysis of non-text PDF objects) to produce structured output in JSON or Markdown format. Extracted content includes section-segmented body text, tables as pandas DataFrames, figure captions, and metadata (title, authors, abstract, DOI). `pdfextract` is designed for batch processing of paper corpora in systematic review and meta-analysis pipelines.

# Statement of Need

Scientific text mining pipelines require reliable extraction of structured content from PDF documents, but existing tools either require commercial licences, lack section-awareness, or produce poorly structured output that requires extensive post-processing [@gao2023reproducibility]. `pdfextract` targets the research workflow of processing hundreds to thousands of papers: it provides a batch mode, consistent JSON output schema, and graceful degradation when content cannot be reliably extracted rather than silently producing malformed output. The structured output integrates directly with downstream NLP tools, enabling reproducible corpus construction for meta-analyses and systematic literature reviews [@stodden2016enhancing; @pineau2021improving].

# Acknowledgements

The author used Claude (Anthropic) for drafting portions of this manuscript. All scientific claims and design decisions are the author's own.

# References
