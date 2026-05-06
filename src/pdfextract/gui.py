"""Tkinter GUI for pdfextract."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    _TKINTER_AVAILABLE = True
except ImportError:
    _TKINTER_AVAILABLE = False

from .extractor import PDFExtractor
from .schema import ExtractionResult


class PDFExtractApp:
    """Main application window for interactive PDF extraction."""

    def __init__(self, root: "tk.Tk") -> None:
        self.root = root
        root.title("pdfextract — PDF Text Extractor")
        root.geometry("960x720")
        root.minsize(640, 480)
        self._result: Optional[ExtractionResult] = None
        self._build_menu()
        self._build_ui()

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)

        file_menu = tk.Menu(menu, tearoff=0)
        file_menu.add_command(
            label="Open PDF…",
            command=self._browse_input,
            accelerator="Ctrl+O",
        )
        file_menu.add_command(
            label="Save Output…",
            command=self._save_output,
            accelerator="Ctrl+S",
        )
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menu.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menu, tearoff=0)
        help_menu.add_command(label="About", command=self._show_about)
        menu.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menu)
        self.root.bind("<Control-o>", lambda _e: self._browse_input())
        self.root.bind("<Control-s>", lambda _e: self._save_output())

    # ------------------------------------------------------------------
    # Main UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # ---- File selection row ----
        file_frame = ttk.LabelFrame(self.root, text="Input PDF", padding=6)
        file_frame.pack(fill="x", padx=10, pady=(8, 4))

        self._input_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self._input_var, width=70).grid(
            row=0, column=0, padx=(0, 6), sticky="ew"
        )
        ttk.Button(file_frame, text="Browse…", command=self._browse_input).grid(
            row=0, column=1
        )
        file_frame.columnconfigure(0, weight=1)

        # ---- Options row ----
        opt_frame = ttk.LabelFrame(self.root, text="Options", padding=6)
        opt_frame.pack(fill="x", padx=10, pady=4)

        ttk.Label(opt_frame, text="Output format:").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self._fmt_var = tk.StringVar(value="text")
        for col, fmt in enumerate(("text", "markdown", "json"), start=1):
            ttk.Radiobutton(
                opt_frame, text=fmt, value=fmt, variable=self._fmt_var
            ).grid(row=0, column=col, padx=4)

        ttk.Separator(opt_frame, orient="vertical").grid(
            row=0, column=4, sticky="ns", padx=10
        )

        ttk.Label(opt_frame, text="Max pages (0 = all):").grid(
            row=0, column=5, sticky="w", padx=(0, 4)
        )
        self._maxpages_var = tk.IntVar(value=0)
        ttk.Spinbox(
            opt_frame,
            from_=0,
            to=9999,
            textvariable=self._maxpages_var,
            width=6,
        ).grid(row=0, column=6)

        # ---- Action bar ----
        action_frame = ttk.Frame(self.root, padding=(10, 4))
        action_frame.pack(fill="x")

        ttk.Button(
            action_frame, text="Extract", command=self._start_extract, width=12
        ).pack(side="left")
        ttk.Button(
            action_frame, text="Clear", command=self._clear_output, width=8
        ).pack(side="left", padx=6)

        self._progress = ttk.Progressbar(
            action_frame, mode="indeterminate", length=180
        )
        self._progress.pack(side="right")

        self._status_var = tk.StringVar(value="Ready.")
        ttk.Label(
            action_frame, textvariable=self._status_var, anchor="w"
        ).pack(side="left", padx=8, fill="x", expand=True)

        # ---- Output text area ----
        out_frame = ttk.LabelFrame(self.root, text="Output", padding=4)
        out_frame.pack(fill="both", expand=True, padx=10, pady=4)
        out_frame.rowconfigure(0, weight=1)
        out_frame.columnconfigure(0, weight=1)

        self._output_text = tk.Text(
            out_frame,
            wrap="word",
            font=("Courier", 10),
            undo=True,
        )
        v_scroll = ttk.Scrollbar(
            out_frame, orient="vertical", command=self._output_text.yview
        )
        h_scroll = ttk.Scrollbar(
            out_frame, orient="horizontal", command=self._output_text.xview
        )
        self._output_text.configure(
            yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set
        )
        self._output_text.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

        # ---- Bottom bar ----
        bot_frame = ttk.Frame(self.root, padding=(10, 4))
        bot_frame.pack(fill="x")
        ttk.Button(
            bot_frame, text="Save Output…", command=self._save_output
        ).pack(side="right")

        self._stats_var = tk.StringVar(value="")
        ttk.Label(bot_frame, textvariable=self._stats_var).pack(
            side="left", anchor="w"
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _browse_input(self) -> None:
        path = filedialog.askopenfilename(
            title="Select a PDF file",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self._input_var.set(path)

    def _start_extract(self) -> None:
        path = self._input_var.get().strip()
        if not path:
            messagebox.showwarning(
                "No file selected", "Please select a PDF file first."
            )
            return
        self._progress.start(10)
        self._status_var.set("Extracting…")
        self._stats_var.set("")
        self._output_text.delete("1.0", tk.END)
        threading.Thread(
            target=self._run_extract, args=(path,), daemon=True
        ).start()

    def _run_extract(self, path: str) -> None:
        try:
            extractor = PDFExtractor(path, max_pages=self._maxpages_var.get())
            result = self._result = extractor.extract()
            fmt = self._fmt_var.get()
            if fmt == "json":
                output = result.to_json()
            elif fmt == "markdown":
                output = result.to_markdown()
            else:
                output = result.full_text or "(no text extracted)"
            self.root.after(0, self._show_result, output, result)
        except Exception as exc:
            self.root.after(0, self._show_error, str(exc))

    def _show_result(self, output: str, result: ExtractionResult) -> None:
        self._progress.stop()
        errs = len(result.errors)
        self._status_var.set(
            "Done."
            + (f"  {errs} warning(s) — see Warnings section." if errs else "")
        )
        self._stats_var.set(
            f"{result.page_count} page(s)  |  {result.word_count:,} words"
        )
        self._output_text.delete("1.0", tk.END)
        self._output_text.insert(tk.END, output)

    def _show_error(self, message: str) -> None:
        self._progress.stop()
        self._status_var.set("Error.")
        messagebox.showerror("Extraction failed", message)

    def _clear_output(self) -> None:
        self._output_text.delete("1.0", tk.END)
        self._status_var.set("Ready.")
        self._stats_var.set("")
        self._result = None

    def _save_output(self) -> None:
        text = self._output_text.get("1.0", tk.END).strip()
        if not text:
            messagebox.showinfo("Nothing to save", "Run an extraction first.")
            return
        fmt = self._fmt_var.get()
        ext_map = {"text": ".txt", "markdown": ".md", "json": ".json"}
        save_path = filedialog.asksaveasfilename(
            defaultextension=ext_map.get(fmt, ".txt"),
            filetypes=[
                ("Text files", "*.txt"),
                ("Markdown files", "*.md"),
                ("JSON files", "*.json"),
                ("All files", "*.*"),
            ],
        )
        if save_path:
            Path(save_path).write_text(text, encoding="utf-8")
            messagebox.showinfo("Saved", f"Output saved to:\n{save_path}")

    def _show_about(self) -> None:
        messagebox.showinfo(
            "About pdfextract",
            "pdfextract v0.2.0\n\n"
            "Structured text and metadata extraction\n"
            "from PDF documents.\n\n"
            "https://github.com/vdeshmukh203/pdfextract",
        )


def run_gui() -> None:
    """Launch the pdfextract graphical interface."""
    if not _TKINTER_AVAILABLE:
        raise ImportError(
            "tkinter is not available. Install it with your system package manager "
            "(e.g. 'apt install python3-tk' or 'brew install python-tk')."
        )
    root = tk.Tk()
    PDFExtractApp(root)
    root.mainloop()
