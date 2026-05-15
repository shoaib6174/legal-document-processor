import pytest
from pathlib import Path
from core.processor import DocumentProcessor
from core.models import TextChunk


@pytest.fixture
def processor():
    return DocumentProcessor()


def test_chunk_text_basic(processor):
    text = " ".join([f"word{i}" for i in range(100)])
    chunks = processor._chunk_text(text, "test.txt", 1, 1.0, chunk_size=30, overlap=5)

    assert len(chunks) > 0
    assert chunks[0].text.startswith("word0")
    assert chunks[0].source_doc == "test.txt"
    assert chunks[0].page_num == 1
    assert chunks[0].confidence_score == 1.0


def test_chunk_text_overlap(processor):
    # Sentence-aware chunking: use multiple sentences to test overlap
    sentences = [f"This is sentence {i} with some words." for i in range(20)]
    text = " ".join(sentences)
    chunks = processor._chunk_text(text, "test.txt", 1, 1.0, chunk_size=30, overlap=10)

    assert len(chunks) >= 2
    # Verify sentences are not split across chunks
    for chunk in chunks:
        # Each chunk should start with a complete sentence
        text_stripped = chunk.text.strip()
        assert text_stripped[0].isupper() or text_stripped[0] == '"'
    # Overlap: some content from chunk 0 should appear in chunk 1
    assert any(sent in chunks[0].text and sent in chunks[1].text for sent in sentences)

def test_chunk_text_preserves_sentences(processor):
    """Sentences should never be split across chunks."""
    text = "First sentence here. Second sentence here. Third sentence here."
    chunks = processor._chunk_text(text, "test.txt", 1, 1.0, chunk_size=5, overlap=2)
    # Even with tiny chunk_size, each chunk should contain complete sentences
    for chunk in chunks:
        assert "." in chunk.text
        # Should not end mid-sentence (no trailing incomplete sentence)
        # Each chunk should have complete sentences only


def test_chunk_text_empty(processor):
    chunks = processor._chunk_text("", "test.txt", 1, 1.0)
    assert chunks == []


def test_extract_entities_dates(processor):
    raw_text = "The meeting was on 03/15/2024 and the deadline is 2024-06-01."
    chunks = [
        TextChunk(
            chunk_id="c1",
            text=raw_text,
            source_doc="test",
            page_num=1,
            confidence_score=1.0,
        )
    ]
    entities = processor._extract_entities(raw_text, chunks)
    dates = [e for e in entities if e.type == "date"]

    assert len(dates) == 2
    assert dates[0].value == "03/15/2024"
    assert dates[1].value == "2024-06-01"


def test_extract_entities_amounts(processor):
    raw_text = "The settlement was $1,250,000 and fees were $25,000."
    chunks = [
        TextChunk(
            chunk_id="c1",
            text=raw_text,
            source_doc="test",
            page_num=1,
            confidence_score=1.0,
        )
    ]
    entities = processor._extract_entities(raw_text, chunks)
    amounts = [e for e in entities if e.type == "amount"]

    assert len(amounts) == 2
    assert "$1,250,000" in [a.value for a in amounts]
    assert "$25,000" in [a.value for a in amounts]


def test_extract_entities_parties(processor):
    raw_text = "ACME INDUSTRIES LLC and Smith Corp are parties to this agreement."
    chunks = [
        TextChunk(
            chunk_id="c1",
            text=raw_text,
            source_doc="test",
            page_num=1,
            confidence_score=1.0,
        )
    ]
    entities = processor._extract_entities(raw_text, chunks)
    parties = [e for e in entities if e.type == "party"]

    assert len(parties) >= 1
    assert any("ACME" in p.value for p in parties)


def test_extract_entities_written_dates(processor):
    """Written-out month names should be extracted."""
    raw_text = "The agreement was signed on March 15, 2024 and reviewed on January 10, 2024."
    chunks = [
        TextChunk(
            chunk_id="c1",
            text=raw_text,
            source_doc="test",
            page_num=1,
            confidence_score=1.0,
        )
    ]
    entities = processor._extract_entities(raw_text, chunks)
    dates = [e for e in entities if e.type == "date"]

    assert len(dates) == 2
    assert "March 15, 2024" in [d.value for d in dates]
    assert "January 10, 2024" in [d.value for d in dates]


