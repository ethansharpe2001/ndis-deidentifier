import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.deidentify import deidentify_file, get_analyzer  # noqa: E402
from app.text_processor import deidentify_text  # noqa: E402
from tests.make_sample import build_sample_txt  # noqa: E402
from tests.pii_fixtures import EXPECTED_TAGS, FORBIDDEN_STRINGS  # noqa: E402


def test_deidentify_txt_removes_all_planted_pii():
    with tempfile.TemporaryDirectory() as tmp:
        sample_path = os.path.join(tmp, "sample.txt")
        output_path = os.path.join(tmp, "sample_deidentified.txt")
        build_sample_txt(sample_path)

        result = deidentify_file(sample_path, output_path)
        assert result.total > 0

        with open(output_path, "r", encoding="utf-8") as f:
            text = f.read()

        for forbidden in FORBIDDEN_STRINGS:
            assert forbidden not in text, f"Leaked PII survived redaction: {forbidden!r}"

        for tag in EXPECTED_TAGS:
            assert tag in text, f"Expected placeholder missing: {tag!r}"

        # Line count and blank-line layout must survive untouched.
        with open(sample_path, "r", encoding="utf-8") as f:
            original_lines = f.read().splitlines()
        redacted_lines = text.splitlines()
        assert len(original_lines) == len(redacted_lines)
        for orig, red in zip(original_lines, redacted_lines):
            if not orig.strip():
                assert red == ""


def test_split_label_value_lines_are_classified_using_the_label():
    analyzer = get_analyzer()
    content = "Participant Name:\nSarah Jennifer Mitchell\n"
    new_content, result = deidentify_text(content, analyzer)
    assert "[PARTICIPANT NAME]" in new_content
    assert "Sarah Jennifer Mitchell" not in new_content
    assert result.total == 1


def test_label_context_does_not_leak_into_unrelated_later_paragraphs():
    """Regression test: a bare-label line like "Practitioner:" must only
    supply context to the very next line, not bleed into an unrelated
    paragraph several lines later just because no other label appeared
    since.
    """
    analyzer = get_analyzer()
    content = (
        "Behaviour Support Practitioner: Dr. Amanda Chen\n"
        "\n"
        "Unrelated note: David Mitchell dropped off some paperwork today.\n"
    )
    new_content, _ = deidentify_text(content, analyzer)
    # David Mitchell should not have been mislabeled as a second
    # practitioner just because "practitioner" appeared earlier in the file.
    assert "[PRACTITIONER NAME]" not in new_content.splitlines()[-1]


def test_empty_txt_file_does_not_crash():
    analyzer = get_analyzer()
    new_content, result = deidentify_text("", analyzer)
    assert new_content == ""
    assert result.total == 0


def test_whitespace_only_txt_file_does_not_crash():
    analyzer = get_analyzer()
    content = "\n\n   \n\n"
    new_content, result = deidentify_text(content, analyzer)
    assert new_content == content
    assert result.total == 0


def test_trailing_newline_is_preserved():
    analyzer = get_analyzer()
    with_newline = "Contact Email: sarah.mitchell@example.com\n"
    without_newline = "Contact Email: sarah.mitchell@example.com"

    redacted_with, _ = deidentify_text(with_newline, analyzer)
    redacted_without, _ = deidentify_text(without_newline, analyzer)

    assert redacted_with.endswith("\n")
    assert not redacted_without.endswith("\n")
