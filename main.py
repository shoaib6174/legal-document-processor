import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from core.feedback import FeedbackEngine
from core.generator import DraftGenerator
from core.grounding import GroundingVerifier
from core.processor import DocumentProcessor
from core.retrieval import EvidenceRetriever

app = FastAPI(title="Legal Document Processor")

processor = DocumentProcessor()
retriever = EvidenceRetriever()
feedback_engine = FeedbackEngine()

_generator: DraftGenerator | None = None
_last_draft: dict = {}
_last_doc_id: str | None = None


def _get_generator() -> DraftGenerator:
    global _generator
    if _generator is None:
        _generator = DraftGenerator()
    return _generator


@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload and process a document."""
    suffix = Path(file.filename).suffix
    with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        doc = processor.process(tmp_path, source_doc=file.filename)
        retriever.clear()
        retriever.index(doc.chunks)

        # Render PDF pages to images
        rendered_dir = Path("./data/rendered") / file.filename
        page_files = processor.render_pages(tmp_path, rendered_dir)

        global _last_doc_id
        _last_doc_id = file.filename

        return {
            "filename": file.filename,
            "chunks": len(doc.chunks),
            "chunk_data": [
                {
                    "chunk_id": c.chunk_id,
                    "text": c.text,
                    "page_num": c.page_num,
                    "confidence_score": c.confidence_score,
                }
                for c in doc.chunks
            ],
            "entities": [
                {"type": e.type, "value": e.value, "start": e.start, "end": e.end}
                for e in doc.entities
            ],
            "pages": len(page_files),
            "raw_text": doc.raw_text,
        }
    finally:
        tmp_path.unlink(missing_ok=True)


@app.get("/rendered/{doc_id}/{page_file}")
async def get_rendered_page(doc_id: str, page_file: str):
    """Serve a rendered page image."""
    img_path = Path("./data/rendered") / doc_id / page_file
    if img_path.exists():
        return FileResponse(img_path)
    return {"error": "Not found"}


@app.post("/generate")
async def generate_draft(query: str = Form("Generate a case fact summary")):
    """Generate a grounded draft from the uploaded document."""
    evidence = retriever.retrieve(query, top_k=5)
    rules = feedback_engine.get_rules(limit=3)

    # Track which rules are about to be applied (for later effectiveness scoring)
    feedback_engine.track_applied_rules(rules)

    draft = _get_generator().generate(query, evidence, correction_rules=rules)

    # Compute grounding scores for display
    verifier = GroundingVerifier()
    grounding = verifier.get_grounding_scores(draft, evidence)

    global _last_draft
    _last_draft = draft.model_dump()

    return {
        "draft": draft.model_dump(),
        "draft_html": draft.to_html(),
        "draft_markdown": draft.to_markdown(),
        "evidence": [e.model_dump() for e in evidence],
        "rules_applied": rules,
        "grounding": grounding,
    }


@app.post("/feedback")
async def submit_feedback(edited_draft: str = Form(...)):
    """Submit operator edits to improve future drafts."""
    edited = json.loads(edited_draft)
    original = _last_draft

    if not original:
        return {"status": "error", "message": "No draft to compare against"}

    result = feedback_engine.capture_edit(original, edited)
    stats = feedback_engine.get_stats()
    new_rules = feedback_engine.get_rules(limit=3)

    return {
        "status": "success",
        "rules_learned": result["new_rules_learned"],
        "total_diffs": result["total_diffs"],
        "rules_scored": result["rules_scored"],
        "effectiveness_pct": stats["effectiveness_pct"],
        "active_rules": new_rules,
    }


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serve the main UI."""
    html_path = Path(__file__).parent / "static" / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    return HTMLResponse(content="<h1>Legal Document Processor</h1><p>UI not built yet.</p>")


app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