def test_extract_entities_party_with_trailing_punctuation(processor):
    """Company suffixes followed by punctuation (e.g., Inc., Corp.) should match correctly."""
    raw_text = "SMITH VENTURES INC. and ATLANTIC CONSTRUCTION CORP., are defendants."
    chunks = [
        TextChunk(
            chunk_id="c1",
            text=raw_text,
            source_doc="test",
            page_num=1,
            confidence_score=1.0,
        )
    ]
    entities = processor._extract_entities(raw_text, chunks)
    parties = [e for e in entities if e.type == "party"]

    assert len(parties) == 2
    assert any("SMITH VENTURES INC" == p.value for p in parties)
    assert any("ATLANTIC CONSTRUCTION CORP" == p.value for p in parties)


def test_extract_entities_party_blocks_titles(processor):
    """Titles like CEO or CFO should not be absorbed into party names."""
    raw_text = "John Doe, CEO and ACME INDUSTRIES LLC are parties."
    chunks = [
        TextChunk(
            chunk_id="c1",
            text=raw_text,
            source_doc="test",
            page_num=1,
            confidence_score=1.0,
        )
    ]
    entities = processor._extract_entities(raw_text, chunks)
    parties = [e for e in entities if e.type == "party"]

    # Only ACME INDUSTRIES LLC should match; "CEO" must not be part of a party name
    assert len(parties) == 1
    assert parties[0].value == "ACME INDUSTRIES LLC"


def test_extract_entities_party_two_on_same_line(processor):
    """Two company names on the same line should be extracted as two separate parties."""
    raw_text = "ACME INDUSTRIES LLC             SMITH VENTURES INC."
    chunks = [
        TextChunk(
            chunk_id="c1",
            text=raw_text,
            source_doc="test",
            page_num=1,
            confidence_score=1.0,
        )
    ]
    entities = processor._extract_entities(raw_text, chunks)
    parties = [e for e in entities if e.type == "party"]

    assert len(parties) == 2
    assert any("ACME INDUSTRIES LLC" == p.value for p in parties)
    assert any("SMITH VENTURES INC" == p.value for p in parties)


def test_extract_entities_case_numbers(processor):
    raw_text = "Case No. PSL-2024-0017 involves property dispute."
    chunks = [
        TextChunk(
            chunk_id="c1",
            text=raw_text,
            source_doc="test",
            page_num=1,
            confidence_score=1.0,
        )
    ]
    entities = processor._extract_entities(raw_text, chunks)
    case_numbers = [e for e in entities if e.type == "case_number"]

    assert len(case_numbers) == 1
    assert case_numbers[0].value == "PSL-2024-0017"


def test_extract_entities_deduplication(processor):
    """Same entity appearing in multiple chunks should only be extracted once."""
    raw_text = "The date is 03/15/2024. As mentioned, 03/15/2024 is important."
    chunks = [
        TextChunk(
            chunk_id="c1",
            text="The date is 03/15/2024.",
            source_doc="test",
            page_num=1,
            confidence_score=1.0,
        ),
        TextChunk(
            chunk_id="c2",
            text="As mentioned, 03/15/2024 is important.",
            source_doc="test",
            page_num=2,
            confidence_score=1.0,
        ),
    ]
    entities = processor._extract_entities(raw_text, chunks)
    dates = [e for e in entities if e.type == "date"]

    assert len(dates) == 1
    assert dates[0].value == "03/15/2024"


def test_process_text_file(processor, tmp_path):
    """Test processing a plain text file."""
    test_file = tmp_path / "test_contract.txt"
    test_file.write_text(
        "SERVICE AGREEMENT between ACME LLC and SMITH CORP on 01/15/2024. "
        "Total fee: $50,000. Case No. PSL-2024-0001."
    )

    result = processor.process(test_file)

    assert result.source_path == str(test_file)
    assert "ACME LLC" in result.raw_text
    assert len(result.chunks) > 0
    assert len(result.entities) >= 4  # date, amount, 2 parties, case number


def test_extract_entities_individual_all_caps(processor):
    """ALL CAPS individual names followed by ', an individual' should be extracted as parties."""
    raw_text = "ELENA MARTINEZ, an individual residing at 450 Park Avenue."
    chunks = [
        TextChunk(
            chunk_id="c1",
            text=raw_text,
            source_doc="test",
            page_num=1,
            confidence_score=1.0,
        )
    ]
    entities = processor._extract_entities(raw_text, chunks)
    parties = [e for e in entities if e.type == "party"]

    assert len(parties) == 1
    assert parties[0].value == "ELENA MARTINEZ"


