"""app/routers/admin.py — contributions, documents, ontologie active, statistiques.

L'authentification (mot de passe administrateur) est assurée par la gateway ;
ce routeur fait confiance au secret interne et ne la réimplémente pas.

Les routes des trois phases (questions d'investigation, assertions, extraction,
connecteurs, évolution de l'ontologie, journal) sont dans routers/questions.py
et routers/knowledge.py.
"""
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from .. import db, extraction, journal, ontology_evolution, ontology_loader, vectorstore
from ..config import UPLOAD_DIR
from ..internal_auth import require_internal

router = APIRouter(dependencies=[Depends(require_internal)])


class ReviewRequest(BaseModel):
    decision: str  # "approved" | "rejected"
    notes: str | None = None
    editedText: str | None = None
    expert: str | None = None


def _contribution_out(c: dict) -> dict:
    return {
        "id": c["id"], "type": c["type"], "content": c["content"], "submittedBy": c["submitted_by"], "origin": c["origin"],
        "questionId": c["question_id"], "status": c["status"], "createdAt": c["created_at"],
        "reviewedAt": c["reviewed_at"], "reviewedNotes": c["reviewed_notes"],
    }


def _document_out(d: dict, full: bool = False) -> dict:
    out = {
        "id": d["id"], "filename": d["filename"], "storedAs": d["stored_as"], "sizeBytes": d["size_bytes"],
        "submittedBy": d["submitted_by"], "note": d["note"], "extractionError": d["extraction_error"],
        "status": d["status"], "chunksIndexed": d["chunks_indexed"], "createdAt": d["created_at"],
        "reviewedAt": d["reviewed_at"], "reviewedNotes": d["reviewed_notes"],
        "assertionExtraction": d["assertion_extraction"], "assertionExtractionDetail": d["assertion_extraction_detail"],
        "textPreview": (d["extracted_text"] or "")[:240],
    }
    if full:
        out["extractedText"] = d["extracted_text"]
    return out


@router.get("/admin/contributions")
async def list_contributions():
    return [_contribution_out(c) for c in db.fetch_all("SELECT * FROM contributions ORDER BY id")]


@router.get("/admin/documents")
async def list_documents():
    return [_document_out(d) for d in db.fetch_all("SELECT * FROM documents ORDER BY id")]


@router.get("/admin/documents/{doc_id}")
async def get_document(doc_id: int):
    d = db.fetch_one("SELECT * FROM documents WHERE id = ?", (doc_id,))
    if not d:
        raise HTTPException(404, "Document introuvable.")
    return _document_out(d, full=True)


@router.post("/admin/contributions/{contrib_id}/review")
async def review_contribution(contrib_id: int, req: ReviewRequest):
    if req.decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision doit être 'approved' ou 'rejected'.")
    c = db.fetch_one("SELECT * FROM contributions WHERE id = ?", (contrib_id,))
    if not c:
        raise HTTPException(404, "Contribution introuvable.")
    notes = (req.notes or "").strip()[:500] or None
    if req.decision == "approved":
        try:
            vectorstore.add_contribution(c["id"], c["content"], c["type"])
        except vectorstore.EmbeddingUnavailable as exc:
            # Rien n'est marqué approuvé tant que l'indexation n'a pas réussi.
            raise HTTPException(503, str(exc)) from exc
    db.execute("UPDATE contributions SET status = ?, reviewed_at = ?, reviewed_notes = ? WHERE id = ?",
               (req.decision, db.now_iso(), notes, contrib_id))
    journal.append("contribution_decidee", "contribution", contrib_id, req.expert or "administrateur",
                   {"decision": req.decision, "notes": notes})
    return {"ok": True, "entry": _contribution_out(db.fetch_one("SELECT * FROM contributions WHERE id = ?", (contrib_id,)))}


@router.post("/admin/documents/{doc_id}/review")
async def review_document(doc_id: int, req: ReviewRequest):
    if req.decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision doit être 'approved' ou 'rejected'.")
    d = db.fetch_one("SELECT * FROM documents WHERE id = ?", (doc_id,))
    if not d:
        raise HTTPException(404, "Document introuvable.")
    text = req.editedText if (req.editedText and req.editedText.strip()) else d["extracted_text"]
    notes = (req.notes or "").strip()[:500] or None
    chunks = None
    if req.decision == "approved":
        try:
            chunks = vectorstore.add_document(doc_id, d["filename"], text or "")
        except vectorstore.EmbeddingUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
    db.execute(
        "UPDATE documents SET status = ?, reviewed_at = ?, reviewed_notes = ?, extracted_text = ?, chunks_indexed = ? WHERE id = ?",
        (req.decision, db.now_iso(), notes, text, chunks, doc_id),
    )
    journal.append("document_decide", "document", doc_id, req.expert or "administrateur",
                   {"decision": req.decision, "notes": notes, "chunks": chunks})
    return {"ok": True, "entry": _document_out(db.fetch_one("SELECT * FROM documents WHERE id = ?", (doc_id,)))}


