"""
pdfextract – backward-compatibility shim.

The canonical implementation lives in ``src/pdfextract/``.
This module re-exports everything so that scripts which import
``pdfextract`` directly (without installing the package) still work.
"""
from __future__ import annotations
import sys
from pathlib import Path

# Make src/ importable when running the file directly
_src = Path(__file__).parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from pdfextract import (  # noqa: E402  (import not at top)
    PDFExtractor,
    ExtractionResult,
    PageResult,
    PDFParseError,
    extract_pdf,
    extract_batch,
)

__all__ = [
    "PDFExtractor",
    "ExtractionResult",
    "PageResult",
    "PDFParseError",
    "extract_pdf",
    "extract_batch",
]


def _cli() -> None:
    import argparse, json as _json

    parser = argparse.ArgumentParser(
        prog="pdfextract",
        description="Extract structured text and metadata from PDF files.",
    )
    parser.add_argument("input", nargs="+", help="PDF file(s) to process.")
    parser.add_argument("-o", "--output", default=None,
                        help="Output file (single input) or directory (batch).")
    parser.add_argument(
        "-f", "--format",
        choices=["text", "markdown", "json"],
        default="text",
        dest="fmt",
    )
    parser.add_argument("-p", "--max-pages", type=int, default=0,
                        metavar="N", help="Max pages per file (0 = all).")
    args = parser.parse_args()

    if len(args.input) == 1:
        out = extract_pdf(
            args.input[0],
            output_format=args.fmt,
            output_path=args.output,
            max_pages=args.max_pages,
        )
        if not args.output:
            print(out)
        else:
            print(f"Written to {args.output}")
    else:
        results = extract_batch(
            args.input,
            output_format=args.fmt,
            output_dir=args.output,
            max_pages=args.max_pages,
        )
        for r in results:
            status = "ok" if not r.errors else f"{len(r.errors)} error(s)"
            print(f"{r.source}: {r.page_count} pages, {r.word_count} words [{status}]")


if __name__ == "__main__":
    _cli()
