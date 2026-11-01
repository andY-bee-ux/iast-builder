"""app/routers/documents.py — soumission de documents par les usagers.

Le texte est extrait à la réception, mais le document reste « pending » :
il n'est vectorisé qu'après approbation (routers/admin.py)."""
import re
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from .. import crowdsourcing, db, extract_text, journal
from ..config import UPLOAD_DIR
from ..internal_auth import require_internal

router = APIRouter(dependencies=[Depends(require_internal)])

ALLOWED_EXT = {".txt", ".md", ".csv", ".json", ".rtf", ".docx", ".pdf"}
MAX_SIZE = 20 * 1024 * 1024  # 20 Mo


@router.post("/documents")
async def upload_document(file: UploadFile = File(...), submittedBy: str = Form(default=""), note: str = Form(default="")):
    if not crowdsourcing.is_active("formulaire"):
        raise HTTPException(403, "Les contributions sont suspendues pour le moment.")
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Format non supporté ({ext}). Formats acceptés : {', '.join(sorted(ALLOWED_EXT))}")
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(400, "Fichier trop volumineux (limite : 20 Mo).")

    safe_name = re.sub(r"[^\w.\-]+", "_", file.filename)
    stored_name = f"{int(time.time() * 1000)}_{safe_name}"
    dest = UPLOAD_DIR / stored_name
    dest.write_bytes(content)
    text, extraction_error = extract_text.extract_text(dest)

    doc_id = db.execute(
        "INSERT INTO documents (filename, stored_as, size_bytes, submitted_by, note, extracted_text, extraction_error, status, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (file.filename, stored_name, len(content), submittedBy.strip()[:120] or None, note.strip()[:500] or None,
         text, extraction_error, "pending", db.now_iso()),
    )
    journal.append("document_soumis", "document", doc_id, "usager", {"filename": file.filename, "chars": len(text)})
    return {
        "message": (
            "Document reçu et texte extrait. Il sera examiné avant d'intégrer la base de connaissances."
            if text else
            "Document reçu, mais son texte n'a pas pu être extrait automatiquement ; il pourra être complété manuellement."
        ),
        "id": doc_id,
        "charactersExtracted": len(text),
    }
