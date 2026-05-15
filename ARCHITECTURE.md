---
name: legal-doc-processor-design
description: System design for Pearson Specter Litt AI Engineer take-home assessment — legal document ingestion, grounded retrieval, draft generation, and learning from operator edits.
metadata:
  type: project
---

# Legal Document Processor — System Design

**Assessment:** Pearson Specter Litt — AI Engineer Take-Home  
**Date:** 2026-05-15  
**Author:** Mohammad Shoaib  
**Approach:** Full RAG Pipeline with Feedback Loop (Approach A)

---

## 1. Overview

Build a system that ingests messy legal-style documents (scanned PDFs, handwritten notes, low-resolution images), extracts usable text and structured data, retrieves relevant evidence, generates a grounded **Case Fact Summary** draft, and improves over time by learning from operator edits.

**Key Constraints:**
- 2-day build deadline (submit by 2026-05-15)
- Must demonstrate grounding, not legal correctness
- Must show real improvement loop, not just diff viewing
- Evaluators care more about system design than visual polish

**Output Type:** Case Fact Summary — structured extraction of parties, dates, key facts, claims, financial summary, document summary, and uncertainties.

---

## 2. Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Web UI        │────▶│   FastAPI        │────▶│  Document       │
│  (HTML/JS)      │◀────│   Backend        │◀────│  Processor      │
└─────────────────┘     └──────────────────┘     │  (OCR + Struct) │
                                                 └─────────────────┘
                            │                             │
                            ▼                             ▼
                     ┌─────────────┐              ┌─────────────┐
                     │   Groq      │              │  ChromaDB   │
                     │   LLM       │              │  (Vectors)  │
                     └─────────────┘              └─────────────┘
                            ▲                             │
                            │                             │
                            └─────────────┬───────────────┘
                                          ▼
                                   ┌─────────────┐
                                   │  Feedback   │
                                   │  Store      │
                                   │  (SQLite)   │
                                   └─────────────┘
```

**Six Stages:**
1. **Ingest** — accept PDFs/images, run OCR with deskewing, extract structured fields
2. **Embed & Store** — sentence-aware chunking, embed, store in ChromaDB + BM25
3. **Retrieve** — hybrid dense + sparse search with legal query expansion, return cited passages
4. **Generate** — two-stage generation: analyze evidence, then produce structured output with correction rules
5. **Verify** — post-generation semantic grounding check, move ungrounded facts to uncertainties
6. **Learn** — capture operator edits, extract patterns with effectiveness scoring, update future prompts

---

## 3. Component Breakdown

### 3.1 Document Processor (`core/processor.py`)

**Purpose:** Turn messy inputs into clean, structured text.

**Interface:**
```python
class DocumentProcessor:
    def process(self, file_path: Path, source_doc: str | None = None) -> ProcessedDocument
```

**Returns:**
- `raw_text`: full extracted text
- `chunks`: List[TextChunk] with page metadata and confidence scores
- `entities`: List[ExtractedEntity] — 8 entity types with start/end positions

**Implementation:**
- **Hybrid OCR strategy:** Try `pymupdf` first (fast text extraction for clean PDFs), fall back to `pytesseract` + image preprocessing for scanned/noisy inputs
- **Deskewing:** `pytesseract.image_to_osd()` detects skew angle, image is auto-rotated before OCR
- **Image preprocessing:** Grayscale, contrast boost (2x), median filter denoise
- **Sentence-aware chunking:** Text is split into sentences first (with abbreviation protection for Mr., Mrs., Dr., Inc., U.S.C., etc.), then grouped into ~300-word chunks. Sentences are never split across chunks.
- **Structured extraction:** Regex patterns for dates, amounts, party names (ALL CAPS + suffix), individual parties (", an individual"), case numbers, case citations (Smith v. Jones, 123 F.3d 456), statute citations (15 U.S.C. § 1), court names, and judge names
- **Entity position tracking:** `ExtractedEntity` records `start` and `end` character offsets for inline highlighting in the UI
- **Chunk-to-offset mapping:** `_find_chunk_for_offset()` maps any character position back to its containing chunk_id
- **PDF rendering:** `render_pages()` renders each PDF page to PNG for the split-screen UI viewer
- **Noise handling:** Flag low-confidence chunks (< 0.7) but keep them — pass confidence to retrieval layer for downstream decisions

### 3.2 Evidence Retriever (`core/retrieval.py`)

**Purpose:** Surface relevant passages with source attribution.

**Interface:**
```python
class EvidenceRetriever:
    def index(self, chunks: List[TextChunk]) -> None
    def retrieve(self, query: str, top_k: int = 5, use_expansion: bool = True) -> List[RetrievedEvidence]
