"""
pdfextract GUI — a simple Tkinter front-end for pdfextract.

Launch via:
    python pdfextract_gui.py
    pdfextract gui            # if installed via pip
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
except ImportError as exc:
    raise SystemExit(
        "Tkinter is not available in this Python installation.\n"
        "On Debian/Ubuntu: sudo apt-get install python3-tk\n"
        "On Fedora/RHEL:   sudo dnf install python3-tkinter\n"
        "On macOS/Windows: Tkinter is included with the standard installer."
    ) from exc

import pdfextract


class PDFExtractApp(tk.Tk):
    """Main application window."""

    PAD = 8
    OUT_FONT = ("Courier New", 10)
    MIN_W, MIN_H = 740, 560

    def __init__(self) -> None:
        super().__init__()
        self.title(f"pdfextract {pdfextract.__version__}")
        self.minsize(self.MIN_W, self.MIN_H)
        self.resizable(True, True)
        self._result: Optional[pdfextract.ExtractionResult] = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        p = self.PAD

        # ── top control bar ───────────────────────────────────────────
        ctrl = ttk.Frame(self, padding=p)
        ctrl.pack(fill="x", padx=p, pady=(p, 0))

        ttk.Label(ctrl, text="PDF file:").grid(row=0, column=0, sticky="w")
        self._path_var = tk.StringVar()
        self._path_entry = ttk.Entry(ctrl, textvariable=self._path_var, width=52)
        self._path_entry.grid(row=0, column=1, padx=(4, 4), sticky="ew")
        ttk.Button(ctrl, text="Browse…", command=self._browse).grid(row=0, column=2)

        ttk.Label(ctrl, text="Format:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._fmt_var = tk.StringVar(value="text")
        fmt_frame = ttk.Frame(ctrl)
        fmt_frame.grid(row=1, column=1, sticky="w", pady=(4, 0))
        for fmt in ("text", "markdown", "json"):
            ttk.Radiobutton(
                fmt_frame, text=fmt.capitalize(), variable=self._fmt_var, value=fmt
            ).pack(side="left", padx=(0, 10))

        ttk.Label(ctrl, text="Max pages:").grid(row=1, column=2, sticky="e", pady=(4, 0))
        self._pages_var = tk.StringVar(value="0")
        ttk.Entry(ctrl, textvariable=self._pages_var, width=5).grid(
            row=1, column=3, sticky="w", padx=(4, 0), pady=(4, 0)
        )
        ttk.Label(ctrl, text="(0 = all)").grid(row=1, column=4, sticky="w", pady=(4, 0))
        ctrl.columnconfigure(1, weight=1)

        # ── action buttons ────────────────────────────────────────────
        btn_bar = ttk.Frame(self, padding=(p, 0, p, 0))
        btn_bar.pack(fill="x", padx=p)
        self._extract_btn = ttk.Button(
            btn_bar, text="Extract", command=self._on_extract
        )
        self._extract_btn.pack(side="left", padx=(0, 4))
        ttk.Button(btn_bar, text="Save output…", command=self._save).pack(side="left")
        ttk.Button(btn_bar, text="Clear", command=self._clear).pack(side="left", padx=4)
        self._status_lbl = ttk.Label(btn_bar, text="", foreground="gray")
        self._status_lbl.pack(side="left", padx=(8, 0))

        # ── metadata panel ────────────────────────────────────────────
        meta_frame = ttk.LabelFrame(self, text="Metadata", padding=p)
        meta_frame.pack(fill="x", padx=p, pady=(p, 0))
        self._meta_text = tk.Text(
            meta_frame, height=3, state="disabled",
            font=self.OUT_FONT, relief="flat", bg=self.cget("bg"),
            wrap="word",
        )
        self._meta_text.pack(fill="x")

        # ── output text area ──────────────────────────────────────────
        out_frame = ttk.LabelFrame(self, text="Extracted text", padding=p)
        out_frame.pack(fill="both", expand=True, padx=p, pady=p)
        self._output = scrolledtext.ScrolledText(
            out_frame, font=self.OUT_FONT, state="disabled", wrap="word"
        )
        self._output.pack(fill="both", expand=True)

        # ── progress bar (hidden until extraction runs) ───────────────
        self._progress = ttk.Progressbar(self, mode="indeterminate")

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

    def _on_extract(self) -> None:
        pdf_path = self._path_var.get().strip()
        if not pdf_path:
            messagebox.showwarning("No file", "Please select a PDF file first.")
            return
        if not Path(pdf_path).is_file():
            messagebox.showerror("File not found", f"Cannot find:\n{pdf_path}")
            return
        try:
            max_pages = int(self._pages_var.get())
        except ValueError:
            messagebox.showerror("Invalid input", "Max pages must be an integer.")
            return

        self._set_status("Extracting…")
        self._extract_btn.configure(state="disabled")
        self._progress.pack(fill="x", padx=self.PAD, pady=(0, self.PAD))
        self._progress.start(12)

        def _worker() -> None:
            try:
                result = pdfextract.PDFExtractor(pdf_path, max_pages=max_pages).extract()
                self.after(0, self._on_done, result)
            except Exception as exc:  # noqa: BLE001
                self.after(0, self._on_error, str(exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_done(self, result: pdfextract.ExtractionResult) -> None:
        self._result = result
        self._progress.stop()
        self._progress.pack_forget()
        self._extract_btn.configure(state="normal")

        # Render metadata
        meta_lines = [f"{k}: {v}" for k, v in result.metadata.items()]
        meta_lines += [
            f"Pages: {result.page_count}",
            f"Words: {result.word_count}",
        ]
        if result.errors:
            meta_lines.append("Errors: " + "; ".join(result.errors))
        self._set_meta("\n".join(meta_lines))

        # Render extracted text
        fmt = self._fmt_var.get()
        if fmt == "json":
            text = json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
        elif fmt == "markdown":
            text = result.to_markdown()
        else:
            text = result.full_text or "(No text extracted)"

        self._set_output(text)
        self._set_status(
            f"Done — {result.page_count} page(s), {result.word_count} word(s)."
        )

    def _on_error(self, message: str) -> None:
        self._progress.stop()
        self._progress.pack_forget()
        self._extract_btn.configure(state="normal")
        self._set_status("Error.")
        messagebox.showerror("Extraction error", message)

    def _save(self) -> None:
        if self._result is None:
            messagebox.showinfo("Nothing to save", "Extract a PDF first.")
            return
        fmt = self._fmt_var.get()
        ext_map = {"text": ".txt", "markdown": ".md", "json": ".json"}
        default_ext = ext_map.get(fmt, ".txt")
        path = filedialog.asksaveasfilename(
            title="Save output",
            defaultextension=default_ext,
            filetypes=[
                ("Text files", "*.txt"),
                ("Markdown files", "*.md"),
                ("JSON files", "*.json"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        content = self._output.get("1.0", tk.END)
        Path(path).write_text(content, encoding="utf-8")
        self._set_status(f"Saved to {Path(path).name}")

    def _clear(self) -> None:
        self._result = None
        self._set_output("")
        self._set_meta("")
        self._set_status("")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_output(self, text: str) -> None:
        self._output.configure(state="normal")
        self._output.delete("1.0", tk.END)
        self._output.insert(tk.END, text)
        self._output.configure(state="disabled")

    def _set_meta(self, text: str) -> None:
        self._meta_text.configure(state="normal")
        self._meta_text.delete("1.0", tk.END)
        self._meta_text.insert(tk.END, text)
        self._meta_text.configure(state="disabled")

    def _set_status(self, msg: str) -> None:
        self._status_lbl.configure(text=msg)


def main() -> None:
    """Entry point for the GUI."""
    app = PDFExtractApp()
    app.mainloop()


if __name__ == "__main__":
    main()
