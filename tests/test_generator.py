import os
from pathlib import Path

import pytest

from core.generator import DraftGenerator
from core.models import RetrievedEvidence

# Load API key from .env at import time so skipif decorators can see it.
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists() and not os.environ.get("GROQ_API_KEY"):
    for _line in _env_path.read_text().splitlines():
        if _line.startswith("GROQ_API_KEY"):
            _key = _line.split("=", 1)[1].strip().strip('"')
            os.environ["GROQ_API_KEY"] = _key
            break


@pytest.fixture
def api_key():
    return os.environ.get("GROQ_API_KEY")


def test_generator_missing_key():
    original = os.environ.pop("GROQ_API_KEY", None)
    try:
        with pytest.raises(ValueError, match="GROQ_API_KEY"):
            DraftGenerator()
    finally:
        if original:
            os.environ["GROQ_API_KEY"] = original


@pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not available",
)
def test_generate_case_fact_summary(api_key):
    generator = DraftGenerator()
    evidence = [
        RetrievedEvidence(
            chunk_id="doc1_p1_c0",
            text="ACME INDUSTRIES LLC entered into a service agreement with SMITH VENTURES INC. on March 15, 2024 for a fee of $125,000.",
            source_doc="contract.pdf",
            page_num=1,
            score=0.95,
        ),
        RetrievedEvidence(
            chunk_id="doc1_p1_c1",
            text="The agreement term is from April 1, 2024 through March 31, 2025. Case No. PSL-2024-0042.",
            source_doc="contract.pdf",
            page_num=1,
            score=0.92,
        ),
    ]

    result = generator.generate(
        query="Generate a case fact summary",
        evidence=evidence,
    )

    assert result.parties
    assert result.key_facts
    assert result.dates
    assert result.claims is not None
    assert result.uncertainties is not None

    # Grounding check: every fact should cite at least one chunk_id
    for fact in result.key_facts:
        assert fact.supporting_evidence, f"Fact lacks citations: {fact.statement}"

    for claim in result.claims:
        assert claim.supporting_evidence, f"Claim lacks citations: {claim.description}"


@pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not available",
)
def test_generate_with_correction_rules(api_key):
    generator = DraftGenerator()
    evidence = [
        RetrievedEvidence(
            chunk_id="doc1_p1_c0",
            text="Service agreement between ACME LLC and SMITH INC.",
            source_doc="contract.pdf",
            page_num=1,
            score=0.9,
        ),
    ]

    rules = ["Always include the full company name with suffix (LLC, Inc., etc.)"]
    result = generator.generate(
        query="Summarize",
        evidence=evidence,
        correction_rules=rules,
    )

    assert result.parties is not None
    assert result.key_facts is not None