```

**Returns (per evidence item):**
- `text`: the chunk
- `source_doc`: document name
- `page_num`: page number
- `score`: fused RRF similarity score
- `chunk_id`: unique reference for citations
- `retrieval_method`: "dense", "sparse", or "hybrid"

**Implementation — Hybrid Search:**
- **Dense:** ChromaDB with `all-MiniLM-L6-v2` embeddings (384-dim, runs locally)
- **Sparse:** BM25 index over chunks for exact keyword matches (case numbers, specific names)
- **Fusion:** Reciprocal Rank Fusion (RRF, k=60) combining dense + sparse results
- **Query expansion:** 15 legal synonym mappings (breach → violation/failure to perform, contract → agreement/obligation, etc.) to improve recall
- **Chunking:** Sentence-aware, ~300 words with ~50-word overlap
- **Metadata:** source_doc, page_num, confidence_score

**Why hybrid:** Dense search catches semantic similarity ("liability claim" ≈ "damages request"), but BM25 catches exact case numbers like "PSL-2024-0017" that embeddings might miss. Query expansion bridges legal terminology gaps.

### 3.3 Draft Generator (`core/generator.py`)

**Purpose:** Generate grounded Case Fact Summary with inline citations.

**Interface:**
```python
class DraftGenerator:
    def generate(self, query: str, evidence: List[RetrievedEvidence], correction_rules: List[str] = None) -> CaseFactSummary
