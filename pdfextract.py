"""
Standalone shim — imports the installed pdfextract package.

Run directly with ``python pdfextract.py <args>`` or install the package
and use the ``pdfextract`` command instead.
"""
import sys
from pathlib import Path

# Allow running without installation by adding src/ to sys.path.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from pdfextract import (  # noqa: E402 F401
    PDFExtractor,
    ExtractionResult,
    PageResult,
    PDFParseError,
    extract_pdf,
)
from pdfextract.extractor import _cli  # noqa: E402

if __name__ == "__main__":
    _cli()
