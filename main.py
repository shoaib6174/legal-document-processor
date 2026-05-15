import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from core.feedback import FeedbackEngine
from core.generator import DraftGenerator
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
        doc = processor.process(tmp_path)
        retriever.clear()
        retriever.index(doc.chunks)

        global _last_doc_id
        _last_doc_id = file.filename

        return {
            "filename": file.filename,
            "chunks": len(doc.chunks),
            "entities": [{"type": e.type, "value": e.value} for e in doc.entities],
            "raw_text": doc.raw_text[:2000] + "..." if len(doc.raw_text) > 2000 else doc.raw_text,
        }
    finally:
        tmp_path.unlink(missing_ok=True)


@app.post("/generate")
async def generate_draft(query: str = Form("Generate a case fact summary")):
    """Generate a grounded draft from the uploaded document."""
    evidence = retriever.retrieve(query, top_k=5)
    rules = feedback_engine.get_rules(limit=3)
    draft = _get_generator().generate(query, evidence, correction_rules=rules)

    global _last_draft
    _last_draft = draft.model_dump()

    return {
        "draft": draft.model_dump(),
        "evidence": [e.model_dump() for e in evidence],
        "rules_applied": rules,
    }


@app.post("/feedback")
async def submit_feedback(edited_draft: str = Form(...)):
    """Submit operator edits to improve future drafts."""
    edited = json.loads(edited_draft)
    original = _last_draft

    if not original:
        return {"status": "error", "message": "No draft to compare against"}

    feedback_engine.capture_edit(original, edited)
    new_rules = feedback_engine.get_rules(limit=3)

    return {
        "status": "success",
        "rules_learned": len(new_rules),
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
