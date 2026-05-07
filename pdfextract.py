"""
Backward-compatible shim.

The canonical implementation lives in ``src/pdfextract/__init__.py``.
After ``pip install -e .`` the package is importable as ``import pdfextract``
from any Python environment.  This file allows the CLI to be run directly
as ``python pdfextract.py <args>`` without installation.
"""
import sys
from pathlib import Path

# When executed as a script (__name__ == "__main__"), Python does not shadow
# the src package with this file, so the import below resolves correctly.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from pdfextract import (  # noqa: F401, E402
    __version__,
    PDFParseError,
    PDFExtractor,
    ExtractionResult,
    PageResult,
    extract_pdf,
    _cli,
)

if __name__ == "__main__":
    _cli()
