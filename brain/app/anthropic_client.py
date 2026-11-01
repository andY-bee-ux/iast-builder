"""app/anthropic_client.py — appels à l'API de génération (Anthropic).

Deux fonctions :
- messages()      : conversation ordinaire, renvoie le texte de la réponse ;
- complete_json() : tâche structurée (extraction, formalisation), renvoie un objet
                    JSON décodé. Le modèle reçoit la consigne de ne produire que du
                    JSON ; les éventuelles clôtures ```json sont retirées avant décodage.

Toute erreur de l'API est convertie en AnthropicError, avec le code HTTP et le
message renvoyé par l'API, puis consignée dans le journal de l'application
(logger « yobakoko.llm ») : le détail d'un échec (clé refusée, espace de travail
non précisé, crédit épuisé, modèle introuvable) est ainsi visible dans
logs/brain.log sans script de diagnostic.
"""
from __future__ import annotations

import json
import logging
import re

import httpx

from .config import LLM_TEMPERATURE, ANTHROPIC_API_KEY, ANTHROPIC_MODEL

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
log = logging.getLogger("yobakoko.llm")


class AnthropicError(Exception):
    pass


async def messages(system: str, messages: list[dict], max_tokens: int = 1200) -> str:
    if not ANTHROPIC_API_KEY:
        raise AnthropicError("ANTHROPIC_API_KEY n'est pas configurée côté service brain (fichier brain/.env).")
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            ANTHROPIC_URL,
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            json={"model": ANTHROPIC_MODEL, "max_tokens": max_tokens, "system": system, "messages": messages,
                  "temperature": LLM_TEMPERATURE},
        )
    if resp.status_code != 200:
        log.error("Échec de l'appel à l'API Anthropic (%s) : %s", resp.status_code, resp.text[:1000])
        raise AnthropicError(f"Anthropic API error {resp.status_code}: {resp.text}")
    data = resp.json()
    blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(blocks).strip()


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_text(text: str):
    """Décode un JSON produit par le modèle, en tolérant les clôtures Markdown
    et un éventuel texte avant le premier '{' ou '['."""
    cleaned = _FENCE.sub("", text).strip()
    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0]
    if starts:
        cleaned = cleaned[min(starts):]
    return json.loads(cleaned)


async def complete_json(system: str, user: str, max_tokens: int = 2500):
    """Tâche structurée : renvoie l'objet JSON produit par le modèle.
    Lève AnthropicError si la réponse n'est pas du JSON valide."""
    raw = await messages(system + "\n\nRéponds UNIQUEMENT par du JSON valide, sans texte autour.", [{"role": "user", "content": user}], max_tokens)
    try:
        return parse_json_text(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        log.error("Réponse non JSON du modèle : %s", raw[:500])
        raise AnthropicError(f"Réponse du modèle non conforme au format JSON attendu : {exc}") from exc
