"""app/routers/chat.py — conversation avec l'agent.

Déroulement d'une question :
1. prompt_builder construit le dossier de réponse et le prompt système ;
2. le LLM répond, en tête de réponse les balises EMOTION et SIGNAL, puis un texte
   dont chaque phrase factuelle porte ses renvois au dossier ;
3. response_parser lit les balises ; restitution vérifie et retire les renvois ;
4. un signal éventuel devient une question d'investigation (investigations.py).

Réponse JSON : {text, emotion, sources:[{id,label}], signal:{type, questionId}|null,
memoryQueued (compatibilité avec l'interface précédente)}.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import anthropic_client, crowdsourcing, investigations, journal, prompt_builder, response_parser, restitution, vectorstore
from ..internal_auth import require_internal

router = APIRouter(dependencies=[Depends(require_internal)])


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    lang: str = "fr"
    persona: str = "sage"
    clientId: str | None = None   # identifiant aléatoire du navigateur, pour compter les usagers distincts


@router.post("/chat")
async def chat(req: ChatRequest):
    if not req.messages:
        raise HTTPException(400, "Le champ 'messages' est requis (liste non vide).")

    last_user = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
    # Messages précédents, du plus récent au plus ancien (hors question en cours).
    context = [m.content for m in reversed(req.messages[-7:-1])]
    try:
        system, dossier = prompt_builder.build_system_prompt(req.lang, req.persona, last_user, context)
    except vectorstore.EmbeddingUnavailable:
        # Dégradation maîtrisée : réponse fondée sur l'ontologie et les assertions
        # validées, sans recherche documentaire.
        system, dossier = prompt_builder.build_system_prompt(req.lang, req.persona, "", context)

    try:
        raw = await anthropic_client.messages(system, [m.model_dump() for m in req.messages])
    except anthropic_client.AnthropicError as exc:
        raise HTTPException(502, str(exc)) from exc

    parsed = response_parser.parse(raw)
    result = restitution.apply_citations(parsed.text, dossier)
    restitution.log_anomalies(result)
    # Contrôle de sûreté du profil (par exemple : aucune posologie dans une pharmacopée).
    safety = restitution.apply_safety(result.text)
    if safety.removed:
        journal.append("controle_surete", "conversation", None, "systeme",
                       {"contraintes": safety.removed, "phrases_retirees": safety.sentences, "reponse_videe": safety.emptied})

    signal_out = None
    if parsed.signal and not crowdsourcing.signal_transmitted(parsed.signal["type"]):
        # Mode de collecte désactivé : le signal n'est pas transmis ; seul son type est journalisé,
        # sans rien des propos de l'usager.
        journal.append("signal_non_transmis", "conversation", None, "systeme", {"type": parsed.signal["type"]})
    elif parsed.signal:
        q = investigations.record_signal(
            parsed.signal["type"], parsed.signal["question"], parsed.signal.get("hypothesis"),
            "; ".join(s["label"] for s in result.sources) or "aucune source du dossier mobilisée",
            last_user, req.clientId,
        )
        signal_out = {"type": parsed.signal["type"], "questionId": q["id"], "nouvelle": q.get("nouvelle", True)}

    return {
        "text": restitution.plain_text(safety.text),
        "emotion": parsed.emotion,
        "sources": result.sources,
        "signal": signal_out,
        "memoryQueued": bool(signal_out and signal_out["type"] == "nouveaute"),
    }
