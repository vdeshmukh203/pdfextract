"""Tkinter GUI for pdfextract."""
from __future__ import annotations
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .extractor import PDFExtractor


class PDFExtractApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("pdfextract")
        self.resizable(True, True)
        self.minsize(680, 520)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # ── File row ──────────────────────────────────────────────────
        file_frame = ttk.LabelFrame(self, text="Input PDF", padding=6)
        file_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        file_frame.columnconfigure(0, weight=1)

        self._file_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self._file_var).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        ttk.Button(file_frame, text="Browse…", command=self._browse).grid(
            row=0, column=1
        )

        # ── Options row ───────────────────────────────────────────────
        opt_frame = ttk.LabelFrame(self, text="Options", padding=6)
        opt_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=4)

        ttk.Label(opt_frame, text="Output format:").grid(row=0, column=0, sticky="w")
        self._fmt_var = tk.StringVar(value="text")
        fmt_cb = ttk.Combobox(
            opt_frame,
            textvariable=self._fmt_var,
            values=["text", "markdown", "json"],
            state="readonly",
            width=10,
        )
        fmt_cb.grid(row=0, column=1, padx=(4, 20), sticky="w")

        ttk.Label(opt_frame, text="Max pages (0 = all):").grid(
            row=0, column=2, sticky="w"
        )
        self._maxpages_var = tk.StringVar(value="0")
        ttk.Spinbox(
            opt_frame,
            textvariable=self._maxpages_var,
            from_=0,
            to=9999,
            width=6,
        ).grid(row=0, column=3, padx=(4, 20), sticky="w")

        self._extract_btn = ttk.Button(
            opt_frame, text="Extract", command=self._start_extraction
        )
        self._extract_btn.grid(row=0, column=4, padx=(0, 4))

        ttk.Button(opt_frame, text="Save…", command=self._save).grid(
            row=0, column=5
        )

        # ── Output area ───────────────────────────────────────────────
        out_frame = ttk.LabelFrame(self, text="Output", padding=6)
        out_frame.grid(row=2, column=0, sticky="nsew", padx=8, pady=4)
        out_frame.columnconfigure(0, weight=1)
        out_frame.rowconfigure(0, weight=1)

        self._output = scrolledtext.ScrolledText(
            out_frame, wrap=tk.WORD, font=("Courier", 10)
        )
        self._output.grid(row=0, column=0, sticky="nsew")

        # ── Status bar ────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self._status_var, anchor="w").grid(
            row=3, column=0, sticky="ew", padx=8, pady=(2, 6)
        )

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Select PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self._file_var.set(path)

    def _start_extraction(self) -> None:
        path = self._file_var.get().strip()
        if not path:
            messagebox.showwarning("No file", "Please select a PDF file first.")
            return
        if not Path(path).is_file():
            messagebox.showerror("File not found", f"Cannot find:\n{path}")
            return
        try:
            max_pages = int(self._maxpages_var.get())
        except ValueError:
            messagebox.showerror("Invalid input", "Max pages must be an integer.")
            return

        self._extract_btn.state(["disabled"])
        self._status_var.set("Extracting…")
        self._output.delete("1.0", tk.END)

        threading.Thread(
            target=self._run_extraction,
            args=(path, self._fmt_var.get(), max_pages),
            daemon=True,
        ).start()

    def _run_extraction(self, path: str, fmt: str, max_pages: int) -> None:
        try:
            result = PDFExtractor(path, max_pages=max_pages).extract()
            if fmt == "json":
                text = result.to_json()
            elif fmt == "markdown":
                text = result.to_markdown()
            else:
                text = result.full_text

            errors = result.errors
            pages = result.page_count
            words = result.word_count
        except Exception as exc:
            self.after(0, self._extraction_error, str(exc))
            return

        self.after(0, self._extraction_done, text, pages, words, errors)

    def _extraction_done(
        self, text: str, pages: int, words: int, errors: list
    ) -> None:
        self._output.insert(tk.END, text)
        msg = f"Done. {pages} page(s), {words} word(s)."
        if errors:
            msg += f"  {len(errors)} error(s): {errors[0]}"
        self._status_var.set(msg)
        self._extract_btn.state(["!disabled"])

    def _extraction_error(self, msg: str) -> None:
        messagebox.showerror("Extraction failed", msg)
        self._status_var.set("Error.")
        self._extract_btn.state(["!disabled"])

    def _save(self) -> None:
        content = self._output.get("1.0", tk.END).strip()
        if not content:
            messagebox.showinfo("Nothing to save", "Extract a PDF first.")
            return
        fmt = self._fmt_var.get()
        ext = {"markdown": ".md", "json": ".json"}.get(fmt, ".txt")
        path = filedialog.asksaveasfilename(
            defaultextension=ext,
            filetypes=[("Text", "*.txt"), ("Markdown", "*.md"), ("JSON", "*.json")],
        )
        if path:
            Path(path).write_text(content, encoding="utf-8")
            self._status_var.set(f"Saved to {path}")


def main() -> None:
    app = PDFExtractApp()
    app.mainloop()


if __name__ == "__main__":
    main()