def test_extract_entities_individual_with_title(processor):
    """Title-prefixed individual names followed by ', an individual' should be extracted as parties."""
    raw_text = "DR. AMANDA PARK, an individual (the 'Executive')."
    chunks = [
        TextChunk(
            chunk_id="c1",
            text=raw_text,
            source_doc="test",
            page_num=1,
            confidence_score=1.0,
        )
    ]
    entities = processor._extract_entities(raw_text, chunks)
    parties = [e for e in entities if e.type == "party"]

    assert len(parties) == 1
    assert parties[0].value == "DR. AMANDA PARK"


def test_extract_entities_individual_does_not_match_org(processor):
    """Individual patterns should not accidentally match organizational parties."""
    raw_text = "NEXUS FINANCIAL SERVICES INC., a New York corporation."
    chunks = [
        TextChunk(
            chunk_id="c1",
            text=raw_text,
            source_doc="test",
            page_num=1,
            confidence_score=1.0,
        )
    ]
    entities = processor._extract_entities(raw_text, chunks)
    parties = [e for e in entities if e.type == "party"]

    assert len(parties) == 1
    assert parties[0].value == "NEXUS FINANCIAL SERVICES INC"


def test_extract_entities_case_citation(processor):
    """Case citations like 'Smith v. Jones, 123 F.3d 456' should be extracted."""
    raw_text = "See Smith v. Jones, 123 F.3d 456 (9th Cir. 2024). Also cited 2024 WL 1234567."
    chunks = [
        TextChunk(
            chunk_id="c1",
            text=raw_text,
            source_doc="test",
            page_num=1,
            confidence_score=1.0,
        )
    ]
    entities = processor._extract_entities(raw_text, chunks)
    citations = [e for e in entities if e.type == "case_citation"]

    assert len(citations) == 2
    assert any("Smith v. Jones" in c.value for c in citations)
    assert any("2024 WL 1234567" in c.value for c in citations)


def test_extract_entities_statute_citation(processor):
    """Statute citations like '15 U.S.C. § 1' should be extracted."""
    raw_text = "Violations of 15 U.S.C. § 1 and 28 U.S.C. § 1331(a) are alleged."
    chunks = [
        TextChunk(
            chunk_id="c1",
            text=raw_text,
            source_doc="test",
            page_num=1,
            confidence_score=1.0,
        )
    ]
    entities = processor._extract_entities(raw_text, chunks)
    statutes = [e for e in entities if e.type == "statute_citation"]

    assert len(statutes) == 2
    assert any("15 U.S.C. § 1" in s.value for s in statutes)
    assert any("28 U.S.C. § 1331(a)" in s.value for s in statutes)


def test_extract_entities_court_name(processor):
    """Court names should be extracted."""
    raw_text = "Filed in the United States District Court for the Southern District of New York."
    chunks = [
        TextChunk(
            chunk_id="c1",
            text=raw_text,
            source_doc="test",
            page_num=1,
            confidence_score=1.0,
        )
    ]
    entities = processor._extract_entities(raw_text, chunks)
    courts = [e for e in entities if e.type == "court_name"]

    assert len(courts) == 1
    assert "United States District Court" in courts[0].value


def test_extract_entities_judge_name(processor):
    """Judge names should be extracted."""
    raw_text = "Hon. John Smith presided. Judge Jane Doe issued the ruling."
    chunks = [
        TextChunk(
            chunk_id="c1",
            text=raw_text,
            source_doc="test",
            page_num=1,
            confidence_score=1.0,
        )
    ]
    entities = processor._extract_entities(raw_text, chunks)
    judges = [e for e in entities if e.type == "judge_name"]

    assert len(judges) == 2
    assert any("Hon. John Smith" in j.value for j in judges)
    assert any("Judge Jane Doe" in j.value for j in judges)


def test_extract_entities_deduplication_across_types(processor):
    """Same text matched by different entity types should still dedupe within each type."""
    raw_text = "Smith v. Jones, 123 F.3d 456. Smith v. Jones, 123 F.3d 456."
    chunks = [
        TextChunk(
            chunk_id="c1",
            text=raw_text,
            source_doc="test",
            page_num=1,
            confidence_score=1.0,
        )
    ]
    entities = processor._extract_entities(raw_text, chunks)
    citations = [e for e in entities if e.type == "case_citation"]

    assert len(citations) == 1  # deduplicated
