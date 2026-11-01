"""app/journal.py — journal épistémique en ajout seul.

Chaque changement d'état de la connaissance est inscrit ici : proposition,
verdict formel, avis d'expert, décision, révision, retrait, question
d'investigation, nouvelle version de l'ontologie. La base SQLite refuse toute
modification ou suppression d'une ligne du journal (déclencheurs dans db.py) :
une correction s'inscrit toujours comme un nouvel événement.

Chaque événement porte la version de l'ontologie active au moment où il est
écrit, ce qui permet de savoir sur quelle version une décision a été prise.

Types d'événements utilisés dans le code (event_type) :
    contribution_proposee, contribution_decidee,
    document_soumis, document_decide, extraction_lancee, extraction_terminee,
    signal_recu, question_creee, question_regroupee, question_decidee, avis_depose,
    assertion_proposee, verdict_formel, assertion_decidee, assertion_retiree,
    evolution_proposee, evolution_appliquee, evolution_rejetee, version_ontologie,
    retour_version, ontologie_importee, import_connecteur, controle_fidelite
"""
from __future__ import annotations

from typing import Any

from . import db


def current_ontology_version() -> int | None:
    row = db.fetch_one("SELECT MAX(version) AS v FROM ontology_versions")
    return row["v"] if row else None


def append(event_type: str, subject_type: str, subject_id: Any, actor: str, payload: dict | None = None) -> int:
    """Inscrit un événement. `actor` désigne qui agit : 'usager', 'agent',
    'systeme', 'connecteur', ou le nom d'un expert."""
    return db.execute(
        "INSERT INTO journal (ts, event_type, subject_type, subject_id, actor, ontology_version, payload)"
        " VALUES (?,?,?,?,?,?,?)",
        (
            db.now_iso(), event_type, subject_type,
            None if subject_id is None else str(subject_id),
            actor, current_ontology_version(), db.dumps(payload or {}),
        ),
    )


def history(subject_type: str | None = None, subject_id: Any = None, event_type: str | None = None,
            limit: int = 200, before_id: int | None = None) -> list[dict]:
    """Lecture filtrée, du plus récent au plus ancien, avec pagination par identifiant."""
    clauses, params = [], []
    if subject_type:
        clauses.append("subject_type = ?")
        params.append(subject_type)
    if subject_id is not None:
        clauses.append("subject_id = ?")
        params.append(str(subject_id))
    if event_type:
        clauses.append("event_type = ?")
        params.append(event_type)
    if before_id:
        clauses.append("id < ?")
        params.append(before_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return db.fetch_all(
        f"SELECT * FROM journal {where} ORDER BY id DESC LIMIT ?", (*params, limit), json_fields=("payload",)
    )
