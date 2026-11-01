"""app/investigations.py — proactivité de l'agent : questions d'investigation (phase 1).

À chaque échange, l'agent qualifie la situation épistémique par une balise
(voir response_parser.py). Quatre signaux sont retenus :

    lacune         la question ne trouve d'appui ni dans l'ontologie ni dans le corpus ;
    contradiction  l'usager affirme un fait contraire à une connaissance validée ;
    nouveaute      l'usager affirme un fait absent des connaissances ;
    ambiguite      les règles s'appliquent sans permettre de trancher.

Un signal ne parvient pas tel quel aux experts : il devient une question
d'investigation, formulée pour eux, accompagnée d'un extrait anonymisé de
l'échange, de ce que l'agent savait et d'une hypothèse éventuelle. Les signaux
proches sont regroupés (similarité d'embeddings, ou repli lexical), et chaque
question porte son nombre d'occurrences et d'usagers distincts, qui déterminent
sa priorité (PRIORITY_WEIGHTS).

Les experts décident : validation (avec portée), rejet motivé, demande de
complément ou délibération. Une validation crée une ou plusieurs assertions
validées, qui enrichissent immédiatement les réponses de l'agent.
"""
from __future__ import annotations

import hashlib

from .profile import active as active_profile
from . import anthropic_client, assertions, db, journal, paraphrase, validation, vectorstore
from .config import INTERNAL_SECRET, SIGNAL_JACCARD, SIGNAL_SIMILARITY
from .ontology_loader import load_active, vocabulary_brief
from .text_utils import anonymize, cosine, jaccard

SIGNAL_TYPES = {"lacune", "contradiction", "nouveaute", "ambiguite"}
OPEN_STATUSES = ("open", "complement", "deliberation")

# Poids du type de signal dans la priorité : une contradiction répétée prime sur une lacune isolée.
PRIORITY_WEIGHTS = {"contradiction": 3.0, "nouveaute": 2.0, "ambiguite": 2.0, "lacune": 1.0}


class TensionError(Exception):
    """Levée quand une validation porte sur une assertion en tension : l'expert
    doit confirmer en connaissance de cause (les questions du domaine sont jointes)."""

    def __init__(self, details: list[dict]):
        super().__init__("Tension détectée")
        self.details = details


def client_hash(client_id: str | None) -> str | None:
    """Identifiant d'usager irréversible : sert seulement à compter les usagers distincts."""
    if not client_id:
        return None
    return hashlib.sha256((INTERNAL_SECRET + "|" + client_id).encode()).hexdigest()[:16]


def priority(signal_type: str, occurrences: int, distinct_clients: int) -> float:
    return PRIORITY_WEIGHTS.get(signal_type, 1.0) + occurrences + 2 * distinct_clients


def _find_similar(signal_type: str, text: str, vector: list[float] | None) -> dict | None:
    """Question ouverte du même type la plus proche, si elle dépasse le seuil."""
    rows = db.fetch_all(
        f"SELECT * FROM questions WHERE signal_type = ? AND status IN {OPEN_STATUSES}", (signal_type,), json_fields=("embedding",)
    )
    best, best_score = None, 0.0
    for q in rows:
        if vector is not None and isinstance(q.get("embedding"), list):
            score, threshold = cosine(vector, q["embedding"]), SIGNAL_SIMILARITY
        else:
            score, threshold = jaccard(text, q["question"]), SIGNAL_JACCARD
        if score >= threshold and score > best_score:
            best, best_score = q, score
    return best


