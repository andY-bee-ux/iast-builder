"""app/routers/questions.py — questions d'investigation (phase 1), vues par les experts."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import anthropic_client, investigations
from ..internal_auth import require_internal

router = APIRouter(dependencies=[Depends(require_internal)])


@router.get("/admin/questions")
async def list_questions(status: str | None = "open"):
    return investigations.list_questions(None if status == "all" else status)


@router.get("/admin/questions/{qid}")
async def get_question(qid: int):
    q = investigations.get(qid)
    if not q:
        raise HTTPException(404, "Question introuvable.")
    return q


class FormalizeRequest(BaseModel):
    answer: str


@router.post("/admin/questions/{qid}/formalize")
async def formalize(qid: int, req: FormalizeRequest):
    """L'expert rédige sa réponse en français ; le système propose les assertions
    correspondantes, avec leur paraphrase et leur verdict. Rien n'est enregistré."""
    try:
        return await investigations.formalize_answer(qid, req.answer)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except anthropic_client.AnthropicError as exc:
        raise HTTPException(502, str(exc)) from exc


class DecisionRequest(BaseModel):
    outcome: str                       # validated | rejected | complement | deliberation
    expert: str
    notes: str | None = None
    assertions: list[dict] | None = None
    confirmTension: bool = False


@router.post("/admin/questions/{qid}/decide")
async def decide(qid: int, req: DecisionRequest):
    try:
        return investigations.decide(qid, req.outcome, req.expert.strip() or "expert", req.notes, req.assertions,
                                     req.confirmTension)
    except investigations.TensionError as exc:
        # 409 : l'expert doit confirmer en connaissance de cause.
        return JSONResponse(status_code=409, content={"error": "tension", "tensions": exc.details})
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class OpinionRequest(BaseModel):
    expert: str
    position: str       # pour | contre | reserve
    argument: str | None = None


@router.post("/admin/questions/{qid}/opinions")
async def add_opinion(qid: int, req: OpinionRequest):
    try:
        return investigations.add_opinion(qid, req.expert.strip() or "expert", req.position, req.argument)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
