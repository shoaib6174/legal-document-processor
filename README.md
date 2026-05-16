# Legal Document Processor

A pipeline for ingesting messy legal documents, extracting structured information, retrieving grounded evidence, and generating draft case fact summaries that improve from operator feedback.

Built for the Pearson Specter Litt AI Engineer take-home assessment.

![Technical Architecture](docs/screenshots/architecture-cover.png)

## What It Does

1. **Process** — Extracts text from PDFs and images using hybrid OCR (native text extraction + Tesseract fallback for scanned pages). Sentence-aware chunking ensures no sentence is split across chunks. Extracts entities (dates, amounts, parties, case numbers, case citations, statute citations, court names, judge names) and scores each chunk for OCR confidence.

2. **Index** — Embeds chunks using sentence-transformers and stores them in ChromaDB with BM25 sparse indexing. Metadata includes source document, page number, and OCR confidence.

3. **Retrieve** — Uses hybrid search (dense embeddings via ChromaDB + sparse BM25 + Reciprocal Rank Fusion) with legal query expansion to find the most relevant evidence passages. Every retrieved passage carries a `chunk_id` so its source can be traced.

4. **Generate** — Two-stage generation: first analyzes evidence, then produces a structured `CaseFactSummary` JSON with parties, dates, claims, key facts, document summary, financial summary, and uncertainties.

5. **Verify** — Post-generation semantic grounding check compares each fact against its cited evidence. Facts below the similarity threshold are moved to `uncertainties` with a `[Grounding check]` prefix.

6. **Learn** — Captures operator edits via a diff engine, extracts reusable correction rules with 12 heuristic generalizers + LLM fallback, scores rule effectiveness, and injects the best rules into future generation prompts.

## Prerequisites

- Python 3.11+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed on your system
  - macOS: `brew install tesseract`
  - Ubuntu: `sudo apt-get install tesseract-ocr`
