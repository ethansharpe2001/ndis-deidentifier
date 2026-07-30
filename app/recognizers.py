"""Custom PII recognizers and AnalyzerEngine construction for NDIS Behaviour
Support Plan de-identification.

Builds on presidio-analyzer's predefined recognizers (PERSON, LOCATION,
ORGANIZATION, DATE_TIME, PHONE_NUMBER, EMAIL_ADDRESS, AU_MEDICARE) and adds
two custom ones that presidio has no built-in equivalent for:

- NDIS_NUMBER: the participant's 9-digit NDIS number.
- AU_ADDRESS: a full Australian street address (street + suburb + state +
  postcode), which spaCy's LOCATION/GPE entity does not reliably capture as
  a single span.
"""
from __future__ import annotations

from presidio_analyzer import (
    AnalyzerEngine,
    Pattern,
    PatternRecognizer,
    RecognizerRegistry,
)
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import AuMedicareRecognizer

# Entities we ask the analyzer to look for. ORGANIZATION is off by default in
# presidio's stock config because of false-positive risk in generic text, but
# for an NDIS plan the provider/organisation name is exactly the kind of
# identifying detail we're asked to remove, so we turn it back on here.
ENTITIES = [
    "PERSON",
    "LOCATION",
    "ORGANIZATION",
    "DATE_TIME",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "AU_MEDICARE",
    "NDIS_NUMBER",
    "AU_ADDRESS",
    "URL",
]

SPACY_MODEL = "en_core_web_lg"


class NdisNumberRecognizer(PatternRecognizer):
    """Recognizes an Australian NDIS participant number.

    NDIS numbers are 9-digit identifiers. There's no public checksum, so
    detection leans on nearby context words ("NDIS number", "NDIS no",
    "participant number") which is how presidio's Pattern context boost
    works: a bare 9-digit number scores low, but scores much higher when a
    context word appears within the configured window.
    """

    PATTERNS = [
        Pattern("NDIS number (digits)", r"\b\d{9}\b", 0.15),
        Pattern("NDIS number (spaced/dashed)", r"\b\d{3}[\s-]\d{3}[\s-]\d{3}\b", 0.2),
    ]

    CONTEXT = [
        "ndis",
        "ndis number",
        "ndis no",
        "ndis id",
        "participant number",
    ]

    def __init__(self):
        super().__init__(
            supported_entity="NDIS_NUMBER",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            supported_language="en",
        )


class AuAddressRecognizer(PatternRecognizer):
    """Recognizes a full Australian street address in one span: street
    number/name/type, optional suburb, state abbreviation and postcode.

    e.g. "12 Smith Street, Richmond VIC 3121" or "Unit 4/56 High St, Bendigo VIC 3550"
    """

    _STREET_TYPES = (
        r"Street|St|Road|Rd|Avenue|Ave|Court|Ct|Drive|Dr|Place|Pl|Lane|Ln|"
        r"Boulevard|Blvd|Way|Crescent|Cres|Close|Cl|Terrace|Tce|Highway|Hwy|"
        r"Parade|Pde|Circuit|Cct|Grove|Gr"
    )
    _STATES = r"NSW|VIC|QLD|WA|SA|TAS|ACT|NT"

    PATTERNS = [
        Pattern(
            "AU street address",
            r"\b\d{1,4}[A-Za-z]?(?:/\d{1,4})?\s+[A-Za-z0-9'.\s]{1,40}\b"
            rf"(?:{_STREET_TYPES})\b[,.\s]+[A-Za-z\s]{{2,30}}?\b({_STATES})\b\s*\d{{4}}\b",
            0.6,
        ),
    ]

    CONTEXT = ["address", "residential", "residence", "lives at", "postal"]

    def __init__(self):
        super().__init__(
            supported_entity="AU_ADDRESS",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            supported_language="en",
        )


def build_analyzer_engine() -> AnalyzerEngine:
    """Constructs the AnalyzerEngine used across the app.

    Uses presidio's default spaCy-backed NLP engine but re-enables the
    ORGANIZATION label (presidio ignores it by default) so provider /
    organisation names get flagged, then layers the two custom recognizers
    on top of the predefined registry.
    """
    nlp_configuration = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": SPACY_MODEL}],
        "ner_model_configuration": {
            "model_to_presidio_entity_mapping": {
                "PER": "PERSON",
                "PERSON": "PERSON",
                "NORP": "NRP",
                "FAC": "LOCATION",
                "LOC": "LOCATION",
                "GPE": "LOCATION",
                "LOCATION": "LOCATION",
                "ORG": "ORGANIZATION",
                "ORGANIZATION": "ORGANIZATION",
                "DATE": "DATE_TIME",
                "TIME": "DATE_TIME",
            },
            "low_confidence_score_multiplier": 0.4,
            "low_score_entity_names": [],
            # Note: ORGANIZATION deliberately left out of labels_to_ignore.
            "labels_to_ignore": [
                "CARDINAL",
                "EVENT",
                "LANGUAGE",
                "LAW",
                "MONEY",
                "ORDINAL",
                "PERCENT",
                "PRODUCT",
                "QUANTITY",
                "WORK_OF_ART",
            ],
        },
    }

    provider = NlpEngineProvider(nlp_configuration=nlp_configuration)
    nlp_engine = provider.create_engine()

    # presidio's default registry only loads locale-agnostic recognizers -
    # every country-specific one (AU included) ships `enabled: false` in
    # presidio's own config, regardless of any `countries=` filter, so
    # AU_MEDICARE has to be instantiated and added explicitly.
    registry = RecognizerRegistry(supported_languages=["en"])
    registry.load_predefined_recognizers(languages=["en"], nlp_engine=nlp_engine)
    registry.add_recognizer(AuMedicareRecognizer())
    registry.add_recognizer(NdisNumberRecognizer())
    registry.add_recognizer(AuAddressRecognizer())

    analyzer = AnalyzerEngine(
        nlp_engine=nlp_engine, registry=registry, supported_languages=["en"]
    )
    return analyzer
