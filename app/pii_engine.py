"""Format-agnostic PII detection/classification pipeline shared by the
.docx and plain-text processors: run the analyzer over a chunk of text,
pick non-overlapping spans (highest-scoring first), classify each into a
placeholder tag, and substitute `[TAG]` markers into the text.

Callers own the notion of "context text" (e.g. a docx table row's combined
cell text, or a plain-text file's preceding line) - it's used both for this
app's own role classification/score-boosting (`roles.py`) and passed to
presidio itself for its own context-aware scoring.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import List, Tuple

from . import roles
from .recognizers import ENTITIES

SCORE_THRESHOLD = 0.4


@dataclass
class DeidResult:
    counts: Counter = field(default_factory=Counter)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def select_spans(
    analyzer, full_text: str, context_text: str, stats: Counter
) -> List[Tuple[int, int, str]]:
    """Analyzes `full_text` for PII and returns non-overlapping (start, end,
    tag) spans sorted by position, incrementing `stats[tag]` for each
    accepted span. Returns `[]` for blank text.
    """
    if not full_text.strip():
        return []

    results = analyzer.analyze(text=full_text, entities=ENTITIES, language="en")

    # spaCy's NER leans heavily on casing cues, so it routinely misses names
    # in ALL-CAPS text (a heading like "JOHN SMITH" reads very differently to
    # it than "John Smith"). Title-casing is a length- and offset-preserving
    # transform, so a second PERSON-only pass on the title-cased text can be
    # merged straight back into the same spans.
    if full_text.isupper():
        titled_results = analyzer.analyze(text=full_text.title(), entities=["PERSON"], language="en")
        results = results + titled_results

    accepted: List[Tuple[int, int]] = []
    tagged: List[Tuple[int, int, str]] = []

    boosted = [(roles.boost_score(r.entity_type, r.score, context_text), r) for r in results]
    # Tie-break on span length so a specific, longer match (e.g. a full
    # street-address regex) wins over a shorter overlapping NER fragment
    # (e.g. just the suburb) scored the same.
    for score, result in sorted(boosted, key=lambda pair: (-pair[0], -(pair[1].end - pair[1].start))):
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


def apply_spans(full_text: str, spans: List[Tuple[int, int, str]]) -> str:
    """Substitutes each (start, end, tag) span in `full_text` with `[TAG]`."""
    parts = []
    cursor = 0
    for start, end, tag in spans:
        parts.append(full_text[cursor:start])
        parts.append(f"[{tag}]")
        cursor = end
    parts.append(full_text[cursor:])
    return "".join(parts)