```

**Returns:**
- `document_summary`: concise overview of what the document is about
- `parties`: List[Party]
- `key_facts`: List[Fact] (each with `supporting_evidence: [chunk_id]`)
- `dates`: List[DateEvent]
- `claims`: List[Claim]
- `financial_summary`: List[FinancialItem]
- `uncertainties`: List[str] — things flagged as unclear or low-confidence

**Implementation:**
- **Two-stage generation:** Stage 1 analyzes evidence and produces a 3-5 bullet factual outline. Stage 2 uses that outline as context to generate the structured JSON. This produces more coherent, better-grounded outputs than single-shot generation.
- Few-shot prompt with 2-3 examples of good case fact summaries
- **Grounding rule (enforced in prompt):** Every fact MUST cite at least one evidence chunk_id. Hallucination is explicitly forbidden — unsupported facts go in `uncertainties`.
- **Correction rules injection:** Query Feedback Store for relevant rules and inject into system prompt before generation
- **Evidence formatting:** `_format_evidence()` groups passages by source document, assigns confidence labels (HIGH/MEDIUM/LOW) based on RRF score, and truncates long chunks for token efficiency
- **Dynamic token limits:** `max_tokens` scales with evidence length (`min(4096, 500 + len(evidence_text) // 3)`) to avoid truncating long documents
- **Retry logic:** Up to 2 retries on validation failure (invalid JSON, hallucinated citations) with error context accumulated in the prompt
- **LLM:** Groq API (llama-3.3-70b-versatile) for fast, cheap inference
- **Post-generation verification:** `GroundingVerifier.verify()` performs semantic similarity check between facts and evidence. Ungrounded items are moved to `uncertainties`.

### 3.4 Grounding Verifier (`core/grounding.py`)

**Purpose:** Catch hallucinations that citation validation misses.

**Interface:**
```python
class GroundingVerifier:
    def verify(self, draft: CaseFactSummary, evidence: List[RetrievedEvidence]) -> CaseFactSummary
    def get_grounding_scores(self, draft: CaseFactSummary, evidence: List[RetrievedEvidence]) -> dict
```

**Implementation:**
- Computes cosine similarity between each fact statement and its cited evidence chunks
- Threshold: 0.55 — facts below this are considered ungrounded
- Also checks if cited chunks are among the most semantically similar to the fact
- Ungrounded items are moved to `uncertainties` with `[Grounding check]` prefix
- **Per-section grounding scores:** `get_grounding_scores()` returns detailed metrics for each fact, claim, and financial item including max similarity, average cited similarity, best matching chunk, and a boolean `grounded` flag. Overall score is the mean across all sections. Used by the UI to display the grounding strength banner (Strong/Moderate/Weak).

### 3.5 Feedback Engine (`core/feedback.py`)

**Purpose:** Capture operator edits and extract reusable improvement patterns with effectiveness tracking.

**Interface:**
```python
class FeedbackEngine:
    def track_applied_rules(self, rules: List[str]) -> None
    def capture_edit(self, original: dict, edited: dict) -> dict
    def get_rules(self, limit: int = 3, min_confidence: float = 0.3) -> List[str]
    def get_stats(self) -> dict
```

**Implementation:**
- **Diff extraction:** Deep-diff of original vs edited JSON structure via `_deep_diff()`
- **Rule extraction:** 12 heuristic generalizers (e.g., party removal → "only include organizational entities", date format changes → "format dates consistently") + LLM fallback for complex edits via `_llm_generalize()`
- **Rule classification:** `_classify_rule_type()` tags each edit as removal, addition, evidence_fix, correction, or modification
- **Rule validation:** `_is_valid_rule()` filters out overly specific or malformed rules (e.g., rules containing tmp filenames or chunk IDs)
- **Effectiveness scoring:** Tracks which rules were applied before generation. After an edit, `_score_applied_rules()` checks if previously-applied rules would have prevented the edit. Rules get success/failure counters.
- **Confidence filtering:** `get_rules(min_confidence=0.3)` filters by empirical success rate. Rules with ≥2 applications use `success / (success + failure)`. Rules with fewer applications start at 0.3 + frequency × 0.05 (capped at 0.6).
- **Recency decay:** Score multiplier of `max(0.5, 1.0 - days_old / 90)` gives older rules a 90-day half-life, preventing stale rules from dominating.
- **Semantic deduplication:** `_find_similar_rule()` uses Jaccard token similarity (threshold 0.6) to prevent duplicate rules
- **Safe parsing:** `_safe_parse()` handles JSON parse failures gracefully during diff processing
- **Rule storage:** SQLite with frequency counters, success/failure counts, and creation timestamps

### 3.6 Web UI (`static/index.html` + `static/app.js`)

**Purpose:** Split-screen interface for upload, visual verification, review, edit, and feedback.

**Features:**
- Drag-and-drop document upload
- **PDF pages rendered as images** on the left panel for visual source verification
- **Color-coded entity highlighting** in extracted text (dates=blue, amounts=green, parties=orange, case numbers=purple, case citations=red, statutes=teal, courts=lime, judges=brown)
- **Entity legend, badges, and table** showing all extracted structured data
- Auto-generated draft with **clickable inline citations** (click citation → modal preview of chunk)
- **Grounding score banner** showing semantic support strength (Strong/Moderate/Weak)
- **Retrieval method badges** (dense=blue, sparse=orange, hybrid=green) and RRF fusion scores on chunk cards
- **Edit mode:** Toggle between a structured visual form editor (with per-field inputs, add/remove buttons) and a raw JSON textarea. The visual editor syncs bidirectionally with the JSON view.
- **Feedback results** showing new rules learned, changes detected, rule effectiveness percentage, and active rules

**Why HTML/JS:** No build step, fast to develop, evaluators can open `index.html` directly or run via FastAPI static files.

---

## 4. Data Flow

```
Upload (PDF/Image)
    │
    ▼
┌─────────────────┐
│ 1. PROCESS      │──▶ OCR + deskewing + structuring ──▶ raw_text + chunks + entities
│   (processor)   │     Sentence-aware chunking, 8 entity types
└─────────────────┘
    │
    ▼
┌─────────────────┐
│ 2. INDEX        │──▶ Embed chunks ──▶ Store in Chroma + BM25
│   (retriever)   │     (source_doc, page_num, confidence_score)
└─────────────────┘
    │
    ▼ (Auto-triggered after upload)
┌─────────────────┐
│ 3. RETRIEVE     │──▶ Hybrid search + query expansion
│   (retriever)   │     Returns top-5 passages with source attribution
└─────────────────┘
    │
    ▼
┌─────────────────┐
│ 4. GENERATE     │──▶ Two-stage: analyze evidence, generate structured output
│   (generator)   │     Evidence + correction rules → CaseFactSummary
└─────────────────┘
    │
    ▼
┌─────────────────┐
│ 5. VERIFY       │──▶ Semantic grounding check
│   (grounding)   │     Ungrounded facts → uncertainties
└─────────────────┘
    │
    ▼
┌─────────────────┐
│ 6. PRESENT      │──▶ UI shows draft with clickable citations
│   (UI)          │     User edits inline, clicks "Submit Edits"
└─────────────────┘
    │
    ▼
┌─────────────────┐
│ 7. LEARN        │──▶ Diff original vs edited ──▶ Extract rules, score effectiveness
│   (feedback)    │     Store rules, increment frequency/success counters
└─────────────────┘
    │
    ▼
Future generations now include learned correction rules in the prompt
```

**Key Design Decisions:**
- Low-confidence chunks are **kept, not dropped** — the generator knows their confidence and can flag them in `uncertainties`
- Every fact in output **must cite a chunk_id** — enforced by prompt and verified by generator and grounding verifier
- Correction rules are **empirically scored** — rules with low success rates are filtered out before injection
- Sentence-aware chunking ensures each retrieved passage contains **complete thoughts**

---

## 5. Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| Backend | FastAPI, Python 3.11+ | Modern, async, auto-generated API docs, easy to test |
| OCR | `pymupdf` + `pytesseract` + `pdf2image` | Local, no external deps, hybrid strategy with deskewing |
| Embeddings | `sentence-transformers` (all-MiniLM-L6-v2) | 384-dim, fast on CPU, good semantic similarity |
| Vector Store | ChromaDB | Lightweight, persistent option, easy setup |
| Sparse Search | `rank-bm25` | Pure Python BM25, no deps, exact match complement |
| LLM | Groq API (llama-3.3-70b-versatile) | Fast, cheap, no local GPU needed |
| Feedback Store | SQLite | Zero-config, portable, sufficient for demo |
| UI | Vanilla HTML/JS (no framework) | No build step, evaluators can run instantly |
| Testing | `pytest` | Standard Python testing |

---

## 6. Evaluation Plan

### 6.1 Synthetic Test Documents

| Document | Messiness | Content |
|---|---|---|
| `contract_scan_dirty.pdf` | High — scanned, skewed, stains, handwritten notes | Service agreement with liability clauses |
| `pleading_partial.pdf` | Medium — mixed OCR/image pages, inconsistent formatting | Court filing with dates, parties, claims |
| `email_chain_messy.txt` | Low — clean text but threaded, inconsistent headers | Client correspondence chain |
| `complex_litigation.pdf` | Low — clean text | Settlement agreement exercising all 8 entity types: parties, dates, amounts, case number, case citation, statute citation, court, judge |

### 6.2 Metrics

| Stage | Metric | Measurement |
|---|---|---|
| **Document Processing** | OCR Character Accuracy | Levenshtein distance vs ground truth |
| | Structured Field F1 | Precision/recall for dates, parties, amounts, citations |
| | Sentence Preservation | % of chunks with complete sentences |
| **Retrieval** | Precision@K | % of top-K chunks manually labeled relevant |
| | Citation Recall | % of ground-truth facts with supporting evidence |
| **Generation** | Citation Accuracy | % of generated facts with valid chunk citations |
| | Hallucination Rate | % of facts not found in any retrieved chunk |
| | Grounding Score | Average semantic similarity between facts and evidence |
| **Feedback Loop** | Edit Reduction Rate | % reduction in operator edits after N iterations |
| | Rule Effectiveness | % of previously-applied rules that prevent future edits |

### 6.3 Evaluation Script

`evaluation/generate_samples.py` creates synthetic docs and `pytest tests/` runs the full test suite (40 tests).

---

## 7. Tradeoffs and Assumptions

### Tradeoffs

1. **Local OCR vs Cloud OCR (Textract/Document AI)**
   - *Chose:* Local `pytesseract` with deskewing
   - *Why:* No API keys to manage, works offline, evaluators can run instantly
   - *Cost:* Lower accuracy on truly messy handwriting vs cloud alternatives

2. **CPU embeddings vs GPU embeddings**
   - *Chose:* CPU (`all-MiniLM-L6-v2`)
   - *Why:* 22M parameters, 384-dim, < 50ms per chunk on modern CPU
   - *Cost:* Could be slower at very large scale, but sufficient for demo

3. **Few-shot prompting vs fine-tuned model**
   - *Chose:* Few-shot prompting with Groq
   - *Why:* No training data or compute needed, easy to iterate, demonstrates prompt engineering
   - *Cost:* Less consistent than fine-tuning for highly structured outputs

4. **SQLite vs PostgreSQL for feedback store**
   - *Chose:* SQLite
   - *Why:* Zero setup, portable, sufficient for proof-of-concept
   - *Cost:* Not suitable for concurrent multi-user production use

5. **Vanilla HTML/JS vs React/Vue**
   - *Chose:* Vanilla HTML/JS
   - *Why:* No build step, faster to develop, easier for evaluators to run
   - *Cost:* Less polished UI, no component reusability

6. **Sentence-aware chunking vs fixed word chunking**
   - *Chose:* Sentence-aware chunking
   - *Why:* Each chunk contains complete thoughts, improving retrieval relevance and generation coherence
   - *Cost:* Chunk sizes vary more, some chunks may be slightly larger or smaller than target

### Assumptions

1. **Synthetic documents are sufficient** — The assessment explicitly allows mock/synthetic documents. We'll create realistic legal-style docs with known ground truth.

2. **Operator edits are structured** — We assume the operator edits the JSON-structured output, not free-text. This makes diff extraction and rule learning tractable.

3. **Groq API is available** — We assume the evaluator can set a `GROQ_API_KEY` environment variable. If not, the system degrades gracefully with a clear error message.

4. **Single-document focus** — For the 2-day scope, we optimize for single-document ingestion. Multi-document comparison is architecturally supported (Chroma collections) but not the primary demo.

5. **English-language documents** — OCR and NER patterns are tuned for English legal documents.

---

## 8. Directory Structure

```
legal-doc-processor/
├── README.md
├── requirements.txt
├── main.py                      # FastAPI entry point
├── core/
│   ├── __init__.py
│   ├── models.py                # Pydantic models + HTML/Markdown rendering
│   ├── processor.py             # Document OCR + sentence-aware chunking + 8 entity types
│   ├── retrieval.py             # Hybrid dense + sparse retrieval + query expansion
│   ├── generator.py             # Two-stage LLM draft generation + grounding verification
│   ├── feedback.py              # Edit capture + rule extraction + effectiveness scoring
│   └── grounding.py             # Post-generation semantic verification
├── static/
│   ├── index.html               # Split-screen UI with PDF viewer
│   └── app.js                   # Frontend logic with entity highlighting
├── evaluation/
│   ├── generate_samples.py      # Creates synthetic PDFs
│   └── synthetic_docs/          # Generated test files
├── data/
│   ├── chroma_db/               # Vector store persistence
│   ├── feedback.db              # SQLite feedback store
│   └── rendered/                # Rendered page images
└── tests/
    ├── test_processor.py        # 22 tests
    ├── test_retrieval.py        # 3 tests
    ├── test_generator.py        # 3 tests
    ├── test_feedback.py         # 7 tests
    └── test_feedback_improvement.py  # 5 end-to-end tests
```

---

## 9. Rubric Alignment Check

| Rubric Category | Points | Our Coverage |
|---|---|---|
| Document Processing | 25 | Hybrid OCR with deskewing, sentence-aware chunking, 8 entity types, confidence scoring |
| Retrieval and Grounding | 25 | Hybrid search, query expansion, citation tracking, post-generation grounding verification, hallucination control |
| Draft Quality | 10 | Two-stage generation, structured output with document summary + financial summary, grounded facts, uncertainties |
| Improvement from Edits | 25 | Rule extraction with 12 heuristics + LLM fallback, effectiveness scoring, semantic deduplication, confidence filtering |
| Code Quality and Design | 10 | 6 modules, clean interfaces, error handling, 40 tests |
| Documentation and Clarity | 5 | README, architecture doc, assumptions, sample I/O |
| **Total** | **100** | **All categories addressed** |

---

## 10. Completed Implementation

All planned components are implemented and tested:

1. ✅ Document Processor — hybrid OCR, deskewing, sentence-aware chunking, 8 entity types, entity position tracking, PDF page rendering
2. ✅ Evidence Retriever — ChromaDB + BM25 + RRF + query expansion
3. ✅ Draft Generator — two-stage generation, correction rules, JSON enforcement, dynamic token limits, retry logic with error accumulation
4. ✅ Grounding Verifier — semantic similarity check, ungrounded fact filtering, per-section grounding scores for UI display
5. ✅ Feedback Engine — diff capture, 12 heuristic rule extractors, LLM fallback, effectiveness scoring, recency decay, rule classification, semantic deduplication
6. ✅ Web UI — split-screen PDF viewer, entity highlighting, clickable citations, grounding scores, structured visual editor with add/remove entries, bidirectional JSON sync
7. ✅ Tests — 40 tests covering all components and end-to-end feedback improvement
8. ✅ Synthetic Documents — 5 templates including `complex_litigation` exercising all 8 entity types
