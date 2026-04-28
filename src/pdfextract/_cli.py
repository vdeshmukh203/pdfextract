"""Command-line interface for pdfextract."""
from __future__ import annotations

import argparse
import sys

from ._extractor import extract_pdf
from . import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pdfextract",
        description="Extract structured text and metadata from PDF files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  pdfextract paper.pdf\n"
            "  pdfextract paper.pdf -f markdown -o out.md\n"
            "  pdfextract paper.pdf -f json -p 5\n"
            "  pdfextract --gui"
        ),
    )
    parser.add_argument("input", nargs="?", help="Path to input PDF file.")
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
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the graphical user interface.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"pdfextract {__version__}",
    )

    args = parser.parse_args(argv)

    if args.gui:
        from .gui import launch_gui
        launch_gui()
        return 0

    if not args.input:
        parser.print_help()
        return 1

    try:
        out = extract_pdf(
            args.input,
            output_format=args.fmt,
            output_path=args.output,
            max_pages=args.max_pages,
        )
    except FileNotFoundError:
        print(f"pdfextract: error: file not found: {args.input}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"pdfextract: error: {exc}", file=sys.stderr)
        return 3

    if args.output:
        print(f"Written to {args.output}")
    else:
        print(out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
