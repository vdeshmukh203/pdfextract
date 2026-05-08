"""Command-line interface for pdfextract."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .extractor import PDFExtractor


def main(argv=None) -> None:
    """Entry point for the ``pdfextract`` command-line tool."""
    parser = argparse.ArgumentParser(
        prog="pdfextract",
        description="Extract text and metadata from PDF files without external binaries.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  pdfextract paper.pdf\n"
            "  pdfextract paper.pdf -f markdown -o paper.md\n"
            "  pdfextract paper.pdf -f json -p 5\n"
        ),
    )
    parser.add_argument("input", help="Path to the input PDF file.")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        metavar="FILE",
        help="Write output to FILE instead of stdout.",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["text", "markdown", "json"],
        default="text",
        dest="fmt",
        metavar="FORMAT",
        help="Output format: text (default), markdown, or json.",
    )
    parser.add_argument(
        "-p",
        "--max-pages",
        type=int,
        default=0,
        metavar="N",
        help="Stop after N pages (0 = all pages).",
    )

    args = parser.parse_args(argv)

    extractor = PDFExtractor(args.input, max_pages=args.max_pages)
    try:
        result = extractor.extract()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.fmt == "json":
        out = result.to_json()
    elif args.fmt == "markdown":
        out = result.to_markdown()
    else:
        out = result.full_text

    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(out)


if __name__ == "__main__":
    main()
