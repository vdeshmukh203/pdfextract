"""Command-line interface for pdfextract."""
from __future__ import annotations

import sys
from typing import List, Optional

from . import __version__, extract_pdf
from .extractor import PDFParseError


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point for the ``pdfextract`` command.

    Parameters
    ----------
    argv:
        Argument list (defaults to ``sys.argv[1:]``).

    Returns
    -------
    int
        Exit code (0 on success, 1 on error).
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="pdfextract",
        description="Extract structured text and metadata from PDF files.",
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
        "-o", "--output",
        default=None,
        metavar="FILE",
        help="Write output to FILE instead of stdout.",
    )
    parser.add_argument(
        "-f", "--format",
        choices=["text", "markdown", "json"],
        default="text",
        dest="fmt",
        help="Output format: text (default), markdown, or json.",
    )
    parser.add_argument(
        "-p", "--max-pages",
        type=int,
        default=0,
        metavar="N",
        help="Extract at most N pages (0 = all, the default).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    args = parser.parse_args(argv)

    try:
        out = extract_pdf(
            args.input,
            output_format=args.fmt,
            output_path=args.output,
            max_pages=args.max_pages,
        )
    except PDFParseError as exc:
        print(f"pdfextract: error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"pdfextract: error: {exc}", file=sys.stderr)
        return 1

    if args.output:
        print(f"Written to {args.output}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
