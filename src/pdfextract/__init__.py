"""
pdfextract: Structured scientific PDF content extraction tool.

Parses scientific PDF documents and extracts structured content: sections,
abstracts, figures, tables, captions, equations, citations, and metadata.
Output is emitted as structured JSON, enabling downstream text mining,
dataset construction, and reproducible scientific content analysis pipelines.
"""

__version__ = "0.1.0"
__author__ = "Vaibhav Deshmukh"
__license__ = "MIT"

from .extractor import PDFExtractor
from .schema import ExtractionResult

__all__ = ["PDFExtractor", "ExtractionResult"]
