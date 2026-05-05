"""Tkinter GUI for pdfextract."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from pathlib import Path
from typing import Optional

from .extractor import extract_pdf, PDFExtractor
from .schema import PDFParseError


class PDFExtractApp(tk.Tk):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.title("pdfextract")
        self.resizable(True, True)
        self.minsize(680, 480)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # --- File row ---
        file_frame = ttk.LabelFrame(self, text="Input PDF", padding=6)
        file_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        file_frame.columnconfigure(1, weight=1)

        ttk.Label(file_frame, text="Path:").grid(row=0, column=0, sticky="w")
        self._path_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self._path_var).grid(
            row=0, column=1, sticky="ew", padx=(6, 4))
        ttk.Button(file_frame, text="Browse…", command=self._browse).grid(
            row=0, column=2)

        # --- Options row ---
        opt_frame = ttk.LabelFrame(self, text="Options", padding=6)
        opt_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=4)

        ttk.Label(opt_frame, text="Format:").grid(row=0, column=0, sticky="w")
        self._fmt_var = tk.StringVar(value="text")
        fmt_combo = ttk.Combobox(
            opt_frame, textvariable=self._fmt_var,
            values=["text", "markdown", "json"], state="readonly", width=10)
        fmt_combo.grid(row=0, column=1, sticky="w", padx=(4, 16))

        ttk.Label(opt_frame, text="Max pages (0=all):").grid(row=0, column=2, sticky="w")
        self._pages_var = tk.IntVar(value=0)
        ttk.Spinbox(opt_frame, from_=0, to=9999, textvariable=self._pages_var,
                    width=6).grid(row=0, column=3, sticky="w", padx=(4, 16))

        self._extract_btn = ttk.Button(opt_frame, text="Extract", command=self._start_extract)
        self._extract_btn.grid(row=0, column=4, padx=(0, 8))

        ttk.Button(opt_frame, text="Save…", command=self._save).grid(row=0, column=5)

        # --- Output area ---
        out_frame = ttk.LabelFrame(self, text="Output", padding=6)
        out_frame.grid(row=2, column=0, sticky="nsew", padx=8, pady=4)
        out_frame.columnconfigure(0, weight=1)
        out_frame.rowconfigure(0, weight=1)

        self._output = scrolledtext.ScrolledText(
            out_frame, wrap=tk.WORD, font=("Courier", 10), state="disabled")
        self._output.grid(row=0, column=0, sticky="nsew")

        # --- Status bar ---
        self._status_var = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self._status_var, anchor="w",
                  relief="sunken").grid(row=3, column=0, sticky="ew", padx=0, pady=0)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Select PDF file",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self._path_var.set(path)

    def _start_extract(self) -> None:
        path = self._path_var.get().strip()
        if not path:
            messagebox.showwarning("No file", "Please select a PDF file first.")
            return
        self._extract_btn.config(state="disabled")
        self._set_status("Extracting…")
        threading.Thread(target=self._run_extract, args=(path,), daemon=True).start()

    def _run_extract(self, path: str) -> None:
        fmt = self._fmt_var.get()
        max_pages = self._pages_var.get()
        try:
            extractor = PDFExtractor(path, max_pages=max_pages)
            result = extractor.extract()
            if fmt == "json":
                out = result.to_json()
            elif fmt == "markdown":
                out = result.to_markdown()
            else:
                out = result.full_text

            summary = (
                f"Done — {result.page_count} page(s), "
                f"{result.word_count} words"
                + (f", {len(result.errors)} error(s)" if result.errors else "")
            )
            if result.metadata:
                title = result.metadata.get("Title", "")
                if title:
                    summary += f" | Title: {title[:60]}"

            self.after(0, self._show_output, out, summary)
        except (PDFParseError, FileNotFoundError, OSError) as exc:
            self.after(0, self._show_error, str(exc))
        except Exception as exc:
            self.after(0, self._show_error, "Unexpected error: " + str(exc))
        finally:
            self.after(0, lambda: self._extract_btn.config(state="normal"))

    def _show_output(self, text: str, status: str) -> None:
        self._output.config(state="normal")
        self._output.delete("1.0", tk.END)
        self._output.insert(tk.END, text)
        self._output.config(state="disabled")
        self._set_status(status)

    def _show_error(self, msg: str) -> None:
        self._set_status("Error: " + msg)
        messagebox.showerror("Extraction error", msg)

    def _save(self) -> None:
        content = self._output.get("1.0", tk.END).strip()
        if not content:
            messagebox.showinfo("Nothing to save", "Extract a PDF first.")
            return
        fmt = self._fmt_var.get()
        ext_map = {"text": ".txt", "markdown": ".md", "json": ".json"}
        path = filedialog.asksaveasfilename(
            defaultextension=ext_map.get(fmt, ".txt"),
            filetypes=[("Text", "*.txt"), ("Markdown", "*.md"),
                       ("JSON", "*.json"), ("All files", "*.*")],
        )
        if path:
            Path(path).write_text(content, encoding="utf-8")
            self._set_status("Saved to " + path)

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)


def launch() -> None:
    """Start the GUI event loop."""
    app = PDFExtractApp()
    app.mainloop()


if __name__ == "__main__":
    launch()
