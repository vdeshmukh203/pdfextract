"""PDF content-stream text extraction."""
from __future__ import annotations

import re
from typing import List

# ---------------------------------------------------------------------------
# PDF literal string decoder
# ---------------------------------------------------------------------------

_ESCAPE_MAP = {
    b"n": "\n",
    b"r": "\r",
    b"t": "\t",
    b"b": "\b",
    b"f": "\f",
    b"(": "(",
    b")": ")",
    b"\\": "\\",
}


def decode_pdf_string(s: bytes) -> str:
    """Decode a PDF literal string (content between parentheses, already stripped).

    Handles backslash escapes including ``\\nrtbf()\\\\ `` and 1-3 digit octal
    sequences per the PDF specification (ISO 32000, §7.3.4.2).
    """
    out: List[str] = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i: i + 1]
        if c != b"\\":
            out.append(c.decode("latin-1", errors="replace"))
            i += 1
            continue

        i += 1  # skip backslash
        if i >= n:
            break

        nc = s[i: i + 1]

        mapped = _ESCAPE_MAP.get(nc)
        if mapped is not None:
            out.append(mapped)
            i += 1
            continue

        # Octal escape: 1-3 octal digits (PDF spec §7.3.4.2).
        if b"0" <= nc <= b"7":
            j = i
            while j < min(i + 3, n) and b"0" <= s[j: j + 1] <= b"7":
                j += 1
            octal_str = s[i:j].decode("latin-1")
            out.append(chr(int(octal_str, 8) & 0xFF))
            i = j
            continue

        # Line continuation: backslash followed by newline → ignore both.
        if nc in (b"\n", b"\r"):
            i += 1
            if i < n and nc == b"\r" and s[i: i + 1] == b"\n":
                i += 1  # consume \r\n pair
            continue

        # Unknown escape: emit the character as-is.
        out.append(nc.decode("latin-1", errors="replace"))
        i += 1

    return "".join(out)


# ---------------------------------------------------------------------------
# Content-stream text extraction
# ---------------------------------------------------------------------------

_BT_ET_RE = re.compile(rb"BT(.+?)ET", re.DOTALL)
_STRING_RE = re.compile(rb"\((?:[^)\\]|\\.)*\)")
_TJ_RE = re.compile(rb"\[([^\]]+)\]\s*TJ")
_TJ_OPERATOR_RE = re.compile(rb"\((?:[^)\\]|\\.)*\)\s*Tj")


def extract_text_from_stream(stream: bytes) -> str:
    """Extract visible text from a PDF content stream.

    Handles both ``Tj`` (single-string) and ``TJ`` (array) text-showing
    operators.  Strings are decoded from PDF literal encoding.  Each BT/ET
    block contributes one space-separated group so word boundaries are
    preserved across operators.
    """
    parts: List[str] = []

    for bt_block in _BT_ET_RE.finditer(stream):
        block = bt_block.group(1)
        block_parts: List[str] = []

        # (text) Tj — single literal string
        for m in _TJ_OPERATOR_RE.finditer(block):
            raw = m.group(0)
            # strip trailing whitespace + "Tj"
            s_bytes = _STRING_RE.search(raw)
            if s_bytes:
                block_parts.append(decode_pdf_string(s_bytes.group(0)[1:-1]))

        # [(text) kern (text)] TJ — array of strings and kerning numbers
        for tj_m in _TJ_RE.finditer(block):
            inner = tj_m.group(1)
            for s in _STRING_RE.finditer(inner):
                block_parts.append(decode_pdf_string(s.group(0)[1:-1]))

        text = " ".join(p for p in block_parts if p.strip())
        if text.strip():
            parts.append(text)

    return " ".join(parts)
