"""
Tkinter-based graphical user interface for pdfextract.

Launch with::

    python -m pdfextract.gui

or via the installed entry point::

    pdfextract-gui
"""
from __future__ import annotations

import threading
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk

    _HAS_TK = True
except ImportError:
    _HAS_TK = False


def _require_tk() -> None:
    if not _HAS_TK:
        raise RuntimeError(
            "tkinter is not available.\n"
            "Install it with your OS package manager, e.g.:\n"
            "  Debian/Ubuntu: sudo apt install python3-tk\n"
            "  Fedora:        sudo dnf install python3-tkinter\n"
            "  macOS (brew):  brew install python-tk"
        )


class _App:
    """Main application window."""

    def __init__(self, root: "tk.Tk") -> None:
        self.root = root
        self.root.title("PDFExtract")
        self.root.resizable(True, True)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = {"padx": 8, "pady": 4}

        # ── File selection ──────────────────────────────────────────────
        file_frame = ttk.LabelFrame(self.root, text="Input PDF")
        file_frame.pack(fill="x", **outer)

        self._file_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self._file_var, width=60).pack(
            side="left", fill="x", expand=True, padx=(6, 4), pady=6
        )
        ttk.Button(file_frame, text="Browse…", command=self._browse).pack(
            side="left", padx=(0, 6), pady=6
        )

        # ── Options ─────────────────────────────────────────────────────
        opt_frame = ttk.LabelFrame(self.root, text="Options")
        opt_frame.pack(fill="x", **outer)

        ttk.Label(opt_frame, text="Format:").pack(side="left", padx=(8, 2), pady=6)
        self._fmt_var = tk.StringVar(value="text")
        for fmt in ("text", "markdown", "json"):
            ttk.Radiobutton(
                opt_frame, text=fmt, variable=self._fmt_var, value=fmt
            ).pack(side="left", padx=4, pady=6)

        ttk.Separator(opt_frame, orient="vertical").pack(
            side="left", fill="y", padx=10
        )
        ttk.Label(opt_frame, text="Max pages (0 = all):").pack(
            side="left", padx=(4, 2)
        )
        self._max_pages_var = tk.IntVar(value=0)
        ttk.Spinbox(
            opt_frame,
            from_=0,
            to=9999,
            textvariable=self._max_pages_var,
            width=6,
        ).pack(side="left", padx=(0, 8), pady=6)

        # ── Extract button ───────────────────────────────────────────────
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill="x", **outer)
        self._extract_btn = ttk.Button(
            btn_frame, text="Extract PDF", command=self._run_extraction
        )
        self._extract_btn.pack(fill="x", ipady=4)

        # ── Output area ──────────────────────────────────────────────────
        out_frame = ttk.LabelFrame(self.root, text="Output")
        out_frame.pack(fill="both", expand=True, **outer)

        self._output = scrolledtext.ScrolledText(
            out_frame, wrap="word", font=("Courier", 10), height=22
        )
        self._output.pack(fill="both", expand=True, padx=4, pady=4)

        # ── Status bar ───────────────────────────────────────────────────
        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", **outer)

        ttk.Button(bottom, text="Save Output…", command=self._save).pack(side="left")
        self._status_var = tk.StringVar(value="Ready.")
        ttk.Label(bottom, textvariable=self._status_var, anchor="w").pack(
            side="left", fill="x", expand=True, padx=10
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Select a PDF file",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self._file_var.set(path)

    def _run_extraction(self) -> None:
        path = self._file_var.get().strip()
        if not path:
            messagebox.showwarning("No file", "Please select a PDF file first.")
            return

        self._extract_btn.state(["disabled"])
        self._status_var.set("Extracting…")
        self._output.delete("1.0", "end")

        def _worker() -> None:
            from .extractor import PDFExtractor

            try:
                result = PDFExtractor(
                    path, max_pages=self._max_pages_var.get()
                ).extract()
            except Exception as exc:
                self.root.after(0, self._on_error, str(exc))
                return

            fmt = self._fmt_var.get()
            if fmt == "json":
                text = result.to_json()
            elif fmt == "markdown":
                text = result.to_markdown()
            else:
                text = result.full_text

            summary = (
                f"Done — {result.page_count} page(s), {result.word_count} word(s)."
            )
            if result.errors:
                summary += f" [{len(result.errors)} non-fatal error(s)]"
            self.root.after(0, self._on_done, text, summary)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_done(self, text: str, summary: str) -> None:
        self._output.insert("1.0", text)
        self._status_var.set(summary)
        self._extract_btn.state(["!disabled"])

    def _on_error(self, message: str) -> None:
        messagebox.showerror("Extraction error", message)
        self._status_var.set(f"Error: {message}")
        self._extract_btn.state(["!disabled"])

    def _save(self) -> None:
        text = self._output.get("1.0", "end").rstrip()
        if not text:
            messagebox.showinfo("Nothing to save", "Extract a PDF first.")
            return
        ext_map = {"text": ".txt", "markdown": ".md", "json": ".json"}
        fmt = self._fmt_var.get()
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
            Path(path).write_text(text, encoding="utf-8")
            self._status_var.set(f"Saved to {path}")


def launch() -> None:
    """Launch the PDFExtract GUI application.

    Raises
    ------
    RuntimeError
        If tkinter is not available on this system.
    """
    _require_tk()
    root = tk.Tk()
    root.geometry("720x620")
    _App(root)
    root.mainloop()


if __name__ == "__main__":
    launch()
