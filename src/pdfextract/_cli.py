"""Command-line interface for pdfextract."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .extractor import PDFExtractor, PDFParseError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdfextract",
        description=(
            "Extract structured text and metadata from PDF files.\n\n"
            "When called without a positional argument the GUI is launched."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "input",
        nargs="?",
        metavar="PDF",
        help="Path to the input PDF file. Omit to launch the GUI.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        metavar="PATH",
        help="Write output to PATH instead of stdout.",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["text", "markdown", "json"],
        default="text",
        dest="fmt",
        metavar="FMT",
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
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the graphical user interface.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point; returns an integer exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # GUI mode: no positional arg, or --gui flag
    if args.gui or args.input is None:
        try:
            from .gui import run_gui
            run_gui()
        except ImportError as exc:
            print(f"GUI unavailable: {exc}", file=sys.stderr)
            return 1
        return 0

    # CLI extraction mode
    extractor = PDFExtractor(args.input, max_pages=args.max_pages)
    try:
        result = extractor.extract()
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except PDFParseError as exc:
        print(f"Parse error: {exc}", file=sys.stderr)
        return 1

    if args.fmt == "json":
        output = result.to_json()
    elif args.fmt == "markdown":
        output = result.to_markdown()
    else:
        output = result.full_text

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(output)

    for warning in result.errors:
        print(f"Warning: {warning}", file=sys.stderr)

    return 0


def _cli() -> None:
    sys.exit(main())
