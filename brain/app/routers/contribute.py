"""app/routers/contribute.py — contributions explicites des usagers (formulaire)."""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from .. import db, journal
from ..internal_auth import require_internal
from ..profile import active as active_profile
from .. import crowdsourcing

router = APIRouter(dependencies=[Depends(require_internal)])


class ContributeRequest(BaseModel):
    type: str = "autre"
    content: str = Field(min_length=5)
    submittedBy: str | None = None


@router.post("/contribute")
async def contribute(req: ContributeRequest):
    if not crowdsourcing.is_active("formulaire"):
        raise HTTPException(403, "Les contributions sont suspendues pour le moment.")
    allowed = set(active_profile().contribution_types)   # types déclarés par le profil de domaine
    safe_type = req.type if req.type in allowed else "autre"
    cid = db.execute(
        "INSERT INTO contributions (type, content, submitted_by, origin, status, created_at) VALUES (?,?,?,?,?,?)",
        (safe_type, req.content.strip(), (req.submittedBy or "").strip()[:120] or None, "usager", "pending", db.now_iso()),
    )
    journal.append("contribution_proposee", "contribution", cid, "usager", {"type": safe_type})
    return {
        "message": (
            "Merci. Votre contribution a été enregistrée comme proposition et sera examinée par les experts du "
            "projet avant d'être considérée comme une information fiable."
        ),
        "id": cid,
    }
