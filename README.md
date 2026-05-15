# Legal Document Processor

A pipeline for ingesting messy legal documents, extracting structured information, retrieving grounded evidence, and generating draft case fact summaries that improve from operator feedback.

Built for the Pearson Specter Litt AI Engineer take-home assessment.

## What It Does

1. **Process** — Extracts text from PDFs and images using hybrid OCR (native text extraction + Tesseract fallback for scanned pages). Chunks text into ~300-word passages with overlap, extracts entities (dates, amounts, parties, case numbers), and scores each chunk for OCR confidence.

2. **Retrieve** — Uses hybrid search (dense embeddings via ChromaDB + sparse BM25 + Reciprocal Rank Fusion) to find the most relevant evidence passages for a given query. Every retrieved passage carries a `chunk_id` so its source can be traced.

3. **Generate** — Feeds retrieved evidence into a Groq LLM (Llama 3.3 70B) with a structured system prompt. The model produces a `CaseFactSummary` JSON with parties, dates, claims, key facts, and uncertainties. Every fact cites its supporting evidence chunks; unsupported facts land in `uncertainties`.

4. **Learn** — Captures operator edits via a diff engine, extracts reusable correction rules, and injects the top rules into future generation prompts.

## Prerequisites

- Python 3.11+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed on your system
  - macOS: `brew install tesseract`
  - Ubuntu: `sudo apt-get install tesseract-ocr`
- A [Groq](https://groq.com/) API key (free tier available)

## Setup

1. **Clone and enter the repository:**
   ```bash
   cd legal-doc-processor
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set your Groq API key:**
   ```bash
   echo 'GROQ_API_KEY="your_key_here"' > .env
   ```

## Running the Application

### Start the server

```bash
python main.py
```

The FastAPI server starts on `http://localhost:8000`.

### Use the web UI

Open `http://localhost:8000` in a browser. The UI supports:

- Drag-and-drop or click-to-select file upload (PDF, PNG, JPG)
- One-click generation of a Case Fact Summary
- Inline JSON editor for reviewing and editing drafts
- Submitting edits to train the system's correction rules

### API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Serve the web UI |
| `/upload` | POST | Upload a document (`file: UploadFile`) |
| `/generate` | POST | Generate a draft (`query: str = "Generate a case fact summary"`) |
| `/feedback` | POST | Submit edited draft (`edited_draft: str`) |

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
```

Expected output: 21 tests pass.

### Generate synthetic test documents

```bash
python evaluation/generate_samples.py
```

Creates clean-text and scanned/image PDFs in `evaluation/synthetic_docs/` for manual end-to-end testing.

## Project Structure

```
.
├── main.py                  # FastAPI app with /upload, /generate, /feedback
├── requirements.txt         # Python dependencies
├── core/
│   ├── models.py            # Pydantic data models
│   ├── processor.py         # DocumentProcessor (OCR, chunking, entities)
│   ├── retrieval.py         # EvidenceRetriever (ChromaDB + BM25 + RRF)
│   ├── generator.py         # DraftGenerator (Groq LLM client)
│   └── feedback.py          # FeedbackEngine (SQLite + rule extraction)
├── tests/
│   ├── test_processor.py    # 13 tests for chunking, entities, OCR
│   ├── test_retrieval.py    # 3 tests for hybrid search
│   ├── test_generator.py    # 3 tests for prompt assembly and JSON parsing
│   └── test_feedback.py     # 5 tests for diff capture and rule ranking
├── evaluation/
│   ├── generate_samples.py  # Creates synthetic PDFs
│   └── synthetic_docs/      # Generated test files
├── static/
│   ├── index.html           # Minimal web UI
│   └── app.js               # Frontend logic
├── ARCHITECTURE.md          # Full system design with tradeoffs
└── README.md                # This file
```

## Architecture Overview

The system follows a 5-stage pipeline:

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

See `ARCHITECTURE.md` for detailed tradeoffs, assumptions, and rubric alignment.

## Key Design Decisions

- **Hybrid OCR** — Native `pymupdf` text extraction is fast and accurate for clean PDFs. `pytesseract` + `pdf2image` is used as a fallback for scanned pages. Per-chunk confidence scoring lets the generator know which text is trustworthy.

- **Hybrid Retrieval** — Dense embeddings (ChromaDB + `all-MiniLM-L6-v2`) catch semantic similarity (e.g., "liability claim" ≈ "damages request"). BM25 catches exact matches on case numbers like `PSL-2024-0017` that embeddings might miss. RRF merges the two without requiring score calibration.

- **Grounded Generation** — The system prompt explicitly instructs the LLM to cite `chunk_id` for every fact and place unsupported claims in `uncertainties`. The output schema is enforced via `response_format={"type": "json_object"}`.

- **Feedback Loop** — Operator edits are diffed recursively. Changed field paths + original → edited values become frequency-weighted rules. The top-3 most frequent rules are injected into the system prompt before the next generation.

## Sample Input / Output

### Input

A scanned or native-text PDF legal document, e.g.:
- `evaluation/synthetic_docs/contract_clean.pdf` — a service agreement with parties, dates, amounts, and liability clauses
- `evaluation/synthetic_docs/pleading_scanned.pdf` — a scanned complaint document

### Output

A structured `CaseFactSummary` JSON:

```json
{
  "parties": [
    {"name": "ACME INDUSTRIES LLC", "role": "provider"},
    {"name": "SMITH VENTURES INC.", "role": "client"}
  ],
  "dates": [
    {"date": "March 15, 2024", "event": "Service Agreement entered into"},
    {"date": "April 1, 2024", "event": "Term commences"},
    {"date": "March 31, 2025", "event": "Term ends"}
  ],
  "claims": [
    {
      "description": "Provider's liability is limited to the amount paid by Client",
      "supporting_evidence": ["contract_clean.pdf_p1_c0"]
    }
  ],
  "key_facts": [
    {
      "statement": "The total fee for consulting services is $125,000.",
      "supporting_evidence": ["contract_clean.pdf_p1_c0"]
    }
  ],
  "uncertainties": []
}
```

## Tech Stack

- **Backend:** FastAPI, Python 3.11+
- **OCR:** `pymupdf` (native text) + `pytesseract` + `pdf2image` (scan fallback)
- **Embeddings:** `sentence-transformers` (`all-MiniLM-L6-v2`, 384-dim, CPU)
- **Vector Store:** ChromaDB (persistent, `./data/chroma_db`)
- **Sparse Search:** `rank-bm25`
- **LLM:** Groq API (`llama-3.3-70b-versatile`)
- **Feedback Store:** SQLite (`./data/feedback.db`)
- **UI:** Vanilla HTML/JS served by FastAPI static files
