import os
import sys
import tempfile

from docx import Document

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.deidentify import deidentify_file  # noqa: E402
from tests.make_sample import build_sample  # noqa: E402

# Real identifying strings planted in the sample document. None of these
# should survive de-identification anywhere in the output - not in the field
# tables, not in the narrative paragraphs, not in the sign-off block.
FORBIDDEN_STRINGS = [
    "Sarah Jennifer Mitchell",
    "Sarah Mitchell",
    "David Mitchell",
    "Amanda Chen",
    "430128754",
    "2950 12092 1",
    "27 Wattle Grove",
    "0412 345 678",
    "0400 111 222",
    "sarah.mitchell@example.com",
    "amanda.chen@brightpathways.example.com",
    "14/03/2009",
]

EXPECTED_TAGS = [
    "[NDIS NUMBER]",
    "[MEDICARE NUMBER]",
    "[PHONE]",
    "[EMAIL]",
    "[DOB]",
]


def _full_text(docx_path: str) -> str:
    doc = Document(docx_path)
    chunks = []
    for p in doc.paragraphs:
        chunks.append(p.text)
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                chunks.append(cell.text)
    return "\n".join(chunks)


def test_deidentify_removes_all_planted_pii():
    with tempfile.TemporaryDirectory() as tmp:
        sample_path = os.path.join(tmp, "sample.docx")
        output_path = os.path.join(tmp, "sample_deidentified.docx")
        build_sample(sample_path)

        result = deidentify_file(sample_path, output_path)
        assert result.total > 0

        text = _full_text(output_path)

        for forbidden in FORBIDDEN_STRINGS:
            assert forbidden not in text, f"Leaked PII survived redaction: {forbidden!r}"

        for tag in EXPECTED_TAGS:
            assert tag in text, f"Expected placeholder missing: {tag!r}"

        # Structure must survive: same number of tables/rows, headings intact.
        original = Document(sample_path)
        redacted = Document(output_path)
        assert len(original.tables) == len(redacted.tables)
        for ot, rt in zip(original.tables, redacted.tables):
            assert len(ot.rows) == len(rt.rows)
        assert len(original.paragraphs) == len(redacted.paragraphs)


def test_non_docx_input_rejected():
    import pytest

    with tempfile.TemporaryDirectory() as tmp:
        bad_path = os.path.join(tmp, "not_a_docx.txt")
        with open(bad_path, "w") as f:
            f.write("hello")
        with pytest.raises(ValueError):
            deidentify_file(bad_path)
