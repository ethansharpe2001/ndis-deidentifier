"""Drag-and-drop desktop GUI for de-identifying NDIS Behaviour Support Plan
.docx files. Runs the (slow to load, slow to run) presidio analyzer on a
background thread so the window never freezes; the worker thread only ever
talks to the UI thread through a thread-safe queue polled via `after()`.

Styling: ttkbootstrap gives the stock Tk widget set a flat, modern
Bootstrap-inspired theme (with a one-line light/dark toggle) for free,
without pulling in a heavyweight UI framework. It's layered on top of
tkinterdnd2 (drag-and-drop) using ttkbootstrap's own documented recipe for
combining the two: `Window` + `TkinterDnD.DnDWrapper` as a mixin.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import ttkbootstrap as ttkb

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    _DND_AVAILABLE = True

    class _Base(ttkb.Window, TkinterDnD.DnDWrapper):
        def __init__(self, *args, **kwargs):
            ttkb.Window.__init__(self, *args, **kwargs)
            self.TkdndVersion = TkinterDnD._require(self)

except ImportError:  # pragma: no cover - exercised only if tkinterdnd2 missing
    _DND_AVAILABLE = False
    _Base = ttkb.Window

from .deidentify import FileOutcome, deidentify_files, get_analyzer

_DOCX_FILETYPES = [("Word documents", "*.docx")]
_THEME = "bootstrap-light"


class App(_Base):
    def __init__(self):
        super().__init__(
            title="NDIS Behaviour Support Plan De-identifier",
            themename=_THEME,
            size=(760, 660),
            minsize=(680, 560),
            resizable=(True, True),
        )

        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._output_dir: str | None = None
        self._analyzer_ready = False
        self._processing = False

        self._build_widgets()
        self.after(100, self._poll_queue)
        threading.Thread(target=self._load_analyzer_bg, daemon=True).start()

    # ---------- UI construction ----------

    def _build_widgets(self) -> None:
        self._build_header()

        body = ttkb.Frame(self, padding=20)
        body.pack(fill="both", expand=True)

        self._build_status_row(body)
        self._build_drop_zone(body)
        self._build_output_section(body)
        self._build_progress(body)
        self._build_log(body)
        self._build_footer()

    def _build_header(self) -> None:
        header = ttkb.Frame(self, bootstyle="primary", padding=(20, 16))
        header.pack(fill="x")

        text_col = ttkb.Frame(header, bootstyle="primary")
        text_col.pack(side="left", fill="x", expand=True)
        ttkb.Label(
            text_col,
            text="🛡  NDIS Behaviour Support Plan De-identifier",
            bootstyle="inverse-primary",
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")
        ttkb.Label(
            text_col,
            text="Drop in a .docx plan, get a de-identified copy back - names, dates of birth,\n"
            "NDIS/Medicare numbers, addresses, contact details and provider names removed.",
            bootstyle="inverse-primary",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(4, 0))

    def _build_status_row(self, parent) -> None:
        row = ttkb.Frame(parent)
        row.pack(fill="x", pady=(0, 14))
        self._status_dot = ttkb.Label(row, text="●", bootstyle="warning", font=("Segoe UI", 12))
        self._status_dot.pack(side="left")
        self.status_var = tk.StringVar(value="Loading PII detection engine…")
        ttkb.Label(row, textvariable=self.status_var, font=("Segoe UI", 10)).pack(
            side="left", padx=(6, 0)
        )

    def _build_drop_zone(self, parent) -> None:
        self.drop_canvas = tk.Canvas(parent, height=150, highlightthickness=0, bd=0)
        self.drop_canvas.pack(fill="x", pady=(0, 16))
        self.drop_canvas.bind("<Configure>", lambda _e: self._draw_drop_zone())
        self.drop_canvas.bind("<Button-1>", lambda _e: self._browse_files())

        if _DND_AVAILABLE:
            self.drop_canvas.drop_target_register(DND_FILES)
            self.drop_canvas.dnd_bind("<<DropEnter>>", lambda e: self._draw_drop_zone(active=True))
            self.drop_canvas.dnd_bind("<<DropLeave>>", lambda e: self._draw_drop_zone(active=False))
            self.drop_canvas.dnd_bind("<<Drop>>", self._on_drop)

        self._draw_drop_zone()

    def _draw_drop_zone(self, active: bool = False) -> None:
        c = self.drop_canvas
        c.delete("all")
        c.configure(bg=self.style.colors.bg)
        w = max(c.winfo_width(), 200)
        h = max(c.winfo_height(), 100)
        colors = self.style.colors
        border = colors.info if active else colors.secondary
        text_color = colors.info if active else colors.fg

        c.create_rectangle(3, 3, w - 3, h - 3, dash=(7, 4), width=2, outline=border)
        c.create_text(w / 2, h / 2 - 18, text="📥" if active else "📄", font=("Segoe UI Emoji", 26))
        if active:
            message = "Release to add files"
        elif _DND_AVAILABLE:
            message = "Drag .docx files here, or click to browse"
        else:
            message = "Click to browse for .docx files"
        c.create_text(
            w / 2, h / 2 + 22, text=message, font=("Segoe UI", 10), fill=text_color, justify="center"
        )

    def _build_output_section(self, parent) -> None:
        section = ttkb.Labelframe(parent, text="Output location", padding=14)
        section.pack(fill="x", pady=(0, 16))

        self.output_mode = tk.StringVar(value="alongside")
        ttkb.Radiobutton(
            section,
            text="Save next to each original (adds \"_deidentified\" suffix)",
            variable=self.output_mode,
            value="alongside",
            bootstyle="toolbutton",
            command=self._on_output_mode_change,
        ).pack(anchor="w", fill="x")

        choose_row = ttkb.Frame(section)
        choose_row.pack(anchor="w", fill="x", pady=(8, 0))
        ttkb.Radiobutton(
            choose_row,
            text="Save all outputs into a chosen folder",
            variable=self.output_mode,
            value="folder",
            bootstyle="toolbutton",
            command=self._on_output_mode_change,
        ).pack(side="left")
        self.choose_folder_btn = ttkb.Button(
            choose_row,
            text="Choose folder…",
            bootstyle="secondary-outline",
            command=self._choose_output_folder,
            state="disabled",
        )
        self.choose_folder_btn.pack(side="left", padx=(10, 0))
        self.output_dir_label = ttkb.Label(section, text="(no folder chosen)", bootstyle="secondary")
        self.output_dir_label.pack(anchor="w", pady=(6, 0))

    def _build_progress(self, parent) -> None:
        self.progress = ttkb.Floodgauge(
            parent, bootstyle="success", mode="determinate", mask="{}%", length=100
        )
        self.progress.pack(fill="x", pady=(0, 16))

    def _build_log(self, parent) -> None:
        section = ttkb.Labelframe(parent, text="Activity", padding=8)
        section.pack(fill="both", expand=True)

        self.log_text = ttkb.ScrolledText(section, wrap="word", height=10, autohide=True)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.text.configure(state="disabled", font=("Segoe UI", 9))
        self.log_text.text.tag_configure("success", foreground=self.style.colors.success)
        self.log_text.text.tag_configure("error", foreground=self.style.colors.danger)
        self.log_text.text.tag_configure("info", foreground=self.style.colors.secondary)

    def _build_footer(self) -> None:
        ttkb.Label(
            self,
            text="Built on Microsoft Presidio (spaCy NER + rule-based recognizers) - always spot-check output.",
            bootstyle="secondary",
            font=("Segoe UI", 8),
            padding=(20, 6),
        ).pack(fill="x", side="bottom")

    # ---------- analyzer loading ----------

    def _load_analyzer_bg(self) -> None:
        try:
            get_analyzer()
            self._queue.put(("analyzer_ready", None))
        except Exception as exc:  # noqa: BLE001
            self._queue.put(("analyzer_error", str(exc)))

    # ---------- input handling ----------

    def _on_output_mode_change(self) -> None:
        if self.output_mode.get() == "folder":
            self.choose_folder_btn.configure(state="normal")
        else:
            self.choose_folder_btn.configure(state="disabled")

    def _choose_output_folder(self) -> None:
        folder = filedialog.askdirectory(title="Choose output folder")
        if folder:
            self._output_dir = folder
            self.output_dir_label.configure(text=folder)

    def _browse_files(self) -> None:
        if self._processing:
            return
        paths = filedialog.askopenfilenames(title="Choose NDIS plan .docx files", filetypes=_DOCX_FILETYPES)
        if paths:
            self._start_processing(list(paths))

    def _on_drop(self, event) -> None:
        self._draw_drop_zone(active=False)
        if self._processing:
            return
        raw_paths = self.tk.splitlist(event.data)
        docx_paths = [p for p in raw_paths if p.lower().endswith(".docx")]
        skipped = len(raw_paths) - len(docx_paths)
        if skipped:
            self._log(f"Ignored {skipped} non-.docx file(s).", "info")
        if docx_paths:
            self._start_processing(docx_paths)

    # ---------- processing ----------

    def _start_processing(self, paths: list[str]) -> None:
        if not self._analyzer_ready:
            ttkb.dialogs.Messagebox.show_info(
                "The PII detection engine is still starting up. Try again in a moment.",
                "Still loading",
            )
            return
        self._processing = True
        self.progress.configure(value=0, maximum=len(paths))
        output_dir = self._output_dir if self.output_mode.get() == "folder" else None

        def progress_cb(i, total, path):
            self._queue.put(("progress", (i, total, path)))

        def run():
            outcomes = deidentify_files(paths, output_dir=output_dir, progress_callback=progress_cb)
            self._queue.put(("done", outcomes))

        threading.Thread(target=run, daemon=True).start()

    # ---------- queue-driven UI updates (runs on the main thread) ----------

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                self._handle_event(kind, payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _handle_event(self, kind: str, payload) -> None:
        if kind == "analyzer_ready":
            self._analyzer_ready = True
            self._status_dot.configure(bootstyle="success")
            self.status_var.set("Ready. Drop NDIS plan .docx files above to de-identify them.")
        elif kind == "analyzer_error":
            self._status_dot.configure(bootstyle="danger")
            self.status_var.set("Failed to load PII detection engine.")
            self._log(f"ERROR loading analyzer: {payload}", "error")
        elif kind == "progress":
            i, total, path = payload
            self.progress.configure(value=i, maximum=total)
            self.status_var.set(f"Processing {i}/{total}: {Path(path).name}")
        elif kind == "done":
            self._processing = False
            self.progress.configure(value=0)
            self._status_dot.configure(bootstyle="success")
            self.status_var.set("Ready. Drop NDIS plan .docx files above to de-identify them.")
            self._report(payload)

    def _report(self, outcomes: list[FileOutcome]) -> None:
        for outcome in outcomes:
            name = Path(outcome.input_path).name
            if outcome.error:
                self._log(f"✗ {name}: {outcome.error}", "error")
            else:
                total = outcome.result.total if outcome.result else 0
                out_name = Path(outcome.output_path).name
                self._log(f"✓ {name} → {out_name} ({total} item(s) redacted)", "success")

    def _log(self, message: str, tag: str = "info") -> None:
        text = self.log_text.text
        text.configure(state="normal")
        text.insert("end", message + "\n", tag)
        text.see("end")
        text.configure(state="disabled")


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
