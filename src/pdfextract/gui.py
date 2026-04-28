"""Tkinter GUI for pdfextract."""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Optional

from ._extractor import PDFExtractor


def launch_gui() -> None:
    """Create and run the pdfextract GUI (blocking call)."""
    app = PDFExtractApp()
    app.mainloop()


class PDFExtractApp(tk.Tk):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()

        self.title("pdfextract")
        self.resizable(True, True)
        self.minsize(700, 520)
        self.geometry("900x640")

        self._pdf_path: Optional[Path] = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # ── Toolbar ──────────────────────────────────────────────────────
        toolbar = ttk.Frame(self, padding=6)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(1, weight=1)

        ttk.Button(toolbar, text="Open PDF…", command=self._open_pdf).grid(
            row=0, column=0, padx=(0, 6)
        )

        self._path_var = tk.StringVar(value="No file selected")
        ttk.Label(toolbar, textvariable=self._path_var, anchor="w").grid(
            row=0, column=1, sticky="ew"
        )

        # ── Options bar ──────────────────────────────────────────────────
        opts = ttk.Frame(self, padding=(6, 0, 6, 6))
        opts.grid(row=1, column=0, sticky="ew")

        ttk.Label(opts, text="Format:").grid(row=0, column=0, padx=(0, 4))
        self._fmt_var = tk.StringVar(value="text")
        fmt_cb = ttk.Combobox(
            opts,
            textvariable=self._fmt_var,
            values=["text", "markdown", "json"],
            state="readonly",
            width=10,
        )
        fmt_cb.grid(row=0, column=1, padx=(0, 16))

        ttk.Label(opts, text="Max pages (0 = all):").grid(row=0, column=2, padx=(0, 4))
        self._maxpages_var = tk.StringVar(value="0")
        ttk.Entry(opts, textvariable=self._maxpages_var, width=6).grid(row=0, column=3, padx=(0, 16))

        self._extract_btn = ttk.Button(
            opts, text="Extract", command=self._start_extraction
        )
        self._extract_btn.grid(row=0, column=4, padx=(0, 6))

        ttk.Button(opts, text="Save output…", command=self._save_output).grid(
            row=0, column=5
        )

        # ── Output area ──────────────────────────────────────────────────
        output_frame = ttk.Frame(self, padding=(6, 0, 6, 0))
        output_frame.grid(row=2, column=0, sticky="nsew")
        output_frame.rowconfigure(0, weight=1)
        output_frame.columnconfigure(0, weight=1)

        self._output_text = scrolledtext.ScrolledText(
            output_frame,
            wrap=tk.WORD,
            font=("Courier New", 10),
            state=tk.DISABLED,
            relief=tk.FLAT,
            borderwidth=1,
        )
        self._output_text.grid(row=0, column=0, sticky="nsew")

        # ── Status bar ───────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="Ready.  Open a PDF file to begin.")
        status_bar = ttk.Label(
            self,
            textvariable=self._status_var,
            relief=tk.SUNKEN,
            anchor="w",
            padding=(4, 2),
        )
        status_bar.grid(row=3, column=0, sticky="ew")

        # ── Progress bar ─────────────────────────────────────────────────
        self._progress = ttk.Progressbar(self, mode="indeterminate")
        self._progress.grid(row=4, column=0, sticky="ew")
        self._progress.grid_remove()  # hidden until extraction starts

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _open_pdf(self) -> None:
        path_str = filedialog.askopenfilename(
            title="Open PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not path_str:
            return
        self._pdf_path = Path(path_str)
        self._path_var.set(str(self._pdf_path))
        self._set_status(f"Loaded: {self._pdf_path.name}")
        self._clear_output()

    def _start_extraction(self) -> None:
        if self._pdf_path is None:
            messagebox.showwarning("No file", "Please open a PDF file first.")
            return

        try:
            max_pages = int(self._maxpages_var.get())
        except ValueError:
            messagebox.showerror("Invalid input", "'Max pages' must be an integer.")
            return

        self._extract_btn.configure(state=tk.DISABLED)
        self._progress.grid()
        self._progress.start(10)
        self._clear_output()
        self._set_status("Extracting…")

        thread = threading.Thread(
            target=self._run_extraction,
            args=(self._pdf_path, self._fmt_var.get(), max_pages),
            daemon=True,
        )
        thread.start()

    def _run_extraction(self, path: Path, fmt: str, max_pages: int) -> None:
        try:
            result = PDFExtractor(str(path), max_pages=max_pages).extract()

            if fmt == "json":
                output = result.to_json()
            elif fmt == "markdown":
                output = result.to_markdown()
            else:
                output = result.full_text

            summary = (
                f"Done — {result.page_count} page(s), "
                f"{result.word_count:,} word(s)"
            )
            if result.errors:
                summary += f"  |  {len(result.errors)} warning(s)"

            self.after(0, self._on_extraction_done, output, summary)

        except Exception as exc:  # pragma: no cover
            self.after(0, self._on_extraction_error, str(exc))

    def _on_extraction_done(self, text: str, status: str) -> None:
        self._write_output(text)
        self._set_status(status)
        self._progress.stop()
        self._progress.grid_remove()
        self._extract_btn.configure(state=tk.NORMAL)

    def _on_extraction_error(self, message: str) -> None:  # pragma: no cover
        messagebox.showerror("Extraction failed", message)
        self._set_status("Extraction failed.")
        self._progress.stop()
        self._progress.grid_remove()
        self._extract_btn.configure(state=tk.NORMAL)

    def _save_output(self) -> None:
        content = self._output_text.get("1.0", tk.END).strip()
        if not content:
            messagebox.showinfo("Nothing to save", "Extract a PDF first.")
            return

        fmt = self._fmt_var.get()
        ext_map = {"text": ".txt", "markdown": ".md", "json": ".json"}
        default_ext = ext_map.get(fmt, ".txt")

        initial = (self._pdf_path.stem if self._pdf_path else "output") + default_ext
        path_str = filedialog.asksaveasfilename(
            title="Save output",
            initialfile=initial,
            defaultextension=default_ext,
            filetypes=[
                ("Text files", "*.txt"),
                ("Markdown files", "*.md"),
                ("JSON files", "*.json"),
                ("All files", "*.*"),
            ],
        )
        if not path_str:
            return

        Path(path_str).write_text(content, encoding="utf-8")
        self._set_status(f"Saved to {path_str}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _clear_output(self) -> None:
        self._output_text.configure(state=tk.NORMAL)
        self._output_text.delete("1.0", tk.END)
        self._output_text.configure(state=tk.DISABLED)

    def _write_output(self, text: str) -> None:
        self._output_text.configure(state=tk.NORMAL)
        self._output_text.insert(tk.END, text)
        self._output_text.configure(state=tk.DISABLED)

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)
