"""Command-line interface for pdfextract."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .extractor import PDFExtractor


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdfextract",
        description="Extract structured text and metadata from PDF files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  pdfextract paper.pdf\n"
            "  pdfextract paper.pdf -f markdown -o out.md\n"
            "  pdfextract paper.pdf -f json -p 5\n"
        ),
    )
    parser.add_argument("input", help="Path to input PDF file.")
    parser.add_argument("-o", "--output", default=None, help="Output file path.")
    parser.add_argument(
        "-f", "--format",
        choices=["text", "markdown", "json"],
        default="text",
        dest="fmt",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "-p", "--max-pages",
        type=int,
        default=0,
        metavar="N",
        help="Stop after N pages (default: 0 = all pages).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    extractor = PDFExtractor(args.input, max_pages=args.max_pages)
    try:
        result = extractor.extract()
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.fmt == "json":
        out = result.to_json()
    elif args.fmt == "markdown":
        out = result.to_markdown()
    else:
        out = result.full_text

    if result.errors:
        for err in result.errors:
            print(f"Warning: {err}", file=sys.stderr)

    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
