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
from dataclasses import dataclass, field
from typing import Iterator, List, Tuple

from docx import Document
from docx.document import Document as DocumentObject
from docx.oxml.ns import qn
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from . import roles
from .recognizers import ENTITIES

SCORE_THRESHOLD = 0.4


@dataclass
class DeidResult:
    counts: Counter = field(default_factory=Counter)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def _iter_block_items(parent) -> Iterator["Paragraph | Table"]:
    """Yields each paragraph and table that are direct children of `parent`,
    in document order. `parent` is a Document or a table _Cell.
    """
    if isinstance(parent, DocumentObject):
        parent_elm = parent.element.body
    elif isinstance(parent, _Cell):
        parent_elm = parent._tc
    else:
        raise ValueError(f"Unsupported parent type: {type(parent)}")

    for child in parent_elm.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent)


def _get_runs(paragraph: Paragraph) -> List[Run]:
    """All `<w:r>` runs in the paragraph, including ones nested inside
    `<w:hyperlink>`, in document order (python-docx's own `.runs` skips
    hyperlink-wrapped runs).
    """
    return [Run(r, paragraph) for r in paragraph._p.iter(qn("w:r"))]


def _merge_run_text(runs: List[Run]) -> str:
    return "".join(r.text or "" for r in runs)


def _apply_replacements(runs: List[Run], full_text: str, spans: List[Tuple[int, int, str]]) -> str:
    """Builds the redacted text from `spans` (start, end, tag) and writes it
    into the first run, clearing the rest. Returns the new text.
    """
    parts = []
    cursor = 0
    for start, end, tag in spans:
        parts.append(full_text[cursor:start])
        parts.append(f"[{tag}]")
        cursor = end
    parts.append(full_text[cursor:])
    new_text = "".join(parts)

    runs[0].text = new_text
    for r in runs[1:]:
        r.text = ""
    return new_text


def _select_non_overlapping(results, full_text: str, context_text: str, stats: Counter):
    """Greedily picks non-overlapping analyzer results (highest score
    first), classifies each into a placeholder tag, and returns the
    accepted (start, end, tag) spans sorted by position."""
    accepted: List[Tuple[int, int]] = []
    tagged: List[Tuple[int, int, str]] = []

    boosted = [
        (roles.boost_score(r.entity_type, r.score, context_text), r) for r in results
    ]
    # Tie-break on span length so a specific, longer match (e.g. a full
    # street-address regex) wins over a shorter overlapping NER fragment
    # (e.g. just the suburb) scored the same.
    for score, result in sorted(
        boosted, key=lambda pair: (-pair[0], -(pair[1].end - pair[1].start))
    ):
        if score < SCORE_THRESHOLD:
            continue
        if any(not (result.end <= s or result.start >= e) for s, e in accepted):
            continue
        entity_text = full_text[result.start : result.end]
        tag = roles.classify(result.entity_type, entity_text, context_text)
        if tag is None:
            continue
        accepted.append((result.start, result.end))
        tagged.append((result.start, result.end, tag))
        stats[tag] += 1

    tagged.sort(key=lambda span: span[0])
    return tagged


def _process_paragraph(paragraph: Paragraph, analyzer, stats: Counter, extra_context: str = "") -> None:
    runs = _get_runs(paragraph)
    if not runs:
        return
    full_text = _merge_run_text(runs)
    if not full_text.strip():
        return

    context_text = f"{full_text} {extra_context}"
    results = analyzer.analyze(text=full_text, entities=ENTITIES, language="en")

    # spaCy's NER leans heavily on casing cues, so it routinely misses names
    # in ALL-CAPS text (a document title/heading like "JOHN SMITH" reads very
    # differently to it than "John Smith"). Title-casing is a length- and
    # offset-preserving transform, so a second PERSON-only pass on the
    # title-cased text can be merged straight back into the same spans.
    if full_text.isupper():
        titled_results = analyzer.analyze(text=full_text.title(), entities=["PERSON"], language="en")
        results = results + titled_results

    spans = _select_non_overlapping(results, full_text, context_text, stats)
    if not spans:
        return

    _apply_replacements(runs, full_text, spans)


def _process_container(parent, analyzer, stats: Counter, extra_context: str = "") -> None:
    for block in _iter_block_items(parent):
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
