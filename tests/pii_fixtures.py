"""Identifying strings/tags planted by make_sample.py's builders, shared
across the .docx and .txt test suites so both exercise the same PII.
"""

# Real identifying strings planted in the sample document/text. None of
# these should survive de-identification anywhere in the output.
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
