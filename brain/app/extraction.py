"""app/extraction.py — extraction de connaissances gouvernée par l'ontologie (phase 2).

Double barrière de la conception :

1. Contrainte en amont. Le LLM reçoit la description du vocabulaire de
   l'ontologie (classes, relations, attributs) et un format de sortie dans lequel
   classes et prédicats doivent appartenir à ce vocabulaire. Chaque assertion doit
   citer mot pour mot le passage qui la fonde. Une seule échappatoire :
   « hors_ontologie », pour signaler une notion sans équivalent, avec justification.

2. Validation en aval. Chaque assertion est :
   - rejetée si sa citation ne figure pas dans le passage (irrecevable) ;
   - sinon enregistrée comme candidate, avec son verdict formel (validation.py).

Rien de ce qui est extrait n'est visible de l'agent avant la décision d'un expert.
L'extraction d'un document approuvé est lancée depuis le panneau d'administration
et s'exécute en tâche de fond ; son état est suivi dans la table documents
(colonne assertion_extraction).
"""
from __future__ import annotations

import logging
import re

from . import anthropic_client, assertions, db, journal
from .config import EXTRACTION_CHUNK_SIZE, EXTRACTION_MAX_CHUNKS
from .ontology_loader import load_active, vocabulary_brief
from .profile import active as active_profile
from .vectorstore import chunk_text

log = logging.getLogger("yobakoko.extraction")

EXTRACTION_SYSTEM = """Tu extrais des connaissances d'un passage de document portant sur un savoir traditionnel,
{domaine}, sous la contrainte stricte d'une ontologie.

RÈGLES :
1. N'utilise QUE les classes et relations de l'ontologie fournie (ou "estUn" pour l'appartenance à une classe).
2. Chaque assertion doit être explicitement affirmée par le passage : n'infère rien, n'ajoute aucune connaissance générale.
3. "citation" doit reproduire MOT POUR MOT l'extrait du passage qui fonde l'assertion (au plus 300 caractères).
4. "scope" précise le contexte de validité si le passage le donne, avec les dimensions suivantes : {dimensions}.
   N'invente pas de portée.
5. Si le passage mobilise une notion importante SANS équivalent dans l'ontologie, ne force pas une traduction :
   ajoute-la dans "hors_ontologie" avec sa citation et une justification.
6. "confidence" entre 0 et 1 reflète la netteté de l'affirmation dans le passage.

FORMAT :
{"assertions":[{"subject":...,"subject_class":...,"predicate":...,"object":...,"object_class":<classe ou null>,
"object_is_literal":<bool>,"scope":{...},"citation":...,"confidence":...}],
"hors_ontologie":[{"term":...,"citation":...,"justification":...}]}
Si le passage ne contient aucune connaissance pertinente, renvoie {"assertions":[],"hors_ontologie":[]}."""


def extraction_system() -> str:
    """Consigne d'extraction, complétée par le domaine et les dimensions de portée du profil."""
    profile = active_profile()
    return (EXTRACTION_SYSTEM
            .replace("{domaine}", profile.agent.get("domaine", "le savoir traité"))
            .replace("{dimensions}", ", ".join(profile.scope_labels) or "aucune"))


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def citation_in_passage(citation: str | None, passage: str) -> bool:
    """La citation doit figurer dans le passage (comparaison insensible aux espaces et à la casse)."""
    return bool(citation) and _squash(citation) in _squash(passage)


async def extract_from_text(text: str, source_type: str, source_ref_prefix: str, actor: str,
                            batch_id: int | None = None) -> dict:
    """Extrait les assertions d'un texte, passage par passage. Renvoie un bilan chiffré."""
    vocab = load_active().vocabulary
    brief = vocabulary_brief(vocab)
    chunks = chunk_text(text, size=EXTRACTION_CHUNK_SIZE, overlap=200)[:EXTRACTION_MAX_CHUNKS]
    report = {"chunks": len(chunks), "created": 0, "irrecevables": 0, "hors_ontologie": 0, "errors": []}
    for i, chunk in enumerate(chunks):
        try:
            result = await anthropic_client.complete_json(extraction_system(), f"ONTOLOGIE :\n{brief}\n\nPASSAGE :\n{chunk}")
        except anthropic_client.AnthropicError as exc:
            report["errors"].append(f"passage {i} : {exc}")
            continue
        if not isinstance(result, dict):
            report["errors"].append(f"passage {i} : réponse inattendue")
            continue
        for a in result.get("assertions") or []:
            if not all(a.get(k) for k in ("subject", "predicate", "object")) or not citation_in_passage(a.get("citation"), chunk):
                report["irrecevables"] += 1
                continue
            assertions.create({
                **a, "scope": {k: v for k, v in (a.get("scope") or {}).items() if v not in (None, "", [])},
                "source_type": source_type, "source_ref": f"{source_ref_prefix}#passage{i}",
                "method": "extraction_guidee", "batch_id": batch_id,
            }, actor)
            report["created"] += 1
        for t in result.get("hors_ontologie") or []:
            if not t.get("term") or not citation_in_passage(t.get("citation"), chunk):
                report["irrecevables"] += 1
                continue
            assertions.create({
                "subject": t["term"], "predicate": "estUn", "object": "?",
                "out_of_ontology_term": {"term": t["term"], "justification": t.get("justification")},
                "source_type": source_type, "source_ref": f"{source_ref_prefix}#passage{i}", "citation": t.get("citation"),
                "method": "extraction_guidee", "batch_id": batch_id,
            }, actor)
            report["hors_ontologie"] += 1
    return report


async def extract_document(doc_id: int) -> None:
    """Tâche de fond : extraction guidée d'un document APPROUVÉ."""
    doc = db.fetch_one("SELECT * FROM documents WHERE id = ?", (doc_id,))
    if not doc or doc["status"] != "approved":
        return
    db.execute("UPDATE documents SET assertion_extraction = 'running', assertion_extraction_detail = NULL WHERE id = ?", (doc_id,))
    journal.append("extraction_lancee", "document", doc_id, "systeme", {})
    try:
        report = await extract_from_text(doc["extracted_text"] or "", "document", f"document:{doc_id}", "agent")
        db.execute("UPDATE documents SET assertion_extraction = 'done', assertion_extraction_detail = ? WHERE id = ?",
                   (db.dumps(report), doc_id))
        journal.append("extraction_terminee", "document", doc_id, "systeme", report)
    except Exception as exc:  # noqa: BLE001 — l'état d'échec doit être visible dans le panneau
        log.exception("Extraction du document %s impossible", doc_id)
        db.execute("UPDATE documents SET assertion_extraction = 'failed', assertion_extraction_detail = ? WHERE id = ?",
                   (db.dumps({"error": str(exc)}), doc_id))
        journal.append("extraction_terminee", "document", doc_id, "systeme", {"error": str(exc)})
