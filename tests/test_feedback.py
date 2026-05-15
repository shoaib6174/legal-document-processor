import os
import tempfile

import pytest

from core.feedback import FeedbackEngine


@pytest.fixture
def engine():
    # Use a temp file for test isolation
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    fb = FeedbackEngine(db_path=path)
    yield fb
    os.unlink(path)


def test_capture_simple_edit(engine):
    original = {"parties": [{"name": "ACME LLC", "role": "plaintiff"}]}
    edited = {"parties": [{"name": "ACME Industries LLC", "role": "plaintiff"}]}

    engine.capture_edit(original, edited)
    rules = engine.get_rules(limit=3)

    assert len(rules) >= 1


def test_frequency_increment(engine):
    original = {"parties": [{"name": "ACME", "role": "plaintiff"}]}
    edited = {"parties": [{"name": "ACME LLC", "role": "plaintiff"}]}

    engine.capture_edit(original, edited)
    engine.capture_edit(original, edited)

    stats = engine.get_stats()
    assert stats["total_frequency"] == 2


def test_get_rules_limit(engine):
    original = {"parties": [{"name": "X", "role": "plaintiff"}]}
    edited1 = {"parties": [{"name": "Y", "role": "plaintiff"}]}
    edited2 = {"claims": [{"description": "A", "supporting_evidence": ["c1"]}]}

    engine.capture_edit(original, edited1)
    engine.capture_edit(original, edited2)

    rules = engine.get_rules(limit=1)
    assert len(rules) == 1


def test_deep_diff_nested(engine):
    original = {
        "parties": [{"name": "ACME", "role": "plaintiff"}],
        "key_facts": [{"statement": "Breach alleged", "supporting_evidence": ["c1"]}],
    }
    edited = {
        "parties": [{"name": "ACME LLC", "role": "plaintiff"}],
        "key_facts": [
            {"statement": "Material breach alleged", "supporting_evidence": ["c1"]}
        ],
    }

    engine.capture_edit(original, edited)
    rules = engine.get_rules(limit=5)

    # With generalization, rules should be principles not literal values
    assert len(rules) >= 1
    # Rules should not contain JSON blobs
    for rule in rules:
        assert not rule.startswith("{")
        assert len(rule) > 10


def test_party_removal_generalization(engine):
    """Test that removing officers from parties generates a reusable rule."""
    original = {
        "parties": [
            {"name": "ACME INDUSTRIES LLC", "role": "plaintiff"},
            {"name": "John Doe, CEO", "role": ""},
        ]
    }
    edited = {
        "parties": [
            {"name": "ACME INDUSTRIES LLC", "role": "plaintiff"}
        ]
    }

    engine.capture_edit(original, edited)
    rules = engine.get_rules(limit=3)

    assert len(rules) >= 1
    # Should be a generalized principle about organizational entities
    assert any("organizational" in r.lower() or "officer" in r.lower() for r in rules)


def test_claim_removal_generalization(engine):
    """Test that removing unsupported claims generates a reusable rule."""
    original = {
        "claims": [
            {"description": "Breach of Contract", "supporting_evidence": ["c1"]}
        ]
    }
    edited = {"claims": []}

    engine.capture_edit(original, edited)
    rules = engine.get_rules(limit=3)

    assert len(rules) >= 1
    assert any("claim" in r.lower() for r in rules)


def test_stats(engine):
    original = {"parties": [{"name": "A", "role": "plaintiff"}]}
    edited = {"parties": [{"name": "B", "role": "plaintiff"}]}

    engine.capture_edit(original, edited)
    stats = engine.get_stats()

    assert stats["rule_count"] == 1
    assert stats["total_frequency"] == 1
