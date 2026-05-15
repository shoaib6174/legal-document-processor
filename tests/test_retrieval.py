import pytest
from core.retrieval import EvidenceRetriever
from core.models import TextChunk


@pytest.fixture
def retriever():
    r = EvidenceRetriever(persist_dir="./data/chroma_db_test")
    r.clear()
    return r


def test_index_and_retrieve(retriever):
    chunks = [
        TextChunk(
            chunk_id="c1",
            text="The plaintiff alleges breach of contract on January 15, 2024.",
            source_doc="doc1.pdf",
            page_num=1,
            confidence_score=0.95,
        ),
        TextChunk(
            chunk_id="c2",
            text="Defendant denies all allegations and claims the contract was void.",
            source_doc="doc1.pdf",
            page_num=2,
            confidence_score=0.92,
        ),
        TextChunk(
            chunk_id="c3",
            text="The parties met on February 1, 2024 to discuss settlement options.",
            source_doc="doc1.pdf",
            page_num=3,
            confidence_score=0.88,
        ),
    ]
    retriever.index(chunks)

    results = retriever.retrieve("What did the plaintiff allege?", top_k=2)
    assert len(results) > 0
    assert any("plaintiff" in r.text.lower() for r in results)


def test_retrieve_exact_case_number(retriever):
    chunks = [
        TextChunk(
            chunk_id="c1",
            text="Case No. PSL-2024-0017 involves property dispute.",
            source_doc="doc2.pdf",
            page_num=1,
            confidence_score=0.9,
        ),
        TextChunk(
            chunk_id="c2",
            text="General litigation procedures apply here.",
            source_doc="doc2.pdf",
            page_num=2,
            confidence_score=0.9,
        ),
    ]
    retriever.index(chunks)

    results = retriever.retrieve("PSL-2024-0017", top_k=2)
    assert len(results) > 0
    assert any("PSL-2024-0017" in r.text for r in results)


def test_rrf_fusion_ranks_in_order(retriever):
    chunks = [
        TextChunk(
            chunk_id="c1",
            text="Contract breach by defendant ABC Corp.",
            source_doc="doc3.pdf",
            page_num=1,
            confidence_score=0.9,
        ),
        TextChunk(
            chunk_id="c2",
            text="ABC Corp denies the breach allegation.",
            source_doc="doc3.pdf",
            page_num=2,
            confidence_score=0.9,
        ),
    ]
    retriever.index(chunks)

    results = retriever.retrieve("ABC Corp contract breach", top_k=2)
    assert len(results) == 2
    assert results[0].score >= results[1].score
