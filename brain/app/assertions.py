"""app/assertions.py — cycle de vie des assertions candidates (phases 2 et 3).

L'assertion candidate est l'unité pivot de la conception : toute connaissance
nouvelle, qu'elle vienne d'un document (extraction guidée), d'un fichier de
données (connecteur), d'une question d'investigation ou d'un expert, prend cette
forme avant d'entrer dans la base de connaissances.

Cycle de vie (statut) :
    pending ──► validated ──► retired
       │  └──► deliberation ──► validated | rejected
       └──► rejected

Seules les assertions « validated » sont visibles de l'agent (dossier de réponse)
et figurent dans le graphe d'enrichissements (enrichments.py). Toute transition
est inscrite au journal épistémique.
"""
from __future__ import annotations

from . import db, enrichments, journal, paraphrase, validation
from .ontology_loader import load_active
from .profile import active as active_profile

JSON_FIELDS = ("scope", "verdict_details")
STATUSES = {"pending", "deliberation", "validated", "rejected", "retired"}


def _decorate(a: dict, vocab=None) -> dict:
    vocab = vocab or load_active().vocabulary
    a["paraphrase"] = paraphrase.assertion_text(a, vocab)
    a["object_is_literal"] = bool(a.get("object_is_literal"))
    return a


def get(assertion_id: int) -> dict | None:
    a = db.fetch_one("SELECT * FROM assertions WHERE id = ?", (assertion_id,), json_fields=JSON_FIELDS)
    return _decorate(a) if a else None


def list_assertions(status: str | None = None, verdict: str | None = None, batch_id: int | None = None,
                    source_type: str | None = None, limit: int = 300, offset: int = 0) -> list[dict]:
    clauses, params = [], []
    for col, val in (("status", status), ("verdict", verdict), ("batch_id", batch_id), ("source_type", source_type)):
        if val is not None:
            clauses.append(f"{col} = ?")
            params.append(val)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = db.fetch_all(
        f"SELECT * FROM assertions {where} ORDER BY id DESC LIMIT ? OFFSET ?", (*params, limit, offset), json_fields=JSON_FIELDS
    )
    vocab = load_active().vocabulary
    return [_decorate(r, vocab) for r in rows]


def create(data: dict, actor: str) -> dict:
    """Crée une assertion candidate, calcule son verdict formel et journalise.

    `data` contient : subject, predicate, object, et optionnellement subject_class,
    object_class, object_is_literal, scope (dict), source_type, source_ref, citation,
    method, confidence, batch_id, question_id, out_of_ontology_term (dict).
    """
    a = {
        "subject": str(data["subject"]).strip(),
        "subject_class": data.get("subject_class") or None,
        "predicate": str(data["predicate"]).strip(),
        "object": str(data["object"]).strip(),
        "object_class": data.get("object_class") or None,
        "object_is_literal": bool(data.get("object_is_literal")),
        "scope": data.get("scope") or {},
        "out_of_ontology_term": data.get("out_of_ontology_term"),
    }
    verdict, details = validation.evaluate(a)
    # Niveau d'accès : celui qui est fourni (décision d'expert), sinon celui que fixent les
    # règles d'accès du profil, sinon le niveau par défaut du profil.
    profile = active_profile()
    access = data.get("access_level") if data.get("access_level") in profile.access_levels else profile.access_for(a)
    new_id = db.execute(
        "INSERT INTO assertions (subject, subject_class, predicate, object, object_class, object_is_literal, scope,"
        " source_type, source_ref, citation, method, confidence, verdict, verdict_details, access_level, status, batch_id,"
        " question_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            a["subject"], a["subject_class"], a["predicate"], a["object"], a["object_class"], int(a["object_is_literal"]),
            db.dumps(a["scope"]), data.get("source_type", "manuel"), data.get("source_ref"), data.get("citation"),
            data.get("method", "manuel"), data.get("confidence"), verdict, db.dumps(details), access, "pending",
            data.get("batch_id"), data.get("question_id"), db.now_iso(),
        ),
    )
    journal.append("assertion_proposee", "assertion", new_id, actor,
                   {"source_type": data.get("source_type"), "source_ref": data.get("source_ref"), "method": data.get("method"),
                    "access_level": access})
    journal.append("verdict_formel", "assertion", new_id, "systeme", {"verdict": verdict, "details": details})
    return get(new_id)


