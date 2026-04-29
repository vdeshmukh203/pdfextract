"""Tkinter graphical user interface for pdfextract.

Launched via ``pdfextract --gui`` or the ``pdfextract-gui`` console script.
Requires Tk (ships with CPython; install ``python3-tk`` on Linux if absent).
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Optional

from .extractor import PDFExtractor
from .schema import ExtractionResult


class PDFExtractGUI:
    """Main application window for the pdfextract GUI."""

    _FORMATS = ("text", "markdown", "json")
    _PAD = {"padx": 10, "pady": 4}

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("pdfextract")
        self.root.geometry("960x720")
        self.root.minsize(720, 520)
        self._result: Optional[ExtractionResult] = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._build_input_bar()
        self._build_options_bar()
        self._build_action_bar()
        self._build_progress()
        self._build_output_area()
        self._build_status_bar()

    def _build_input_bar(self) -> None:
        frame = ttk.LabelFrame(self.root, text="PDF file", padding=8)
        frame.pack(fill=tk.X, **self._PAD)

        self.path_var = tk.StringVar()
        entry = ttk.Entry(frame, textvariable=self.path_var)
        entry.pack(side=tk.LEFT, expand=True, fill=tk.X)
        entry.bind("<Return>", lambda _: self._extract_async())

        ttk.Button(frame, text="Browse…", command=self._browse).pack(
            side=tk.LEFT, padx=(6, 0)
        )

    def _build_options_bar(self) -> None:
        frame = ttk.LabelFrame(self.root, text="Options", padding=8)
        frame.pack(fill=tk.X, **self._PAD)

        ttk.Label(frame, text="Output format:").grid(
            row=0, column=0, sticky=tk.W, padx=(0, 6)
        )
        self.fmt_var = tk.StringVar(value="text")
        for col, fmt in enumerate(self._FORMATS, start=1):
            ttk.Radiobutton(
                frame, text=fmt.capitalize(), variable=self.fmt_var, value=fmt
            ).grid(row=0, column=col, padx=4, sticky=tk.W)

        ttk.Label(frame, text="Max pages (0 = all):").grid(
            row=0, column=10, padx=(20, 4), sticky=tk.W
        )
        self.max_pages_var = tk.IntVar(value=0)
        ttk.Spinbox(
            frame,
            from_=0,
            to=9999,
            textvariable=self.max_pages_var,
            width=7,
        ).grid(row=0, column=11, sticky=tk.W)

    def _build_action_bar(self) -> None:
        frame = ttk.Frame(self.root)
        frame.pack(fill=tk.X, **self._PAD)

        self.extract_btn = ttk.Button(
            frame, text="Extract", command=self._extract_async
        )
        self.extract_btn.pack(side=tk.LEFT)
        ttk.Button(frame, text="Save…", command=self._save).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Button(frame, text="Clear", command=self._clear).pack(
            side=tk.LEFT, padx=(6, 0)
        )

    def _build_progress(self) -> None:
        self.progress = ttk.Progressbar(self.root, mode="indeterminate")
        self.progress.pack(fill=tk.X, padx=10, pady=(0, 2))

    def _build_output_area(self) -> None:
        frame = ttk.LabelFrame(self.root, text="Output", padding=4)
        frame.pack(fill=tk.BOTH, expand=True, **self._PAD)

        self.text_area = scrolledtext.ScrolledText(
            frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("Courier New", 10),
            relief=tk.FLAT,
            background="#fafafa",
        )
        self.text_area.pack(fill=tk.BOTH, expand=True)

    def _build_status_bar(self) -> None:
        frame = ttk.Frame(self.root, relief=tk.SUNKEN)
        frame.pack(fill=tk.X, side=tk.BOTTOM)

        self.info_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Ready.")

        ttk.Label(frame, textvariable=self.info_var, anchor=tk.W).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Label(frame, textvariable=self.status_var, anchor=tk.E).pack(
            side=tk.RIGHT, padx=6
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Select PDF file",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self.path_var.set(path)

    def _extract_async(self) -> None:
        path = self.path_var.get().strip()
        if not path:
            messagebox.showwarning("No file selected", "Please choose a PDF file first.")
            return
        self.extract_btn.configure(state=tk.DISABLED)
        self.progress.start(10)
        self.status_var.set("Extracting…")
        self.info_var.set("")
        threading.Thread(
            target=self._do_extract, args=(path,), daemon=True
        ).start()

    def _do_extract(self, path: str) -> None:
        try:
            extractor = PDFExtractor(path, max_pages=self.max_pages_var.get())
            result = extractor.extract()
            self._result = result
            fmt = self.fmt_var.get()
            if fmt == "json":
                content = result.to_json()
            elif fmt == "markdown":
                content = result.to_markdown()
            else:
                content = result.full_text or "(No text could be extracted)"
            info = f"Pages: {result.page_count}  |  Words: {result.word_count}"
            if result.errors:
                info += f"  |  Warnings: {len(result.errors)}"
            self.root.after(0, self._on_success, content, info, result.errors)
        except Exception as exc:  # noqa: BLE001
            self.root.after(0, self._on_error, str(exc))

    def _on_success(self, content: str, info: str, errors: list) -> None:
        self.progress.stop()
        self.extract_btn.configure(state=tk.NORMAL)
        self.status_var.set("Done.")
        self.info_var.set(info)
        self._set_text(content)
        if errors:
            messagebox.showwarning(
                "Extraction warnings",
                "One or more issues occurred during extraction:\n\n"
                + "\n".join(f"• {e}" for e in errors[:8]),
            )

    def _on_error(self, msg: str) -> None:
        self.progress.stop()
        self.extract_btn.configure(state=tk.NORMAL)
        self.status_var.set("Error.")
        messagebox.showerror("Extraction failed", msg)

    def _set_text(self, content: str) -> None:
        self.text_area.configure(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert(tk.END, content)
        self.text_area.configure(state=tk.DISABLED)

    def _save(self) -> None:
        content = self.text_area.get("1.0", tk.END).strip()
        if not content:
            messagebox.showinfo("Nothing to save", "Run an extraction first.")
            return
        fmt = self.fmt_var.get()
        ext_map = {"text": ".txt", "markdown": ".md", "json": ".json"}
        path = filedialog.asksaveasfilename(
            defaultextension=ext_map.get(fmt, ".txt"),
            filetypes=[
                ("Text files", "*.txt"),
                ("Markdown files", "*.md"),
                ("JSON files", "*.json"),
                ("All files", "*.*"),
            ],
        )
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            self.status_var.set(f"Saved → {path}")

    def _clear(self) -> None:
        self._set_text("")
        self.info_var.set("")
        self.status_var.set("Ready.")
        self._result = None

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        self.root.mainloop()


def _gui() -> None:
    """Launch the pdfextract graphical interface."""
    PDFExtractGUI().run()
