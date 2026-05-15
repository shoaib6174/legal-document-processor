# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Context

This is a **Pearson Specter Litt AI Engineer take-home assessment** — a legal document processing pipeline with OCR, hybrid retrieval, grounded LLM generation, and operator feedback learning. The deadline was 2026-05-15. The system generates structured **Case Fact Summaries** (parties, dates, claims, key facts, uncertainties) from messy legal inputs.

**Key constraint:** The assessment values engineering quality, grounding, and system design over visual polish. Every generated fact must cite a source chunk_id; unsupported facts go in `uncertainties`.

## Tech Stack

- **Backend:** FastAPI, Python 3.11+
- **OCR:** `pymupdf` (native text) + `pytesseract` + `pdf2image` (scan fallback)
- **Embeddings:** `sentence-transformers` (`all-MiniLM-L6-v2`, 384-dim, CPU)
- **Vector Store:** ChromaDB (persistent, `./data/chroma_db`)
- **Sparse Search:** `rank-bm25`
- **LLM:** Groq API (`llama-3.3-70b-versatile`)
- **Feedback Store:** SQLite (`./data/feedback.db`)
- **UI:** Vanilla HTML/JS served by FastAPI static files

## Common Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_processor.py -v

# Generate synthetic test documents (creates PDFs in evaluation/synthetic_docs/)
python evaluation/generate_samples.py

# Start the FastAPI server (when main.py exists)
python main.py
# Server runs on http://localhost:8000
```

**Prerequisites:** Tesseract OCR must be installed (`brew install tesseract` on macOS). A `GROQ_API_KEY` environment variable is required for draft generation.

## Architecture

The system follows a **5-stage pipeline**:

```
Upload (PDF/Image)
    │
    ▼
┌─────────────────┐
│ 1. PROCESS      │──▶ OCR + regex structuring ──▶ raw_text + chunks + entities
│   (processor)   │     Low-confidence chunks flagged but kept in pipeline
└─────────────────┘
    │
    ▼
┌─────────────────┐
│ 2. INDEX        │──▶ Embed chunks ──▶ ChromaDB + BM25
│   (retriever)   │     Metadata: source_doc, page_num, confidence_score
└─────────────────┘
    │
    ▼ (User triggers "Generate")
┌─────────────────┐
│ 3. RETRIEVE     │──▶ Hybrid dense + sparse search ──▶ RRF fusion
│   (retriever)   │     Returns top-k passages with chunk_id citations
└─────────────────┘
    │
    ▼
┌─────────────────┐
│ 4. GENERATE     │──▶ Few-shot prompt + evidence + correction rules
│   (generator)   │     Groq LLM produces structured CaseFactSummary JSON
└─────────────────┘
    │
    ▼
┌─────────────────┐
│ 5. LEARN        │──▶ Diff original vs edited ──▶ Extract rules
│   (feedback)    │     SQLite storage; top rules injected into future prompts
└─────────────────┘
```

### Component Responsibilities

| Module | File | Role |
|---|---|---|
| Document Processor | `core/processor.py` | Hybrid OCR (native → fallback), word-level chunking (~300 words, 50-word overlap), regex entity extraction (dates, amounts, parties, case numbers), per-chunk confidence scoring |
| Evidence Retriever | `core/retrieval.py` | ChromaDB dense search + BM25 sparse search, Reciprocal Rank Fusion (RRF, k=60), returns `RetrievedEvidence` with source attribution |
| Draft Generator | `core/generator.py` | Groq API client, assembles system prompt with grounding rules and correction rules, enforces JSON output (`response_format={"type": "json_object"}`), returns `CaseFactSummary` |
| Feedback Engine | `core/feedback.py` | SQLite-backed diff capture, deep-diff of original vs edited JSON, frequency-based rule ranking, rule injection into generator prompts |
| Data Models | `core/models.py` | Pydantic models: `ProcessedDocument`, `TextChunk`, `ExtractedEntity`, `RetrievedEvidence`, `CaseFactSummary` |

### Hybrid Retrieval Strategy

Retrieval intentionally combines two methods:
- **Dense (ChromaDB + sentence-transformers):** Catches semantic similarity (e.g., "liability claim" ≈ "damages request")
- **Sparse (BM25):** Catches exact matches on case numbers like "PSL-2024-0017" that embeddings might miss

RRF fusion merges rankings without requiring score calibration between the two methods.

### Feedback Loop Design

The feedback engine does **not** just store diffs — it extracts reusable correction rules:

1. Operator edits the JSON-structured draft inline in the UI
2. `FeedbackEngine.capture_edit()` performs a recursive deep-diff
3. Each changed field path + original → edited value becomes a rule stored in SQLite with a frequency counter
4. `FeedbackEngine.get_rules(limit=3)` returns the most frequent rules
5. `DraftGenerator` injects these as "CORRECTION RULES" into the system prompt before generation

### Chunking and Confidence

- Chunks are word-based (not token-based) for simplicity: ~300 words, 50-word overlap
- `chunk_id` format: `{source_doc}_p{page_num}_c{index}` — used for inline citations
- Confidence comes from Tesseract word-level OCR data; native PDF text gets 1.0
- Low-confidence chunks (< 0.7) are **kept, not dropped** — the generator sees the confidence and can flag content in `uncertainties`

## Current Implementation Status

The project is a **partially implemented MVP**. Check the file tree before assuming components exist:

- ✅ `core/models.py` — Pydantic models complete
- ✅ `core/processor.py` — DocumentProcessor with hybrid OCR, chunking, entity extraction
- ✅ `core/retrieval.py` — ChromaDB + BM25 + RRF hybrid retrieval
- ✅ `core/generator.py` — Groq API integration with grounded prompting
- ✅ `tests/test_processor.py` — Unit tests for chunking and entity extraction
- ✅ `tests/test_retrieval.py` — Unit tests for hybrid retrieval
- ✅ `tests/test_generator.py` — Unit tests for draft generation
- ✅ `evaluation/generate_samples.py` — Creates clean and scanned synthetic PDFs
- ⬜ `core/feedback.py` — Planned: SQLite feedback store and rule extraction
- ⬜ `main.py` — Planned: FastAPI app with `/upload`, `/generate`, `/feedback` endpoints
- ⬜ `static/index.html`, `static/app.js` — Planned: Minimal drag-and-drop UI

The detailed implementation plan lives in `docs/superpowers/plans/2026-05-15-legal-doc-processor-mvp.md` and `docs/superpowers/specs/2026-05-15-legal-doc-processor-mvp-design.md`.

## Design Documents

- `ARCHITECTURE.md` — Full system design with tradeoffs, assumptions, and rubric alignment
- `ASSESSMENT.md` — Original take-home requirements and rubric (100 points)
- `docs/superpowers/plans/` — Implementation plan with phase breakdown and build order
- `docs/superpowers/specs/` — MVP design spec with component interfaces and simplifications

## Workflow Notes

- **Commit messages:** Do not mention AI assistants (Claude, GPT, etc.) or model names in commit messages or code comments. Use standard conventional commit format.

## Evaluation / Testing

- Synthetic test documents are generated by `evaluation/generate_samples.py` into `evaluation/synthetic_docs/`
- The script creates both clean text PDFs and scanned/image PDFs (the latter tests the OCR fallback path)
- Processor tests cover chunking overlap, empty input, entity regex patterns, and deduplication
