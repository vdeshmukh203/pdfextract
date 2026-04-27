"""
pdfextract: Structured scientific PDF content extraction tool.

Pure-Python library that parses PDF documents and extracts structured
content: body text, section metadata (title, author, subject, keywords,
creation date), and document-level statistics.  Output is emitted as
plain text, Markdown, or structured JSON, enabling downstream text
mining, dataset construction, and reproducible scientific content
analysis pipelines.

Note
----
The installed package is the single-module ``pdfextract.py`` at the
repository root (declared via ``py-modules`` in ``pyproject.toml``).
This ``src/pdfextract/`` namespace is retained for compatibility with
editable installs but does not define any symbols of its own.
"""

__version__ = "0.1.0"
__author__ = "Vaibhav Deshmukh"
__license__ = "MIT"