def record_signal(signal_type: str, question_text: str, hypothesis: str | None, agent_knowledge: str | None,
                  user_message: str, client_id: str | None) -> dict:
    """Transforme un signal en question d'investigation (nouvelle ou regroupée)."""
    if signal_type not in SIGNAL_TYPES:
        raise ValueError(f"Type de signal inconnu : {signal_type}")
    question_text = question_text.strip()[:600]
    vectors = vectorstore.try_embed([question_text])
    vector = vectors[0] if vectors else None
    chash = client_hash(client_id)
    excerpt = anonymize(user_message)
    now = db.now_iso()

    existing = _find_similar(signal_type, question_text, vector)
    if existing:
        qid, created = existing["id"], False
    else:
        qid = db.execute(
            "INSERT INTO questions (signal_type, question, hypothesis, agent_knowledge, status, priority, occurrences,"
            " distinct_clients, embedding, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (signal_type, question_text, hypothesis, agent_knowledge, "open", 0, 0, 0,
             db.dumps(vector) if vector else None, now, now),
        )
        created = True
    db.execute("INSERT INTO question_occurrences (question_id, client_hash, excerpt, created_at) VALUES (?,?,?,?)",
               (qid, chash, excerpt, now))
    stats = db.fetch_one(
        "SELECT COUNT(*) AS n, COUNT(DISTINCT client_hash) AS c FROM question_occurrences WHERE question_id = ?", (qid,)
    )
    db.execute(
        "UPDATE questions SET occurrences = ?, distinct_clients = ?, priority = ?, updated_at = ?"
        + (", hypothesis = COALESCE(hypothesis, ?)" if not created else "") + " WHERE id = ?",
        (stats["n"], stats["c"], priority(signal_type, stats["n"], stats["c"]), now,
         *((hypothesis,) if not created else ()), qid),
    )
    journal.append("signal_recu", "question", qid, "agent", {"type": signal_type, "excerpt": excerpt})
    journal.append("question_creee" if created else "question_regroupee", "question", qid, "agent",
                   {"question": question_text, "hypothesis": hypothesis})

    if signal_type == "nouveaute" and hypothesis:
        # Compatibilité avec le circuit existant : un fait nouveau devient aussi une
        # contribution en attente, examinable dans l'onglet Contributions.
        cid = db.execute(
            "INSERT INTO contributions (type, content, submitted_by, origin, question_id, status, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            ("auto_extrait", hypothesis, f"{active_profile().agent.get('nom', 'Agent')} (extraction automatique)", "agent", qid, "pending", now),
        )
        journal.append("contribution_proposee", "contribution", cid, "agent", {"question_id": qid})
    return {**get(qid), "nouvelle": created}


def get(question_id: int) -> dict | None:
    q = db.fetch_one("SELECT * FROM questions WHERE id = ?", (question_id,), json_fields=("decision",))
    if not q:
        return None
    q.pop("embedding", None)
    q["occurrences_list"] = db.fetch_all(
        "SELECT id, excerpt, created_at FROM question_occurrences WHERE question_id = ? ORDER BY id DESC LIMIT 20", (question_id,)
    )
    q["opinions"] = db.fetch_all("SELECT * FROM opinions WHERE question_id = ? ORDER BY id", (question_id,))
    q["assertions"] = [assertions.get(r["id"]) for r in db.fetch_all("SELECT id FROM assertions WHERE question_id = ?", (question_id,))]
    return q


def list_questions(status: str | None = None) -> list[dict]:
    if status == "open":
        rows = db.fetch_all(f"SELECT * FROM questions WHERE status IN {OPEN_STATUSES} ORDER BY priority DESC, updated_at DESC")
    elif status:
        rows = db.fetch_all("SELECT * FROM questions WHERE status = ? ORDER BY updated_at DESC", (status,))
    else:
        rows = db.fetch_all("SELECT * FROM questions ORDER BY priority DESC, updated_at DESC")
    for r in rows:
        r.pop("embedding", None)
    return rows


def add_opinion(question_id: int, expert: str, position: str, argument: str | None) -> dict:
    if position not in {"pour", "contre", "reserve"}:
        raise ValueError("La position doit être 'pour', 'contre' ou 'reserve'.")
    oid = db.execute(
        "INSERT INTO opinions (question_id, expert, position, argument, created_at) VALUES (?,?,?,?,?)",
        (question_id, expert, position, argument, db.now_iso()),
    )
    journal.append("avis_depose", "question", question_id, expert, {"position": position, "argument": argument, "opinion_id": oid})
    return get(question_id)


