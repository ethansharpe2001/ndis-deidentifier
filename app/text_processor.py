"""De-identifies a plain-text (.txt) file line by line, using the same PII
detection/classification pipeline as the .docx processor (`pii_engine`).

Plain text has no table/cell structure to draw a field's label from, so each
line's own text is its primary context. The one exception: if the
immediately preceding line is a bare label ending in ":" (e.g.
"Participant Name:" with the value on the next line), that label is folded
in as extra context too. Anything looser - e.g. forwarding *any* preceding
line - risks bleeding a label from one field into an unrelated line further
down (a practitioner's name mentioned earlier wrongly tagging an unrelated
person two paragraphs later), so this only fires for that specific
label-only-line pattern.
"""
from __future__ import annotations

from collections import Counter
from typing import Tuple

from . import pii_engine
from .pii_engine import DeidResult

__all__ = ["DeidResult", "deidentify_text", "deidentify_txt_file"]


def deidentify_text(content: str, analyzer) -> Tuple[str, DeidResult]:
    stats: Counter = Counter()
    newline = "\r\n" if "\r\n" in content else "\n"
    had_trailing_newline = content.endswith(("\n", "\r\n"))
    lines = content.splitlines()

    prev_line = ""
    out_lines = []
    for line in lines:
        if not line.strip():
            out_lines.append(line)
            continue
        label_line = prev_line if prev_line.rstrip().endswith(":") else ""
        context_text = f"{line} {label_line}" if label_line else line
        spans = pii_engine.select_spans(analyzer, line, context_text, stats)
        out_lines.append(pii_engine.apply_spans(line, spans) if spans else line)
        prev_line = line

    new_content = newline.join(out_lines)
    if had_trailing_newline:
        new_content += newline
    return new_content, DeidResult(counts=stats)


def deidentify_txt_file(input_path: str, output_path: str, analyzer) -> DeidResult:
    with open(input_path, "r", encoding="utf-8-sig", errors="replace") as f:
        content = f.read()
    new_content, result = deidentify_text(content, analyzer)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        f.write(new_content)
    return result
