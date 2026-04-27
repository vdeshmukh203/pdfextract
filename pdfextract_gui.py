"""
pdfextract_gui: Tkinter graphical front-end for the pdfextract library.

Provides a self-contained GUI that lets users browse for a PDF, choose an
output format, set a page limit, run extraction in a background thread (so
the interface stays responsive), and save the result to a file.

Launch via the CLI flag::

    pdfextract --gui

or directly::

    python pdfextract_gui.py
"""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Optional

import pdfextract


# ---------------------------------------------------------------------------
# Colour / style constants
# ---------------------------------------------------------------------------

_BG = "#f5f5f5"
_ACCENT = "#2c6fad"
_ACCENT_FG = "#ffffff"
_TEXT_BG = "#ffffff"
_FONT_MONO = ("Courier", 10)
_FONT_UI = ("Helvetica", 10)
_FONT_TITLE = ("Helvetica", 13, "bold")
_PAD = 8


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class PDFExtractApp(tk.Tk):
    """Main application window for the pdfextract GUI."""

    def __init__(self) -> None:
        super().__init__()
        self.title("PDFExtract — Scientific PDF Text Extractor")
        self.resizable(True, True)
        self.configure(bg=_BG)
        self.minsize(680, 520)

        self._pdf_path: Optional[str] = None
        self._result_text: str = ""
        self._busy = False

        self._build_ui()
        self._center_window(800, 620)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._build_header()
        self._build_file_row()
        self._build_options_row()
        self._build_action_row()
        self._build_status_bar()
        self._build_result_area()
        self._build_footer()

    def _build_header(self) -> None:
        frm = tk.Frame(self, bg=_ACCENT, pady=10)
        frm.pack(fill="x")
        tk.Label(
            frm,
            text="PDFExtract",
            font=_FONT_TITLE,
            bg=_ACCENT,
            fg=_ACCENT_FG,
        ).pack(side="left", padx=14)
        tk.Label(
            frm,
            text="Pure-Python scientific PDF extractor",
            font=_FONT_UI,
            bg=_ACCENT,
            fg="#cce3f7",
        ).pack(side="left", padx=4)

    def _build_file_row(self) -> None:
        frm = tk.Frame(self, bg=_BG, pady=6)
        frm.pack(fill="x", padx=_PAD)

        tk.Label(frm, text="PDF file:", font=_FONT_UI, bg=_BG, width=9, anchor="w").pack(side="left")

        self._file_var = tk.StringVar()
        entry = tk.Entry(frm, textvariable=self._file_var, font=_FONT_UI, relief="solid", bd=1)
        entry.pack(side="left", fill="x", expand=True, padx=(4, 4))

        tk.Button(
            frm,
            text="Browse…",
            font=_FONT_UI,
            command=self._browse,
            relief="solid",
            bd=1,
            cursor="hand2",
        ).pack(side="left")

    def _build_options_row(self) -> None:
        frm = tk.Frame(self, bg=_BG, pady=4)
        frm.pack(fill="x", padx=_PAD)

        # Output format
        tk.Label(frm, text="Format:", font=_FONT_UI, bg=_BG).pack(side="left")
        self._fmt_var = tk.StringVar(value="text")
        for fmt in ("text", "markdown", "json"):
            tk.Radiobutton(
                frm,
                text=fmt,
                variable=self._fmt_var,
                value=fmt,
                font=_FONT_UI,
                bg=_BG,
                activebackground=_BG,
                cursor="hand2",
            ).pack(side="left", padx=(6, 0))

        # Max pages
        tk.Label(frm, text="   Max pages:", font=_FONT_UI, bg=_BG).pack(side="left")
        self._max_pages_var = tk.IntVar(value=0)
        spin = tk.Spinbox(
            frm,
            from_=0,
            to=9999,
            textvariable=self._max_pages_var,
            width=5,
            font=_FONT_UI,
            relief="solid",
            bd=1,
        )
        spin.pack(side="left", padx=4)
        tk.Label(frm, text="(0 = all)", font=("Helvetica", 9), bg=_BG, fg="#666").pack(side="left")

    def _build_action_row(self) -> None:
        frm = tk.Frame(self, bg=_BG, pady=4)
        frm.pack(fill="x", padx=_PAD)

        self._extract_btn = tk.Button(
            frm,
            text="Extract PDF",
            font=("Helvetica", 10, "bold"),
            bg=_ACCENT,
            fg=_ACCENT_FG,
            activebackground="#1e5080",
            activeforeground=_ACCENT_FG,
            relief="flat",
            padx=16,
            pady=5,
            cursor="hand2",
            command=self._start_extraction,
        )
        self._extract_btn.pack(side="left")

        tk.Button(
            frm,
            text="Clear",
            font=_FONT_UI,
            relief="solid",
            bd=1,
            padx=10,
            pady=4,
            cursor="hand2",
            command=self._clear,
        ).pack(side="left", padx=8)

        self._save_btn = tk.Button(
            frm,
            text="Save result…",
            font=_FONT_UI,
            relief="solid",
            bd=1,
            padx=10,
            pady=4,
            cursor="hand2",
            command=self._save_result,
            state="disabled",
        )
        self._save_btn.pack(side="left")

    def _build_status_bar(self) -> None:
        self._status_var = tk.StringVar(value="Ready — open a PDF file to begin.")
        frm = tk.Frame(self, bg="#e0e0e0", relief="sunken", bd=1)
        frm.pack(fill="x", padx=_PAD, pady=(2, 0))
        tk.Label(
            frm,
            textvariable=self._status_var,
            font=("Helvetica", 9),
            bg="#e0e0e0",
            anchor="w",
            padx=6,
        ).pack(fill="x")

    def _build_result_area(self) -> None:
        frm = tk.Frame(self, bg=_BG)
        frm.pack(fill="both", expand=True, padx=_PAD, pady=6)

        header = tk.Frame(frm, bg=_BG)
        header.pack(fill="x")
        tk.Label(header, text="Extracted text", font=("Helvetica", 9, "bold"), bg=_BG, anchor="w").pack(side="left")
        self._stats_var = tk.StringVar(value="")
        tk.Label(header, textvariable=self._stats_var, font=("Helvetica", 9), bg=_BG, fg="#555", anchor="e").pack(side="right")

        self._text_area = scrolledtext.ScrolledText(
            frm,
            font=_FONT_MONO,
            bg=_TEXT_BG,
            relief="solid",
            bd=1,
            wrap="word",
            state="disabled",
        )
        self._text_area.pack(fill="both", expand=True, pady=(4, 0))

    def _build_footer(self) -> None:
        frm = tk.Frame(self, bg=_BG)
        frm.pack(fill="x", padx=_PAD, pady=(0, 6))
        self._meta_var = tk.StringVar(value="")
        tk.Label(
            frm,
            textvariable=self._meta_var,
            font=("Helvetica", 9),
            bg=_BG,
            fg="#444",
            anchor="w",
            wraplength=760,
            justify="left",
        ).pack(fill="x")

    # ------------------------------------------------------------------
    # Window helpers
    # ------------------------------------------------------------------

    def _center_window(self, w: int, h: int) -> None:
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Open PDF file",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*")],
        )
        if path:
            self._file_var.set(path)
            self._pdf_path = path
            self._set_status("File loaded: %s" % Path(path).name)

    def _start_extraction(self) -> None:
        if self._busy:
            return
        path = self._file_var.get().strip()
        if not path:
            messagebox.showwarning("No file selected", "Please select a PDF file first.")
            return
        if not Path(path).exists():
            messagebox.showerror("File not found", "The file does not exist:\n%s" % path)
            return

        self._busy = True
        self._extract_btn.configure(state="disabled", text="Extracting…")
        self._save_btn.configure(state="disabled")
        self._set_status("Extracting — please wait…")
        self._set_text("")
        self._stats_var.set("")
        self._meta_var.set("")

        fmt = self._fmt_var.get()
        max_pages = self._max_pages_var.get()

        thread = threading.Thread(
            target=self._run_extraction,
            args=(path, fmt, max_pages),
            daemon=True,
        )
        thread.start()

    def _run_extraction(self, path: str, fmt: str, max_pages: int) -> None:
        """Run in background thread; update UI via ``after()``."""
        try:
            result = pdfextract.PDFExtractor(path, max_pages=max_pages).extract()
            if fmt == "json":
                import json
                text = json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
            elif fmt == "markdown":
                text = result.to_markdown()
            else:
                text = result.full_text

            stats = "pages: %d | words: %d | chars: %d" % (
                result.page_count,
                result.word_count,
                sum(p.char_count for p in result.pages),
            )

            meta_parts = []
            for k in ("title", "author", "subject"):
                if k in result.metadata:
                    meta_parts.append("%s: %s" % (k, result.metadata[k]))
            meta_str = "   |   ".join(meta_parts)

            warnings = result.errors
            self.after(0, self._on_extraction_done, text, stats, meta_str, warnings)

        except pdfextract.PDFParseError as exc:
            self.after(0, self._on_extraction_error, "PDF parse error: %s" % exc)
        except FileNotFoundError as exc:
            self.after(0, self._on_extraction_error, "File not found: %s" % exc)
        except Exception as exc:
            self.after(0, self._on_extraction_error, "Unexpected error: %s" % exc)

    def _on_extraction_done(
        self,
        text: str,
        stats: str,
        meta_str: str,
        warnings: list,
    ) -> None:
        self._result_text = text
        self._set_text(text if text else "(No extractable text found in this PDF.)")
        self._stats_var.set(stats)
        self._meta_var.set(meta_str)
        if warnings:
            self._set_status("Done with %d warning(s). " % len(warnings) + warnings[0])
        else:
            self._set_status("Extraction complete.")
        self._extract_btn.configure(state="normal", text="Extract PDF")
        self._save_btn.configure(state="normal" if text else "disabled")
        self._busy = False

    def _on_extraction_error(self, message: str) -> None:
        self._set_status("Error: " + message)
        messagebox.showerror("Extraction failed", message)
        self._extract_btn.configure(state="normal", text="Extract PDF")
        self._busy = False

    def _clear(self) -> None:
        if self._busy:
            return
        self._file_var.set("")
        self._pdf_path = None
        self._result_text = ""
        self._set_text("")
        self._stats_var.set("")
        self._meta_var.set("")
        self._save_btn.configure(state="disabled")
        self._set_status("Ready — open a PDF file to begin.")

    def _save_result(self) -> None:
        if not self._result_text:
            return
        fmt = self._fmt_var.get()
        ext_map = {"text": ".txt", "markdown": ".md", "json": ".json"}
        ext = ext_map.get(fmt, ".txt")
        path = filedialog.asksaveasfilename(
            title="Save extracted text",
            defaultextension=ext,
            filetypes=[
                ("Text files", "*.txt"),
                ("Markdown files", "*.md"),
                ("JSON files", "*.json"),
                ("All files", "*"),
            ],
        )
        if not path:
            return
        try:
            Path(path).write_text(self._result_text, encoding="utf-8")
            self._set_status("Saved to %s" % path)
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)

    def _set_text(self, text: str) -> None:
        self._text_area.configure(state="normal")
        self._text_area.delete("1.0", "end")
        if text:
            self._text_area.insert("1.0", text)
        self._text_area.configure(state="disabled")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def launch_gui() -> None:
    """Create and run the PDFExtract GUI application."""
    app = PDFExtractApp()
    app.mainloop()


if __name__ == "__main__":
    launch_gui()