def decide(question_id: int, outcome: str, expert: str, notes: str | None = None,
           new_assertions: list[dict] | None = None, confirm_tension: bool = False) -> dict:
    """Décision d'un expert sur une question d'investigation.

    outcome :
      validated    — crée les assertions fournies (new_assertions) et les valide ;
      rejected     — rejet motivé (notes) ;
      complement   — demande de complément : la question reste ouverte ;
      deliberation — la question est soumise à plusieurs experts (voir add_opinion).
    Si une assertion est en tension et que confirm_tension est faux, rien n'est
    enregistré et TensionError fournit les questions du domaine à examiner."""
    q = get(question_id)
    if not q:
        raise LookupError("Question introuvable.")
    if outcome not in {"validated", "rejected", "complement", "deliberation"}:
        raise ValueError("Issue inconnue.")
    created_ids: list[int] = []
    if outcome == "validated":
        if not new_assertions:
            raise ValueError("Une validation doit préciser au moins une connaissance à retenir.")
        vocab = load_active().vocabulary
        previews = []
        for a in new_assertions:
            probe = {**a, "scope": a.get("scope") or {}}
            verdict, details = validation.evaluate(probe, vocab)
            previews.append({"paraphrase": paraphrase.assertion_text(probe, vocab), "verdict": verdict, "details": details})
        tensions = [p for p in previews if p["verdict"] != "conforme"]
        if tensions and not confirm_tension:
            raise TensionError(tensions)
        for a in new_assertions:
            created = assertions.create(
                {**a, "source_type": "question", "source_ref": f"question:{question_id}", "method": "expert",
                 "question_id": question_id, "citation": notes},
                expert,
            )
            assertions.decide(created["id"], "validated", expert, notes)
            created_ids.append(created["id"])
    status = {"validated": "validated", "rejected": "rejected", "complement": "complement", "deliberation": "deliberation"}[outcome]
    decision = {"outcome": outcome, "expert": expert, "notes": notes, "assertion_ids": created_ids}
    db.execute(
        "UPDATE questions SET status = ?, decision = ?, decided_at = ?, updated_at = ? WHERE id = ?",
        (status, db.dumps(decision), db.now_iso() if outcome in {"validated", "rejected"} else None, db.now_iso(), question_id),
    )
    journal.append("question_decidee", "question", question_id, expert, decision)
    return get(question_id)


FORMALIZE_ANSWER_SYSTEM = """Un expert d'un savoir traditionnel répond, en français courant, à une question
d'investigation. Traduis sa réponse en assertions exprimées dans le vocabulaire de l'ontologie fournie.

Chaque assertion : {"subject":..., "subject_class":<classe ou null>, "predicate":<relation ou attribut de l'ontologie,
ou "estUn">, "object":..., "object_class":<classe ou null>, "object_is_literal":<true|false>,
"scope":{{SCOPE_KEYS}}}
N'inclus dans scope que les clés que la réponse de l'expert justifie. N'ajoute AUCUN fait absent de sa réponse.
Si la réponse mobilise une notion absente de l'ontologie, ne force pas : signale-la dans "hors_ontologie".
Format : {"assertions":[...], "hors_ontologie":[{"term":..., "justification":...}], "commentaire":...}"""


async def formalize_answer(question_id: int, answer_text: str) -> dict:
    """Propose, à partir de la réponse rédigée par un expert, les assertions à valider,
    avec leur paraphrase et leur verdict formel. Rien n'est enregistré ici."""
    q = get(question_id)
    if not q:
        raise LookupError("Question introuvable.")
    vocab = load_active().vocabulary
    user = (f"ONTOLOGIE :\n{vocabulary_brief(vocab)}\n\nQUESTION : {q['question']}\n"
            f"HYPOTHÈSE DE L'AGENT : {q.get('hypothesis') or 'aucune'}\n\nRÉPONSE DE L'EXPERT :\n{answer_text}")
    # Les clés de portée proposées au modèle sont celles que déclare le profil du domaine.
    keys = ", ".join(f'"{d["cle"]}":...' for d in active_profile().raw.get("portee", []))
    result = await anthropic_client.complete_json(FORMALIZE_ANSWER_SYSTEM.replace("{SCOPE_KEYS}", keys), user)
    out = []
    for a in (result.get("assertions") or []) if isinstance(result, dict) else []:
        if not all(a.get(k) for k in ("subject", "predicate", "object")):
            continue
        a["scope"] = {k: v for k, v in (a.get("scope") or {}).items() if v not in (None, "", [])}
        verdict, details = validation.evaluate(dict(a), vocab)
        out.append({"assertion": a, "paraphrase": paraphrase.assertion_text(a, vocab), "verdict": verdict,
                    "questions_domaine": details.get("questions_domaine", [])})
    return {"propositions": out, "hors_ontologie": result.get("hors_ontologie", []) if isinstance(result, dict) else [],
            "commentaire": result.get("commentaire") if isinstance(result, dict) else None}
