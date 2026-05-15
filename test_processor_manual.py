"""Manual test script for core/processor.py using synthetic PDFs."""

from pathlib import Path
from core.processor import DocumentProcessor

DOCS_DIR = Path(__file__).parent / "evaluation" / "synthetic_docs"
processor = DocumentProcessor()

for pdf_path in sorted(DOCS_DIR.glob("*.pdf")):
    print(f"\n{'='*60}")
    print(f"FILE: {pdf_path.name}")
    print("=" * 60)

    result = processor.process(pdf_path)

    print(f"\n--- Raw text (first 500 chars) ---")
    print(result.raw_text[:500])

    print(f"\n--- Stats ---")
    print(f"  Total chars: {len(result.raw_text)}")
    print(f"  Chunks: {len(result.chunks)}")
    print(f"  Entities: {len(result.entities)}")

    print(f"\n--- Chunks ---")
    for i, chunk in enumerate(result.chunks[:3]):
        print(f"  [{i}] {chunk.chunk_id} | conf={chunk.confidence_score:.2f} | text={chunk.text[:80]}...")
    if len(result.chunks) > 3:
        print(f"  ... ({len(result.chunks) - 3} more chunks)")

    print(f"\n--- Entities ---")
    for e in result.entities:
        print(f"  [{e.type:12}] {e.value:20} (from {e.source_chunk_id})")

    print(f"\n{'='*60}")
