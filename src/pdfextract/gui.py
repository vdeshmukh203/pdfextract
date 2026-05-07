"""
pdfextract GUI — Tkinter-based graphical interface for pdfextract.

Launch with ``pdfextract-gui`` (after installation) or
``python -m pdfextract.gui``.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from pdfextract import ExtractionResult, PDFExtractor, __version__, extract_pdf


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------


class _App:
    """Main GUI application."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(f"pdfextract {__version__}")
        root.geometry("900x640")
        root.minsize(640, 480)
        self._last_result: Optional[ExtractionResult] = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # ── File selection row ──────────────────────────────────────────
        file_row = ttk.Frame(self.root, padding=(8, 8, 8, 0))
        file_row.pack(fill="x")

        ttk.Label(file_row, text="PDF file:").pack(side="left")
        self._path_var = tk.StringVar()
        ttk.Entry(file_row, textvariable=self._path_var, width=60).pack(
            side="left", padx=(4, 4), expand=True, fill="x"
        )
        ttk.Button(file_row, text="Browse…", command=self._browse).pack(side="left")

        # ── Options row ─────────────────────────────────────────────────
        opts = ttk.LabelFrame(self.root, text="Options", padding=(8, 4))
        opts.pack(fill="x", padx=8, pady=4)

        ttk.Label(opts, text="Output format:").grid(row=0, column=0, sticky="w")
        self._fmt_var = tk.StringVar(value="text")
        for col, fmt in enumerate(("text", "markdown", "json"), start=1):
            ttk.Radiobutton(opts, text=fmt, variable=self._fmt_var, value=fmt).grid(
                row=0, column=col, padx=6, sticky="w"
            )

        ttk.Label(opts, text="Max pages (0 = all):").grid(
            row=0, column=5, padx=(24, 4), sticky="w"
        )
        self._pages_var = tk.IntVar(value=0)
        ttk.Spinbox(
            opts, from_=0, to=9999, textvariable=self._pages_var, width=6
        ).grid(row=0, column=6, sticky="w")

        opts.columnconfigure(4, weight=1)

        # ── Action buttons ──────────────────────────────────────────────
        btn_row = ttk.Frame(self.root, padding=(8, 0))
        btn_row.pack(fill="x")

        self._extract_btn = ttk.Button(
            btn_row, text="Extract", command=self._start_extract
        )
        self._extract_btn.pack(side="left")
        ttk.Button(btn_row, text="Save output…", command=self._save).pack(
            side="left", padx=4
        )
        ttk.Button(btn_row, text="Clear", command=self._clear).pack(side="left")

        self._status_var = tk.StringVar(value="Ready.")
        ttk.Label(btn_row, textvariable=self._status_var, foreground="grey").pack(
            side="right"
        )

        # ── Metadata panel (collapsible label-frame) ────────────────────
        self._meta_frame = ttk.LabelFrame(
            self.root, text="Metadata", padding=(8, 4)
        )
        self._meta_frame.pack(fill="x", padx=8, pady=(0, 4))
        self._meta_text = tk.Text(
            self._meta_frame, height=3, state="disabled",
            font=("TkDefaultFont", 9), relief="flat",
            background=self.root.cget("background"),
        )
        self._meta_text.pack(fill="x")

        # ── Output text area ────────────────────────────────────────────
        self._output = scrolledtext.ScrolledText(
            self.root, wrap="word", font=("Courier", 10), undo=True
        )
        self._output.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # ── Progress bar ────────────────────────────────────────────────
        self._progress = ttk.Progressbar(self.root, mode="indeterminate")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Select a PDF file",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self._path_var.set(path)

    def _start_extract(self) -> None:
        path = self._path_var.get().strip()
        if not path:
            messagebox.showwarning("No file selected", "Please select a PDF file first.")
            return
        self._extract_btn.configure(state="disabled")
        self._status_var.set("Extracting…")
        self._output.delete("1.0", "end")
        self._set_meta("")
        self._progress.pack(fill="x", padx=8, pady=(0, 4))
        self._progress.start(10)
        threading.Thread(
            target=self._extract_worker,
            args=(path, self._fmt_var.get(), self._pages_var.get()),
            daemon=True,
        ).start()

    def _extract_worker(self, path: str, fmt: str, max_pages: int) -> None:
        try:
            extractor = PDFExtractor(path, max_pages=max_pages)
            result = extractor.extract()
            if fmt == "json":
                import json
                text = json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
            elif fmt == "markdown":
                text = result.to_markdown()
            else:
                text = result.full_text
            self.root.after(0, self._on_success, result, text)
        except Exception as exc:
            self.root.after(0, self._on_error, str(exc))

    def _on_success(self, result: ExtractionResult, text: str) -> None:
        self._progress.stop()
        self._progress.pack_forget()
        self._output.insert("end", text or "(no text extracted)")
        meta_lines = [f"{k}: {v}" for k, v in result.metadata.items()]
        if result.errors:
            meta_lines.append("errors: " + "; ".join(result.errors))
        self._set_meta("\n".join(meta_lines) if meta_lines else "(no metadata)")
        pages = result.page_count
        words = result.word_count
        self._status_var.set(f"Done — {pages} page(s), {words} word(s).")
        self._extract_btn.configure(state="normal")
        self._last_result = result

    def _on_error(self, msg: str) -> None:
        self._progress.stop()
        self._progress.pack_forget()
        self._output.insert("end", f"ERROR: {msg}\n")
        self._status_var.set("Failed.")
        self._extract_btn.configure(state="normal")

    def _save(self) -> None:
        text = self._output.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("Nothing to save", "Run an extraction first.")
            return
        fmt = self._fmt_var.get()
        default_ext = {"json": ".json", "markdown": ".md"}.get(fmt, ".txt")
        dest = filedialog.asksaveasfilename(defaultextension=default_ext)
        if dest:
            Path(dest).write_text(text, encoding="utf-8")
            self._status_var.set(f"Saved to {Path(dest).name}")

    def _clear(self) -> None:
        self._output.delete("1.0", "end")
        self._set_meta("")
        self._status_var.set("Ready.")
        self._last_result = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_meta(self, text: str) -> None:
        self._meta_text.configure(state="normal")
        self._meta_text.delete("1.0", "end")
        if text:
            self._meta_text.insert("end", text)
        self._meta_text.configure(state="disabled")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Launch the pdfextract GUI."""
    root = tk.Tk()
    _App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