- A [Groq](https://groq.com/) API key (free tier available)

## Setup

1. **Clone and enter the repository:**
   ```bash
   git clone https://github.com/shoaib6174/legal-document-processor.git
   cd legal-document-processor
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   # macOS/Linux:
   source .venv/bin/activate
   # Windows:
   # .venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Set your Groq API key:**
   ```bash
   export GROQ_API_KEY="your_key_here"
   # Or create a .env file (loaded automatically by the app):
   echo "GROQ_API_KEY=your_key_here" > .env
   ```

5. **Verify everything works:**
   ```bash
   pytest tests/ -v
   ```
   Expected: 40 tests pass with no external API calls.

## Running the Application

### Start the server

```bash
python main.py
```

The FastAPI server starts on `http://localhost:8000`.

### Use the web UI

Open `http://localhost:8000` in a browser. The UI supports:

- Drag-and-drop or click-to-select file upload (PDF, PNG, JPG)
- Side-by-side PDF viewer with rendered page images
- Color-coded entity highlighting in extracted text
- Auto-generated Case Fact Summary with clickable citations
- Grounding score banner showing semantic support strength
- Structured visual editor with JSON toggle for reviewing and editing drafts
- Submitting edits to train the system's correction rules
- Retrieval method badges (dense, sparse, hybrid) and RRF fusion scores

### API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Serve the web UI |
| `/upload` | POST | Upload a document (`file: UploadFile`) |
| `/generate` | POST | Generate a draft (`query: str = "Generate a case fact summary"`) |
| `/feedback` | POST | Submit edited draft (`edited_draft: str`) |
| `/rendered/{doc_id}/{page_file}` | GET | Serve rendered page PNG |

Example with `curl`:

```bash
# Upload a document
curl -X POST -F "file=@evaluation/synthetic_docs/contract_clean.pdf" \
  http://localhost:8000/upload

# Generate a draft
curl -X POST -F "query=Generate a case fact summary" \
  http://localhost:8000/generate

# Submit feedback (edit the JSON first)
curl -X POST -F 'edited_draft={"parties": [...]}' \
  http://localhost:8000/feedback
```

## Running Tests

All tests use synthetic data and mocked external calls (no real LLM calls in unit tests).

```bash
# Run the full test suite
pytest tests/ -v

# Run a specific module
pytest tests/test_processor.py -v
pytest tests/test_retrieval.py -v
pytest tests/test_generator.py -v
pytest tests/test_feedback.py -v
pytest tests/test_feedback_improvement.py -v
```

Expected output: 40 tests pass.

### Generate synthetic test documents

```bash
python evaluation/generate_samples.py
```

Creates clean-text and scanned/image PDFs in `evaluation/synthetic_docs/` for manual end-to-end testing.

## Project Structure

```
.
├── main.py                       # FastAPI app with /upload, /generate, /feedback, /rendered
├── requirements.txt              # Python dependencies
├── core/
│   ├── __init__.py
│   ├── models.py                 # Pydantic data models
│   ├── processor.py              # DocumentProcessor (OCR, sentence-aware chunking, entity extraction, deskewing)
│   ├── retrieval.py              # EvidenceRetriever (ChromaDB + BM25 + RRF + query expansion)
│   ├── generator.py              # DraftGenerator (two-stage Groq LLM client)
│   ├── feedback.py               # FeedbackEngine (SQLite + rule extraction + effectiveness scoring)
│   └── grounding.py              # GroundingVerifier (post-generation semantic verification)
├── tests/
│   ├── __init__.py
│   ├── test_processor.py         # 22 tests for chunking, entities, OCR
│   ├── test_retrieval.py         # 3 tests for hybrid search
│   ├── test_generator.py         # 3 tests for prompt assembly and JSON parsing
│   ├── test_feedback.py          # 7 tests for diff capture and rule ranking
│   └── test_feedback_improvement.py  # 5 end-to-end tests for feedback loop
├── evaluation/
│   ├── generate_samples.py       # Creates synthetic PDFs
│   ├── document_templates.py     # Text templates for synthetic document generation
│   ├── evaluate.py               # Evaluation script and rubric scoring
│   └── synthetic_docs/           # Generated test files
├── static/
│   ├── index.html                # Web UI with split-screen PDF viewer
│   └── app.js                    # Frontend logic with entity highlighting
├── docs/
│   ├── architecture-cover.html   # Single-page technical architecture diagram
│   ├── EDIT_SESSION.md           # Feedback loop walkthrough
│   ├── RUBRIC_EVALUATION.md      # Self-assessment against rubric
│   └── SUBMISSION.md             # Submission notes
├── ARCHITECTURE.md               # Full system design with tradeoffs
├── ASSESSMENT.md                 # Original take-home requirements and rubric
└── README.md                     # This file
```

## Screenshot Gallery

| Initial Upload | After Processing | Full Pipeline | Edit Panel |
|---|---|---|---|
| ![Initial](docs/screenshots/ui_initial.png) | ![After Upload](docs/screenshots/ui_after_upload.png) | ![Full](docs/screenshots/ui_full.png) | ![Edit Panel](docs/screenshots/ui_edit_panel.png) |

## Edit Session Demo

The feedback loop is the system's learning engine. Here is a concrete walkthrough of how operator edits become reusable correction rules:

**Document:** `complex_litigation_clean.pdf` — Stipulation and Settlement Agreement

**Issues in initial draft:**
- Missing plaintiff (Alexander Mercer)
- Missing settlement amounts ($3.25M, $875K)
- Missing court opinion date (June 3, 2024)
- Missing claims (breach of contract, fraudulent misrepresentation)

**Operator edits** the JSON inline in the web UI, then submits.

**System response:**
```json
{
  "status": "success",
  "rules_learned": 3,
  "total_diffs": 5,
  "active_rules": [
    "Do not include facts without supporting evidence citations...",
    "Do not generate content without strong supporting evidence...",
    "Verify that every fact and claim cites evidence chunks that actually support the stated content..."
  ]
}
```

These rules are stored in SQLite with frequency counters and effectiveness scores. On the next document generation, the top 3 rules by confidence are injected into the LLM system prompt as **CORRECTION RULES**, reducing the likelihood of the same errors.

See the full walkthrough in [`docs/EDIT_SESSION.md`](docs/EDIT_SESSION.md).

## Architecture Overview

![Technical Architecture](docs/screenshots/architecture-cover.png)

The system follows a 6-stage pipeline: **Process** → **Index** → **Retrieve** → **Generate** → **Verify** → **Learn**. Each stage is implemented as a dedicated module in `core/` with clear responsibilities and data contracts.

See `ARCHITECTURE.md` for detailed tradeoffs, assumptions, and rubric alignment.

## Key Design Decisions

- **Hybrid OCR** — Native `pymupdf` text extraction is fast and accurate for clean PDFs. `pytesseract` + image preprocessing (deskew, contrast boost, denoise) is used as a fallback for scanned pages. Per-chunk confidence scoring lets the generator know which text is trustworthy.

- **Sentence-Aware Chunking** — Text is split into sentences first, then grouped into ~300-word chunks. Sentences are never split across chunks, ensuring each retrieved passage contains complete thoughts.

- **Hybrid Retrieval** — Dense embeddings (ChromaDB + `all-MiniLM-L6-v2`) catch semantic similarity. BM25 catches exact matches on case numbers and citations. RRF merges the two without requiring score calibration. Legal query expansion adds synonyms for 15 common legal terms (breach → violation/failure to perform, etc.).

- **Two-Stage Generation** — Stage 1 analyzes evidence and produces a factual outline. Stage 2 uses that outline as context to generate the structured `CaseFactSummary`. This produces more coherent, better-grounded outputs than single-shot generation.

- **Post-Generation Grounding Verification** — After the LLM produces output, a semantic similarity check verifies that each fact is supported by its cited evidence. Facts below a similarity threshold are moved to `uncertainties` with a `[Grounding check]` prefix.

- **Feedback Loop with Effectiveness Scoring** — Rules are not just extracted but also scored. When an operator edits a draft, the system checks which previously-applied rules would have prevented the edit. Rules with low empirical success rates are filtered out before injection.

## Tech Stack

- **Backend:** FastAPI, Python 3.11+
- **OCR:** `pymupdf` (native text) + `pytesseract` (scan fallback with deskewing)
- **Embeddings:** `sentence-transformers` (`all-MiniLM-L6-v2`, 384-dim, CPU)
- **Vector Store:** ChromaDB (persistent, `./data/chroma_db`)
- **Sparse Search:** `rank-bm25`
- **LLM:** Groq API (`llama-3.3-70b-versatile`)
- **Feedback Store:** SQLite (`./data/feedback.db`)
- **UI:** Vanilla HTML/JS served by FastAPI static files
