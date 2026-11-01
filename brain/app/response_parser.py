"""app/response_parser.py — lecture des balises placées par le modèle en tête de réponse.

Protocole (un seul appel au modèle par question) :

    [EMOTION:pensif]
    [SIGNAL:contradiction|<question formulée pour les experts>|<hypothèse ou none>]
    <texte de la réponse, avec renvois [[...]] traités par restitution.py>

- EMOTION : neutre | joyeux | pensif | solennel ; pilote l'avatar.
- SIGNAL  : none, ou type|question|hypothèse, avec type parmi
            lacune | contradiction | nouveaute | ambiguite (voir investigations.py).
- MEMORY  : balise de la version précédente, toujours acceptée ; [MEMORY:résumé]
            est traitée comme un signal « nouveaute » dont l'hypothèse est le résumé.

Si le modèle omet le format, la réponse est affichée telle quelle avec l'émotion
« neutre » et aucun signal : la disponibilité de la conversation prime.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

EMOTIONS = {"neutre", "joyeux", "pensif", "solennel"}
TAG_LINE = re.compile(r"^\s*\[(EMOTION|SIGNAL|MEMORY):([^\]\n]*)\]\s*$", re.IGNORECASE)


@dataclass
class ParsedResponse:
    text: str
    emotion: str
    signal: dict | None     # {"type", "question", "hypothesis"}


def _signal_from(value: str) -> dict | None:
    value = value.strip()
    if not value or value.lower() == "none":
        return None
    parts = [p.strip() for p in value.split("|")]
    stype = parts[0].lower().replace("é", "e").replace("ï", "i")
    if stype not in {"lacune", "contradiction", "nouveaute", "ambiguite"} or len(parts) < 2 or not parts[1]:
        return None
    hypothesis = parts[2] if len(parts) > 2 and parts[2].lower() != "none" else None
    return {"type": stype, "question": parts[1], "hypothesis": hypothesis}


def parse(raw_text: str) -> ParsedResponse:
    """Retire les lignes de balises en tête de réponse (dans n'importe quel ordre)."""
    lines = raw_text.splitlines()
    emotion, signal = "neutre", None
    consumed = 0
    for line in lines[:4]:
        if not line.strip():
            consumed += 1
            continue
        m = TAG_LINE.match(line)
        if not m:
            break
        tag, value = m.group(1).upper(), m.group(2)
        if tag == "EMOTION" and value.strip().lower() in EMOTIONS:
            emotion = value.strip().lower()
        elif tag == "SIGNAL":
            signal = _signal_from(value) or signal
        elif tag == "MEMORY" and value.strip().lower() != "none" and signal is None:
            signal = {"type": "nouveaute", "question": f"Un usager affirme : {value.strip()} Est-ce attesté, et dans quel contexte ?",
                      "hypothesis": value.strip()}
        consumed += 1
    text = "\n".join(lines[consumed:]).strip()
    return ParsedResponse(text=text or raw_text.strip(), emotion=emotion, signal=signal)
