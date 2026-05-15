import pytest
from core.feedback import FeedbackEngine


@pytest.fixture
def engine():
    fb = FeedbackEngine(db_path="./data/feedback_test.db")
    # Clean slate for each test
    conn = __import__("sqlite3").connect(fb.db_path)
    conn.execute("DELETE FROM corrections")
    conn.commit()
    conn.close()
    return fb


def test_capture_simple_edit(engine):
    original = {"parties": [{"name": "ACME LLC", "role": "plaintiff"}]}
    edited = {"parties": [{"name": "ACME Industries LLC", "role": "plaintiff"}]}

    engine.capture_edit(original, edited)
    rules = engine.get_rules(limit=3)

    assert len(rules) >= 1
    assert any("ACME Industries LLC" in r for r in rules)


def test_frequency_increment(engine):
    original = {"parties": [{"name": "ACME", "role": "plaintiff"}]}
    edited = {"parties": [{"name": "ACME LLC", "role": "plaintiff"}]}

    engine.capture_edit(original, edited)
    engine.capture_edit(original, edited)

    rules = engine.get_rules(limit=3)
    assert len(rules) == 1
    assert "seen 2 times" in rules[0]


def test_get_rules_limit(engine):
    original = {"parties": [{"name": "X", "role": "plaintiff"}]}
    edited1 = {"parties": [{"name": "Y", "role": "plaintiff"}]}
    edited2 = {"parties": [{"name": "Z", "role": "plaintiff"}]}

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

    paths = [r.split("'", 2)[1] for r in rules]
    assert "parties[0].name" in paths
    assert "key_facts[0].statement" in paths


def test_stats(engine):
    original = {"parties": [{"name": "A", "role": "plaintiff"}]}
    edited = {"parties": [{"name": "B", "role": "plaintiff"}]}

    engine.capture_edit(original, edited)
    stats = engine.get_stats()

    assert stats["rule_count"] == 1
    assert stats["total_frequency"] == 1
