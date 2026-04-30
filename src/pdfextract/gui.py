"""Graphical user interface for pdfextract (requires tkinter).

Launch with the ``pdfextract-gui`` command or::

    python -m pdfextract.gui
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Optional

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
    _TKINTER_AVAILABLE = True
except ImportError:
    _TKINTER_AVAILABLE = False

from . import __version__
from .extractor import PDFExtractor, PDFParseError
from .schema import ExtractionResult


def _require_tkinter() -> None:
    if not _TKINTER_AVAILABLE:
        raise RuntimeError(
            "tkinter is not available in this Python installation.\n"
            "On Debian/Ubuntu: sudo apt-get install python3-tk\n"
            "On Fedora/RHEL:   sudo dnf install python3-tkinter\n"
            "On macOS/Windows: tkinter is bundled with standard Python."
        )


class PDFExtractorGUI:
    """Main application window for the pdfextract GUI.

    Parameters
    ----------
    root:
        Parent ``tk.Tk`` window.
    """

    def __init__(self, root: "tk.Tk") -> None:
        _require_tkinter()
        self.root = root
        self.root.title(f"pdfextract {__version__} — PDF Text Extractor")
        self.root.minsize(720, 520)
        self._result: Optional[ExtractionResult] = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        # ── Input ──────────────────────────────────────────────────────
        input_frame = ttk.LabelFrame(self.root, text="Input PDF", padding=8)
        input_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        input_frame.columnconfigure(1, weight=1)

        ttk.Label(input_frame, text="File:").grid(row=0, column=0, sticky="w")
        self.file_var = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self.file_var).grid(
            row=0, column=1, sticky="ew", padx=(6, 4)
        )
        ttk.Button(input_frame, text="Browse…", command=self._browse).grid(
            row=0, column=2
        )

        # ── Options ────────────────────────────────────────────────────
        opt_frame = ttk.LabelFrame(self.root, text="Options", padding=8)
        opt_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=4)

        ttk.Label(opt_frame, text="Format:").grid(row=0, column=0, sticky="w")
        self.fmt_var = tk.StringVar(value="text")
        ttk.Combobox(
            opt_frame,
            textvariable=self.fmt_var,
            values=["text", "markdown", "json"],
            state="readonly",
            width=12,
        ).grid(row=0, column=1, sticky="w", padx=(6, 20))

        ttk.Label(opt_frame, text="Max pages (0 = all):").grid(
            row=0, column=2, sticky="w"
        )
        self.max_pages_var = tk.IntVar(value=0)
        ttk.Spinbox(
            opt_frame,
            from_=0,
            to=9999,
            textvariable=self.max_pages_var,
            width=6,
        ).grid(row=0, column=3, sticky="w", padx=(6, 20))

        self.extract_btn = ttk.Button(
            opt_frame, text="Extract", command=self._start_extract
        )
        self.extract_btn.grid(row=0, column=4, padx=(10, 0))

        # ── Output ─────────────────────────────────────────────────────
        out_frame = ttk.LabelFrame(self.root, text="Output", padding=8)
        out_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=4)
        out_frame.columnconfigure(0, weight=1)
        out_frame.rowconfigure(0, weight=1)

        self.output_text = scrolledtext.ScrolledText(
            out_frame,
            wrap=tk.WORD,
            font=("Courier", 10),
            state=tk.DISABLED,
        )
        self.output_text.grid(row=0, column=0, sticky="nsew")

        btn_bar = ttk.Frame(out_frame)
        btn_bar.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        ttk.Button(btn_bar, text="Save output…", command=self._save).pack(
            side=tk.LEFT
        )
        ttk.Button(btn_bar, text="Clear", command=self._clear).pack(
            side=tk.LEFT, padx=6
        )

        # ── Status bar ─────────────────────────────────────────────────
        status_frame = ttk.Frame(self.root)
        status_frame.grid(row=3, column=0, sticky="ew")
        status_frame.columnconfigure(0, weight=1)

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(
            status_frame,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(4, 2),
        ).grid(row=0, column=0, sticky="ew")

        self.progress = ttk.Progressbar(status_frame, mode="indeterminate", length=120)
        self.progress.grid(row=0, column=1, padx=(4, 2), pady=2)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Select a PDF file",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self.file_var.set(path)

    def _start_extract(self) -> None:
        path = self.file_var.get().strip()
        if not path:
            messagebox.showwarning("No file selected", "Please select a PDF file first.")
            return
        if not Path(path).is_file():
            messagebox.showerror("File not found", f"Cannot find:\n{path}")
            return

        self.extract_btn.config(state=tk.DISABLED)
        self.progress.start(10)
        self._set_status("Extracting…")
        self._clear()
        threading.Thread(
            target=self._extract_worker, args=(path,), daemon=True
        ).start()

    def _extract_worker(self, path: str) -> None:
        try:
            extractor = PDFExtractor(path, max_pages=self.max_pages_var.get())
            result = extractor.extract()
            self._result = result

            fmt = self.fmt_var.get()
            if fmt == "json":
                text = result.to_json()
            elif fmt == "markdown":
                text = result.to_markdown()
            else:
                text = result.full_text or "(No text could be extracted from this PDF.)"

            summary = f"Done — {result.page_count} page(s), {result.word_count} word(s)"
            if result.errors:
                summary += f", {len(result.errors)} warning(s)"

            self.root.after(0, self._on_done, text, summary)
        except PDFParseError as exc:
            self.root.after(0, self._on_error, str(exc))
        except Exception as exc:
            self.root.after(0, self._on_error, f"Unexpected error: {exc}")

    def _on_done(self, text: str, summary: str) -> None:
        self._write_output(text)
        self._set_status(summary)
        self.progress.stop()
        self.extract_btn.config(state=tk.NORMAL)

    def _on_error(self, message: str) -> None:
        self._set_status(f"Error: {message}")
        self.progress.stop()
        self.extract_btn.config(state=tk.NORMAL)
        messagebox.showerror("Extraction error", message)

    def _save(self) -> None:
        content = self.output_text.get("1.0", tk.END).strip()
        if not content:
            messagebox.showinfo("Nothing to save", "Extract a PDF first.")
            return
        fmt = self.fmt_var.get()
        ext = {"text": ".txt", "markdown": ".md", "json": ".json"}.get(fmt, ".txt")
        path = filedialog.asksaveasfilename(
            defaultextension=ext,
            filetypes=[
                ("Text files", "*.txt"),
                ("Markdown files", "*.md"),
                ("JSON files", "*.json"),
                ("All files", "*.*"),
            ],
        )
        if path:
            Path(path).write_text(content, encoding="utf-8")
            self._set_status(f"Saved to {path}")

    def _clear(self) -> None:
        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete("1.0", tk.END)
        self.output_text.config(state=tk.DISABLED)

    def _write_output(self, text: str) -> None:
        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert(tk.END, text)
        self.output_text.config(state=tk.DISABLED)

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)


def main() -> None:
    """Launch the pdfextract graphical interface."""
    _require_tkinter()
    root = tk.Tk()
    PDFExtractorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
