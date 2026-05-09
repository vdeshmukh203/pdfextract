"""
Tkinter GUI for pdfextract.

Provides a simple desktop interface for selecting a PDF file, choosing output
format and page limits, running extraction, previewing results, and saving
output to disk.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
except ImportError:
    tk = None  # type: ignore[assignment]


def _check_tk() -> None:
    if tk is None:
        print(
            "Error: tkinter is not available in this Python environment.\n"
            "On Debian/Ubuntu: sudo apt-get install python3-tk\n"
            "On Fedora:        sudo dnf install python3-tkinter",
            file=sys.stderr,
        )
        sys.exit(1)


class _App(tk.Tk):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.title("pdfextract")
        self.resizable(True, True)
        self.minsize(720, 520)
        self._result = None
        self._build_ui()
        self._center_window()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # ── Top controls ──────────────────────────────────────────────
        ctrl = ttk.Frame(self, padding=8)
        ctrl.grid(row=0, column=0, sticky="ew")
        ctrl.columnconfigure(1, weight=1)

        ttk.Label(ctrl, text="PDF File:").grid(row=0, column=0, sticky="w")
        self._path_var = tk.StringVar()
        ttk.Entry(ctrl, textvariable=self._path_var, width=55).grid(
            row=0, column=1, sticky="ew", padx=(4, 4)
        )
        ttk.Button(ctrl, text="Browse…", command=self._browse).grid(row=0, column=2)

        ttk.Label(ctrl, text="Format:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._fmt_var = tk.StringVar(value="text")
        fmt_frame = ttk.Frame(ctrl)
        fmt_frame.grid(row=1, column=1, sticky="w", pady=(6, 0))
        for fmt in ("text", "markdown", "json"):
            ttk.Radiobutton(
                fmt_frame, text=fmt.capitalize(), variable=self._fmt_var, value=fmt
            ).pack(side="left", padx=4)

        ttk.Label(ctrl, text="Max pages (0=all):").grid(
            row=2, column=0, sticky="w", pady=(6, 0)
        )
        self._pages_var = tk.IntVar(value=0)
        ttk.Spinbox(ctrl, from_=0, to=9999, textvariable=self._pages_var, width=6).grid(
            row=2, column=1, sticky="w", padx=(4, 0), pady=(6, 0)
        )

        btn_row = ttk.Frame(ctrl)
        btn_row.grid(row=3, column=0, columnspan=3, pady=(10, 0), sticky="e")
        ttk.Button(btn_row, text="Extract", command=self._run_extract).pack(
            side="left", padx=4
        )
        ttk.Button(btn_row, text="Save Output…", command=self._save_output).pack(
            side="left", padx=4
        )
        ttk.Button(btn_row, text="Clear", command=self._clear).pack(side="left", padx=4)

        # ── Separator ─────────────────────────────────────────────────
        ttk.Separator(self, orient="horizontal").grid(row=0, column=0, sticky="ew", pady=(0, 0))

        # ── Output area ───────────────────────────────────────────────
        output_frame = ttk.Frame(self, padding=(8, 0, 8, 8))
        output_frame.grid(row=1, column=0, sticky="nsew")
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(1, weight=1)

        self._info_var = tk.StringVar(value="Ready.")
        ttk.Label(output_frame, textvariable=self._info_var, anchor="w").grid(
            row=0, column=0, sticky="ew", pady=(4, 2)
        )

        self._text = scrolledtext.ScrolledText(
            output_frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("Courier New", 10) if sys.platform == "win32" else ("Monospace", 10),
            relief=tk.SUNKEN,
            borderwidth=1,
        )
        self._text.grid(row=1, column=0, sticky="nsew")

        # ── Status bar ────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self._status_var, relief=tk.SUNKEN, anchor="w").grid(
            row=2, column=0, sticky="ew"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _center_window(self) -> None:
        self.update_idletasks()
        w, h = 820, 600
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)

    def _set_output(self, text: str) -> None:
        self._text.config(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        self._text.insert(tk.END, text)
        self._text.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Select PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self._path_var.set(path)

    def _clear(self) -> None:
        self._set_output("")
        self._info_var.set("Ready.")
        self._set_status("")
        self._result = None

    def _run_extract(self) -> None:
        path = self._path_var.get().strip()
        if not path:
            messagebox.showwarning("No file", "Please select a PDF file first.")
            return
        fmt = self._fmt_var.get()
        max_pages = self._pages_var.get()

        self._info_var.set("Extracting…")
        self._set_status("Working…")
        self._set_output("")
        self.update_idletasks()

        def _worker() -> None:
            from .extractor import PDFExtractor

            try:
                extractor = PDFExtractor(path, max_pages=max_pages)
                result = extractor.extract()
                self._result = result

                if fmt == "json":
                    out = result.to_json()
                elif fmt == "markdown":
                    out = result.to_markdown()
                else:
                    out = result.full_text

                info = (
                    f"Pages: {result.page_count}  |  Words: {result.word_count}"
                    + (f"  |  Metadata: {len(result.metadata)} fields" if result.metadata else "")
                    + (f"  |  Warnings: {len(result.errors)}" if result.errors else "")
                )
                self.after(0, lambda: self._info_var.set(info))
                self.after(0, lambda: self._set_output(out or "(no text extracted)"))
                self.after(0, lambda: self._set_status("Done."))

            except FileNotFoundError as exc:
                self.after(0, lambda: messagebox.showerror("File not found", str(exc)))
                self.after(0, lambda: self._set_status("Error."))
                self.after(0, lambda: self._info_var.set("Error."))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: messagebox.showerror("Extraction error", str(exc)))
                self.after(0, lambda: self._set_status("Error."))
                self.after(0, lambda: self._info_var.set("Error."))

        threading.Thread(target=_worker, daemon=True).start()

    def _save_output(self) -> None:
        content = self._text.get("1.0", tk.END).strip()
        if not content:
            messagebox.showinfo("Nothing to save", "Extract a PDF first.")
            return
        fmt = self._fmt_var.get()
        ext_map = {"text": ".txt", "markdown": ".md", "json": ".json"}
        filetypes = {
            "text": [("Text files", "*.txt"), ("All files", "*.*")],
            "markdown": [("Markdown files", "*.md"), ("All files", "*.*")],
            "json": [("JSON files", "*.json"), ("All files", "*.*")],
        }
        path = filedialog.asksaveasfilename(
            defaultextension=ext_map[fmt],
            filetypes=filetypes[fmt],
            title="Save extracted text",
        )
        if path:
            Path(path).write_text(content, encoding="utf-8")
            self._set_status(f"Saved to {path}")


def launch() -> None:
    """Entry point for the pdfextract-gui command."""
    _check_tk()
    app = _App()
    app.mainloop()


if __name__ == "__main__":
    launch()