@router.post("/admin/documents/{doc_id}/extract")
async def extract_document(doc_id: int, background: BackgroundTasks):
    """Phase 2 : lance l'extraction guidée par l'ontologie sur un document approuvé."""
    d = db.fetch_one("SELECT status, assertion_extraction FROM documents WHERE id = ?", (doc_id,))
    if not d:
        raise HTTPException(404, "Document introuvable.")
    if d["status"] != "approved":
        raise HTTPException(400, "Seul un document approuvé peut faire l'objet d'une extraction.")
    if d["assertion_extraction"] == "running":
        raise HTTPException(409, "Une extraction est déjà en cours pour ce document.")
    background.add_task(extraction.extract_document, doc_id)
    return {"ok": True, "message": "Extraction lancée. Les assertions apparaîtront dans l'onglet Assertions."}


# ---------------------------------------------------------------------------
# Ontologie active (JSON ou OWL)
# ---------------------------------------------------------------------------
@router.get("/admin/ontology")
async def get_ontology():
    try:
        bundle = ontology_loader.load_active()
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"format": bundle.format, "content": bundle.raw_text, "summary": bundle.summary,
            "version": journal.current_ontology_version()}


class OntologyTextUpdate(BaseModel):
    format: str                       # "json" ou "owl"
    content: str
    sourceFormat: str | None = None   # indication pour l'analyse OWL : turtle | xml | n3
    expert: str | None = None


@router.put("/admin/ontology")
async def put_ontology(req: OntologyTextUpdate):
    """Correction ponctuelle depuis l'éditeur du panneau. Crée une nouvelle version."""
    if req.format not in ("json", "owl"):
        raise HTTPException(400, "format doit être 'json' ou 'owl'.")
    backup_name = ontology_loader.backup_active()
    try:
        if req.format == "json":
            ontology_loader.save_json(req.content)
        else:
            ontology_loader.save_owl_text(req.content, hint_format=req.sourceFormat)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    version = ontology_evolution.snapshot("Modification directe depuis l'éditeur du panneau", req.expert or "administrateur")
    return {"ok": True, "backup": backup_name, "version": version}


@router.post("/admin/ontology/upload")
async def upload_ontology(file: UploadFile = File(...)):
    """Import d'une ontologie (JSON ou OWL). Sert à charger l'ontologie initiale du projet."""
    ext = Path(file.filename).suffix.lower()
    allowed = {".json"} | ontology_loader.OWL_UPLOAD_EXTENSIONS
    if ext not in allowed:
        raise HTTPException(400, f"Format non supporté ({ext}). Formats acceptés : {', '.join(sorted(allowed))}")
    content = await file.read()
    tmp_path = UPLOAD_DIR / f"_ontology_upload{ext}"
    tmp_path.write_bytes(content)
    backup_name = ontology_loader.backup_active()
    try:
        if ext == ".json":
            ontology_loader.save_json(content.decode("utf-8"))
        else:
            ontology_loader.save_owl_upload(tmp_path, file.filename)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, f"Fichier d'ontologie invalide : {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — erreur d'analyse rdflib
        raise HTTPException(400, f"Fichier d'ontologie invalide : {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    version = ontology_evolution.snapshot(f"Import du fichier {file.filename}", "administrateur")
    journal.append("ontologie_importee", "ontologie", version, "administrateur", {"filename": file.filename})
    return {"ok": True, "format": ontology_loader.load_active().format, "backup": backup_name, "version": version}


@router.get("/admin/stats")
async def stats():
    def count_by(table: str, column: str = "status") -> dict:
        return {r["k"]: r["n"] for r in db.fetch_all(f"SELECT {column} AS k, COUNT(*) AS n FROM {table} GROUP BY {column}")}

    return {
        "contributions": count_by("contributions"),
        "documents": count_by("documents"),
        "questions": count_by("questions"),
        "assertions": count_by("assertions"),
        "assertionsByVerdict": count_by("assertions", "verdict"),
        "vectorCount": vectorstore.count(),
        "ontologyVersion": journal.current_ontology_version(),
    }
