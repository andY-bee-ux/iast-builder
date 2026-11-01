"""app/routers/profile.py — description publique du profil de domaine actif.

L'interface de conversation s'en sert pour adapter ses textes (titre, accroche, suggestions,
langues, outils propres au domaine) sans modification de code."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import audit, crowdsourcing, prompt_builder
from ..internal_auth import require_internal
from ..profile import active as active_profile

router = APIRouter(dependencies=[Depends(require_internal)])


@router.get("/profile")
async def profile():
    p = active_profile()
    return {
        "id": p.id,
        "nom": p.raw.get("nom"),
        "agent": p.agent.get("nom"),
        "description": p.raw.get("description"),
        "interface": p.interface,
        "contributions": p.raw.get("contributions", {}).get("types", []),
        "glossaire": p.glossary.get("langue") if p.glossary else None,
        "risque": p.safety.get("risque", "faible"),
        "collecte": crowdsourcing.state(),
        "personnalites": [{"id": k, "label": v.get("label", k), "label_en": v.get("label_en", v.get("label", k))} for k, v in prompt_builder.personas().items()],
        "personnalite_par_defaut": prompt_builder.default_persona(),
    }


class CollecteIn(BaseModel):
    mode: str            # temoignages | formulaire | lacunes
    actif: bool
    expert: str
    motif: str | None = None


@router.get("/admin/collecte")
async def get_collecte():
    """Réglages de la collecte communautaire : valeur en vigueur et valeur déclarée par le profil."""
    return {"etat": crowdsourcing.state(), "defauts": crowdsourcing.defaults(), "libelles": crowdsourcing.LABELS}


@router.put("/admin/collecte")
async def put_collecte(req: CollecteIn):
    try:
        return {"etat": crowdsourcing.set_mode(req.mode, req.actif, req.expert, req.motif)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/admin/audit")
async def run_audit():
    """Audit de l'état du système au regard des invariants d'exécution du métamodèle."""
    return audit.run()
