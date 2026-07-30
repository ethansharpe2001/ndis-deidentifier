"""Maps a raw presidio entity (PERSON, ORGANIZATION, DATE_TIME, ...) to the
specific placeholder tag that should appear in the de-identified document,
using nearby label text as context.

NDIS Behaviour Support Plans are almost always structured as field/value
pairs - either a two-column table row ("Participant Name" | "John Smith")
or a single line ("Behaviour Support Practitioner: Jane Doe"). The caller
(docx_processor) is responsible for figuring out the right "context text"
to search (the table row's label cell, or the paragraph itself) and passes
it in here alongside the entity type.

Entities with no reliable direct-mapping tag (PERSON, ORGANIZATION,
LOCATION, DATE_TIME) fall back to a generic tag, or to `None` - meaning
"leave this occurrence alone" - when there's no context suggesting it's one
of the categories we were asked to remove (e.g. a plan review date, or a
passing mention of a suburb in clinical narrative).
"""
from __future__ import annotations

import re
from typing import Optional

# Entity types with an unambiguous, always-redact tag.
DIRECT_TAG = {
    "AU_MEDICARE": "MEDICARE NUMBER",
    "NDIS_NUMBER": "NDIS NUMBER",
    "AU_ADDRESS": "ADDRESS",
    "PHONE_NUMBER": "PHONE",
    "EMAIL_ADDRESS": "EMAIL",
    # Unconditional like phone/email: a personal URL (LinkedIn profile, a
    # named social/portfolio link) is just as identifying, and NDIS plans
    # don't tend to rely on inline links for anything load-bearing.
    "URL": "URL",
}

# Organisation names that are generic/government-body terms commonly printed
# in every NDIS plan template. These don't identify the participant or a
# specific small provider, so they're exempt from redaction.
ORG_ALLOWLIST = re.compile(
    r"^(the\s+)?(ndis|ndia|national disability insurance (scheme|agency)|"
    r"medicare|centrelink|department of (health|human services|social services)|"
    r"services australia)$",
    re.IGNORECASE,
)

# (role tag, [regex patterns checked against the context text], priority)
# Checked in order; first category with a match wins.
_ROLE_PATTERNS = [
    ("GUARDIAN NAME", [
        r"\bguardian\b", r"\bparent\b", r"\bcarer\b", r"\bnominee\b",
        r"\bnext of kin\b", r"\bemergency contact\b", r"\bfamily member\b",
        r"\badvocate\b", r"\bsupport(?:ed)? decision maker\b",
    ]),
    ("PRACTITIONER NAME", [
        r"\bbehaviour support practitioner\b", r"\bbehavior support practitioner\b",
        r"\bpractitioner\b", r"\bclinician\b", r"\bpsychologist\b",
        r"\btherapist\b", r"\bplan author\b", r"\bprepared by\b",
        r"\bauthorised by\b", r"\bauthored by\b",
    ]),
    ("PROVIDER NAME", [
        r"\bprovider\b", r"\borganisation\b", r"\borganization\b",
        r"\bservice provider\b", r"\bagency\b", r"\bemployer\b",
    ]),
    ("PARTICIPANT NAME", [
        r"\bparticipant\b", r"\bclient\b", r"\bperson('?s)? name\b",
        r"\bname of participant\b", r"\bfull name\b",
    ]),
]

_DOB_PATTERN = re.compile(r"\bdate of birth\b|\bdob\b|\bborn\b", re.IGNORECASE)

# Some custom/country-specific recognizers (NDIS_NUMBER, AU_MEDICARE) rely on
# a nearby context word ("NDIS", "Medicare") to lift a deliberately low base
# score. Presidio's own context enhancer only looks at words within the same
# analyzed text, but NDIS plan tables routinely put the label ("NDIS Number")
# in one cell and the value in another, so that word never appears in the
# text being analyzed. `boost_score` re-applies the same idea over the wider
# context text the caller assembles from the table row / paragraph.
_SCORE_BOOST = {
    "NDIS_NUMBER": (re.compile(r"\bndis\b", re.IGNORECASE), 0.9),
    "AU_MEDICARE": (re.compile(r"\bmedicare\b", re.IGNORECASE), 0.9),
    "AU_ADDRESS": (re.compile(r"\baddress\b", re.IGNORECASE), 0.95),
}


def boost_score(entity_type: str, score: float, context_text: str) -> float:
    boost = _SCORE_BOOST.get(entity_type)
    if boost is None:
        return score
    pattern, boosted_score = boost
    if pattern.search(context_text):
        return max(score, boosted_score)
    return score


def _first_matching_role(context_text: str) -> Optional[str]:
    for role_tag, patterns in _ROLE_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, context_text, re.IGNORECASE):
                return role_tag
    return None


def classify(entity_type: str, entity_text: str, context_text: str) -> Optional[str]:
    """Returns the placeholder tag (without brackets) for this entity, or
    None if this occurrence should be left untouched.
    """
    if entity_type in DIRECT_TAG:
        return DIRECT_TAG[entity_type]

    if entity_type == "PERSON":
        return _first_matching_role(context_text) or "NAME"

    if entity_type == "ORGANIZATION":
        if ORG_ALLOWLIST.match(entity_text.strip()):
            return None
        return "PROVIDER ORGANISATION NAME"

    if entity_type == "LOCATION":
        role = _first_matching_role(context_text)
        if role == "PARTICIPANT NAME" or re.search(
            r"\baddress\b|\bresiden|\blives at\b|\bpostal\b", context_text, re.IGNORECASE
        ):
            return "ADDRESS"
        return None

    if entity_type == "DATE_TIME":
        if _DOB_PATTERN.search(context_text):
            return "DOB"
        return None

    return None