def decide(assertion_id: int, decision: str, expert: str, notes: str | None = None, scope: dict | None = None,
           access_level: str | None = None) -> dict:
    """Décision d'un expert : validated, rejected ou deliberation.
    `scope` permet de valider avec une portée restreinte ou reformulée."""
    if decision not in {"validated", "rejected", "deliberation"}:
        raise ValueError("La décision doit être 'validated', 'rejected' ou 'deliberation'.")
    a = get(assertion_id)
    if not a:
        raise LookupError("Assertion introuvable.")
    if a["status"] not in {"pending", "deliberation"}:
        raise ValueError(f"Assertion déjà décidée (statut : {a['status']}).")
    with db.connect() as conn:
        if scope is not None:
            conn.execute("UPDATE assertions SET scope = ? WHERE id = ?", (db.dumps(scope), assertion_id))
        if access_level is not None:
            if access_level not in active_profile().access_levels:
                raise ValueError(f"Niveau d'accès inconnu du profil : {access_level}")
            conn.execute("UPDATE assertions SET access_level = ? WHERE id = ?", (access_level, assertion_id))
        conn.execute(
            "UPDATE assertions SET status = ?, decided_at = ?, decided_by = ?, decision_notes = ? WHERE id = ?",
            (decision, db.now_iso() if decision != "deliberation" else None, expert, notes, assertion_id),
        )
    journal.append("assertion_decidee", "assertion", assertion_id, expert,
                   {"decision": decision, "notes": notes, "scope": scope, "access_level": access_level,
                    "paraphrase": a["paraphrase"]})
    if decision == "validated":
        enrichments.rebuild()
    return get(assertion_id)


def retire(assertion_id: int, expert: str, notes: str | None = None) -> dict:
    """Retrait d'une connaissance validée, à la lumière de nouvelles sources.
    Rien n'est effacé : le statut passe à 'retired' et le journal en garde la trace."""
    a = get(assertion_id)
    if not a or a["status"] != "validated":
        raise ValueError("Seule une assertion validée peut être retirée.")
    db.execute("UPDATE assertions SET status = 'retired', decision_notes = ? WHERE id = ?", (notes, assertion_id))
    journal.append("assertion_retiree", "assertion", assertion_id, expert, {"notes": notes})
    enrichments.rebuild()
    return get(assertion_id)


def validate_conforming_in_batch(batch_id: int, expert: str) -> dict:
    """Validation groupée des assertions CONFORMES et en attente d'un lot d'import.
    Les assertions en tension ou hors ontologie restent à examiner une par une."""
    rows = db.fetch_all(
        "SELECT id FROM assertions WHERE batch_id = ? AND status = 'pending' AND verdict = 'conforme'", (batch_id,)
    )
    ids = [r["id"] for r in rows]
    if ids:
        now = db.now_iso()
        with db.connect() as conn:
            conn.executemany(
                "UPDATE assertions SET status = 'validated', decided_at = ?, decided_by = ?, decision_notes = ? WHERE id = ?",
                [(now, expert, f"Validation groupée du lot {batch_id}", i) for i in ids],
            )
        for i in ids:
            journal.append("assertion_decidee", "assertion", i, expert, {"decision": "validated", "groupee": True, "batch_id": batch_id})
        enrichments.rebuild()
    return {"validated": len(ids)}


def deduplicate(expert: str) -> dict:
    """Retire les connaissances en double : même sujet, prédicat, objet et portée. La plus ancienne
    est conservée ; les autres sont retirées si elles étaient validées, rejetées si elles étaient
    en attente. Chaque décision est signée et journalisée."""
    rows = db.fetch_all("SELECT * FROM assertions WHERE status IN ('validated','pending','deliberation') ORDER BY id",
                        json_fields=JSON_FIELDS)
    seen: dict[tuple, int] = {}
    retired = rejected = 0
    for a in rows:
        key = (a["subject"], a["predicate"], a["object"], db.dumps(a.get("scope") or {}))
        if key not in seen:
            seen[key] = a["id"]; continue
        note = f"Doublon de la connaissance n° {seen[key]}"
        if a["status"] == "validated":
            retire(a["id"], expert, note); retired += 1
        else:
            decide(a["id"], "rejected", expert, note); rejected += 1
    return {"retirees": retired, "rejetees": rejected}


def reevaluate_pending() -> int:
    """Recalcule le verdict des assertions en attente (après une évolution de
    l'ontologie, une assertion hors ontologie peut devenir conforme)."""
    vocab = load_active().vocabulary
    rows = db.fetch_all("SELECT * FROM assertions WHERE status IN ('pending','deliberation')", json_fields=JSON_FIELDS)
    changed = 0
    for r in rows:
        r["out_of_ontology_term"] = None
        verdict, details = validation.evaluate(r, vocab)
        if verdict != r["verdict"]:
            db.execute("UPDATE assertions SET verdict = ?, verdict_details = ? WHERE id = ?", (verdict, db.dumps(details), r["id"]))
            journal.append("verdict_formel", "assertion", r["id"], "systeme", {"verdict": verdict, "reevaluation": True})
            changed += 1
    return changed
