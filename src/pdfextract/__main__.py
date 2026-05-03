"""Entry point for ``python -m pdfextract``."""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .extractor import extract_pdf
from .schema import PDFParseError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdfextract",
        description="Extract structured text and metadata from PDF files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  pdfextract paper.pdf\n"
            "  pdfextract paper.pdf -f markdown -o paper.md\n"
            "  pdfextract paper.pdf -f json -p 10\n"
            "  pdfextract --gui\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"pdfextract {__version__}")
    parser.add_argument(
        "input", nargs="?", default=None,
        help="Path to input PDF file (omit when using --gui).",
    )
    parser.add_argument("-o", "--output", default=None, metavar="FILE",
                        help="Write output to FILE instead of stdout.")
    parser.add_argument(
        "-f", "--format",
        choices=["text", "markdown", "json"],
        default="text",
        dest="fmt",
        metavar="FMT",
        help="Output format: text (default), markdown, or json.",
    )
    parser.add_argument(
        "-p", "--max-pages", type=int, default=0, metavar="N",
        help="Stop after N pages (0 = all pages).",
    )
    parser.add_argument(
        "--gui", action="store_true",
        help="Launch the browser-based GUI.",
    )
    parser.add_argument(
        "--port", type=int, default=None, metavar="PORT",
        help="Port for --gui (default: auto-selected).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.gui:
        from .gui import run_gui
        run_gui(port=args.port)
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
    except FileNotFoundError as exc:
        print(f"pdfextract: error: {exc}", file=sys.stderr)
        return 1
    except PDFParseError as exc:
        print(f"pdfextract: parse error: {exc}", file=sys.stderr)
        return 1

    if not args.output:
        print(out)
    else:
        print(f"Written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
