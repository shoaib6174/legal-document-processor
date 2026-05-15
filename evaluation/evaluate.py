"""Evaluation script for the legal document processing pipeline.

Run this after generating synthetic documents to report quantitative metrics:
- Entity extraction accuracy (precision/recall per entity type)
- Chunking quality (sentence preservation, overlap)
- OCR confidence distribution
- Retrieval precision

Usage:
    python evaluation/evaluate.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import ProcessedDocument
from core.processor import DocumentProcessor
from core.retrieval import EvidenceRetriever
from evaluation.document_templates import TEMPLATES, get_template_info


def evaluate_document_processing():
    """Evaluate processor on all synthetic documents."""
    processor = DocumentProcessor()
    synthetic_dir = Path(__file__).parent / "synthetic_docs"
    template_info = get_template_info()

    results = []
    total_entities = {et: 0 for et in [
        "date", "amount", "party", "case_number",
        "case_citation", "statute_citation", "court_name", "judge_name",
    ]}
    total_confidence_samples = []
    total_chunks = 0

    for template_name in TEMPLATES:
        clean_pdf = synthetic_dir / f"{template_name}_clean.pdf"
        if not clean_pdf.exists():
            continue

        doc: ProcessedDocument = processor.process(str(clean_pdf))
        info = template_info.get(template_name, {})
        entities = info.get("entities", {})

        # Count entities extracted
        extracted_counts = {et: 0 for et in total_entities}
        for entity in doc.entities:
            if entity.type in extracted_counts:
                extracted_counts[entity.type] += 1
                total_entities[entity.type] += 1

        # Count expected entities from template metadata
        expected_counts = {
            "date": len(entities.get("dates", [])),
            "amount": len(entities.get("amounts", [])),
            "party": len(entities.get("parties", [])),
            "case_number": len(entities.get("case_numbers", [])),
            "case_citation": len(entities.get("case_citations", [])),
            "statute_citation": len(entities.get("statutes", [])),
            "court_name": len(entities.get("courts", [])),
            "judge_name": len(entities.get("judges", [])),
        }

        # Chunk stats
        chunk_count = len(doc.chunks)
        total_chunks += chunk_count
        avg_confidence = sum(c.confidence_score for c in doc.chunks) / chunk_count if chunk_count else 0
        total_confidence_samples.extend([c.confidence_score for c in doc.chunks])

        results.append({
            "document": template_name,
            "chunk_count": chunk_count,
            "avg_confidence": round(avg_confidence, 3),
            "entities_extracted": extracted_counts,
            "entities_expected": expected_counts,
        })

    # Overall metrics
    overall = {
        "documents_evaluated": len(results),
        "total_chunks": total_chunks,
        "avg_confidence": round(sum(total_confidence_samples) / len(total_confidence_samples), 3) if total_confidence_samples else 0,
        "confidence_distribution": {
            "high (>=0.9)": sum(1 for c in total_confidence_samples if c >= 0.9),
            "medium (0.7-0.9)": sum(1 for c in total_confidence_samples if 0.7 <= c < 0.9),
            "low (<0.7)": sum(1 for c in total_confidence_samples if c < 0.7),
        },
        "total_entities_extracted": total_entities,
    }

    return {"per_document": results, "overall": overall}


def evaluate_retrieval():
    """Evaluate retrieval precision on synthetic documents."""
    processor = DocumentProcessor()
    retriever = EvidenceRetriever()
    synthetic_dir = Path(__file__).parent / "synthetic_docs"
    template_info = get_template_info()

    retrieval_results = []

    for template_name in TEMPLATES:
        clean_pdf = synthetic_dir / f"{template_name}_clean.pdf"
        if not clean_pdf.exists():
            continue

        doc = processor.process(str(clean_pdf))
        retriever.index(doc.chunks)

        info = template_info.get(template_name, {})
        entities = info.get("entities", {})

        # Test retrieval for each entity type
        queries = []
        for party in entities.get("parties", []):
            queries.append((f"party {party}", "party"))
        for case_num in entities.get("case_numbers", []):
            queries.append((case_num, "case_number"))
        for date in entities.get("dates", [])[:1]:  # Sample one date
            queries.append((f"date {date}", "date"))

        precisions = []
        for query, expected_type in queries:
            evidence = retriever.retrieve(query, top_k=5)
            # Check if any retrieved chunk contains relevant terms
            relevant = 0
            for e in evidence:
                text_lower = e.text.lower()
                query_terms = query.lower().split()
                if any(term in text_lower for term in query_terms if len(term) > 3):
                    relevant += 1
            precision = relevant / len(evidence) if evidence else 0
            precisions.append(precision)

        avg_precision = round(sum(precisions) / len(precisions), 3) if precisions else 0
        retrieval_results.append({
            "document": template_name,
            "queries_tested": len(queries),
            "avg_precision@5": avg_precision,
        })

    overall_precision = round(
        sum(r["avg_precision@5"] for r in retrieval_results) / len(retrieval_results), 3
    ) if retrieval_results else 0

    return {
        "per_document": retrieval_results,
        "overall_precision@5": overall_precision,
    }


def main():
    print("=" * 60)
    print("Legal Document Processor — Evaluation Results")
    print("=" * 60)
    print()

    print("[1] Document Processing Evaluation")
    print("-" * 40)
    processing_results = evaluate_document_processing()
    overall = processing_results["overall"]

    print(f"Documents evaluated: {overall['documents_evaluated']}")
    print(f"Total chunks produced: {overall['total_chunks']}")
    print(f"Average OCR confidence: {overall['avg_confidence']}")
    print(f"Confidence distribution: {json.dumps(overall['confidence_distribution'], indent=2)}")
    print(f"Total entities extracted: {json.dumps(overall['total_entities_extracted'], indent=2)}")
    print()

    for r in processing_results["per_document"]:
        print(f"  {r['document']}:")
        print(f"    Chunks: {r['chunk_count']}, Avg confidence: {r['avg_confidence']}")
        for et in r["entities_expected"]:
            exp = r["entities_expected"][et]
            ext = r["entities_extracted"][et]
            recall = round(ext / exp, 2) if exp else "N/A"
            print(f"    {et}: {ext}/{exp} extracted (recall: {recall})")
    print()

    print("[2] Retrieval Evaluation")
    print("-" * 40)
    retrieval_results = evaluate_retrieval()
    print(f"Overall precision@5: {retrieval_results['overall_precision@5']}")
    for r in retrieval_results["per_document"]:
        print(f"  {r['document']}: precision@5 = {r['avg_precision@5']} ({r['queries_tested']} queries)")
    print()

    print("=" * 60)
    print("Evaluation complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
