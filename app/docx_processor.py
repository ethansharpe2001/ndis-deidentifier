"""Walks a .docx document (body, tables - including nested, headers,
footers) and replaces detected PII spans with placeholder tags in place,
while preserving the document's structure and formatting.

Formatting strategy: presidio detects PII on the *merged* text of a
paragraph (Word splits a single sentence across multiple `<w:r>` runs
whenever formatting, spell-check boundaries, or prior edits caused a split,
so analyzing run-by-run would miss things). Once a paragraph's merged text
has any replacement in it, the new text is written into the paragraph's
first run - carrying that run's font/bold/italic/etc. - and every other run
in the paragraph is emptied. This keeps paragraph styles, headings, table
layout and cell structure fully intact; the only cosmetic trade-off is that
if a single paragraph mixed two different run formats (e.g. a bold label
and a plain value on the same line), the whole line adopts the first run's
formatting. NDIS plan templates overwhelmingly put label/value pairs in
separate table cells or separate paragraphs, so this rarely comes up.

Table rows get special handling: all cell text in a row is combined into a
"row context" string used to detect the field label (e.g. "Behaviour
Support Practitioner") for whichever cell holds the value, since the label
and the value routinely sit in different cells of the same row.
"""
from __future__ import annotations

from collections import Counter
from typing import List, Tuple

from docx import Document
from docx.document import Document as DocumentObject
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from . import pii_engine
from .pii_engine import DeidResult

__all__ = ["DeidResult", "deidentify_document", "deidentify_docx_file"]


def _get_runs(paragraph: Paragraph) -> List[Run]:
    """All `<w:r>` runs in the paragraph, including ones nested inside
    `<w:hyperlink>`, in document order (python-docx's own `.runs` skips
    hyperlink-wrapped runs).
    """
    return [Run(r, paragraph) for r in paragraph._p.iter(qn("w:r"))]


def _merge_run_text(runs: List[Run]) -> str:
    return "".join(r.text or "" for r in runs)


def _apply_replacements(runs: List[Run], full_text: str, spans: List[Tuple[int, int, str]]) -> str:
    """Writes the redacted text (built from `spans`) into the first run,
    carrying that run's formatting, and clears the rest. Returns the new
    text.
    """
    new_text = pii_engine.apply_spans(full_text, spans)
    runs[0].text = new_text
    for r in runs[1:]:
        r.text = ""
    return new_text


def _process_paragraph(paragraph: Paragraph, analyzer, stats: Counter, extra_context: str = "") -> None:
    runs = _get_runs(paragraph)
    if not runs:
        return
    full_text = _merge_run_text(runs)
    if not full_text.strip():
        return

    context_text = f"{full_text} {extra_context}"
    spans = pii_engine.select_spans(analyzer, full_text, context_text, stats)
    if not spans:
        return

    _apply_replacements(runs, full_text, spans)


def _process_container(parent, analyzer, stats: Counter, extra_context: str = "") -> None:
    for block in parent.iter_inner_content():
        if isinstance(block, Paragraph):
            _process_paragraph(block, analyzer, stats, extra_context)
        elif isinstance(block, Table):
            _process_table(block, analyzer, stats)


def _process_table(table: Table, analyzer, stats: Counter) -> None:
    for row in table.rows:
        row_context = " | ".join(cell.text for cell in row.cells)
        for cell in row.cells:
            _process_container(cell, analyzer, stats, extra_context=row_context)


def _process_headers_footers(document: DocumentObject, analyzer, stats: Counter) -> None:
    for section in document.sections:
        for part in (
            section.header,
            section.footer,
            section.first_page_header,
            section.first_page_footer,
            section.even_page_header,
            section.even_page_footer,
        ):
            if part is None or part.is_linked_to_previous:
                # Linked-to-previous headers/footers mirror another
                # section's part, which is processed on its own iteration.
                continue
            _process_container(part, analyzer, stats)


def deidentify_document(document: DocumentObject, analyzer) -> DeidResult:
    """Redacts PII in place across the whole document (body, tables,
    headers, footers). Returns counts of how many of each placeholder tag
    were inserted."""
    stats: Counter = Counter()
    _process_container(document, analyzer, stats)
    _process_headers_footers(document, analyzer, stats)
    return DeidResult(counts=stats)


def deidentify_docx_file(input_path: str, output_path: str, analyzer) -> DeidResult:
    document = Document(input_path)
    result = deidentify_document(document, analyzer)
    document.save(output_path)
    return result
