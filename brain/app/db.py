"""app/db.py — base SQLite du service brain.

Pourquoi SQLite plutôt que des fichiers JSON (version précédente) ?
- plusieurs routes écrivent en même temps (conversations, panneau d'administration,
  extraction en tâche de fond) : SQLite gère les écritures concurrentes ;
- le journal épistémique doit être interrogeable (par sujet, par type, par date) ;
- le fichier reste unique, local et sans serveur : le principe « local d'abord »
  de l'architecture est conservé.

Le schéma est créé au démarrage (init_db). Les registres JSON de la version
précédente (contributions.json, documents.json) sont migrés automatiquement au
premier démarrage, puis renommés en *.migrated.json (voir migrate_legacy_json).

Le journal est protégé en ajout seul par deux déclencheurs SQL qui refusent
toute modification ou suppression (voir SCHEMA, table journal).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import DATA_DIR, DB_PATH

SCHEMA = """
PRAGMA journal_mode = WAL;

-- Contributions explicites (formulaire) ou automatiques (balise de l'agent).
CREATE TABLE IF NOT EXISTS contributions (
    id              INTEGER PRIMARY KEY,
    type            TEXT NOT NULL,
    content         TEXT NOT NULL,
    submitted_by    TEXT,
    origin          TEXT NOT NULL DEFAULT 'usager',   -- 'usager' | 'agent'
    question_id     INTEGER,                          -- question d'investigation liée
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    created_at      TEXT NOT NULL,
    reviewed_at     TEXT,
    reviewed_notes  TEXT
);

-- Documents soumis ; le texte extrait n'est vectorisé qu'après approbation.
CREATE TABLE IF NOT EXISTS documents (
    id                 INTEGER PRIMARY KEY,
    filename           TEXT NOT NULL,
    stored_as          TEXT NOT NULL,
    size_bytes         INTEGER NOT NULL,
    submitted_by       TEXT,
    note               TEXT,
    extracted_text     TEXT,
    extraction_error   TEXT,
    status             TEXT NOT NULL DEFAULT 'pending',
    chunks_indexed     INTEGER,
    assertion_extraction TEXT,          -- null | running | done | failed (phase 2)
    assertion_extraction_detail TEXT,
    created_at         TEXT NOT NULL,
    reviewed_at        TEXT,
    reviewed_notes     TEXT
);

-- Journal épistémique : un événement par changement d'état de la connaissance.
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,                 -- ex. collecte.temoignages
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    updated_by  TEXT
);

CREATE TABLE IF NOT EXISTS journal (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ts               TEXT NOT NULL,
    event_type       TEXT NOT NULL,
    subject_type     TEXT NOT NULL,
    subject_id       TEXT,
    actor            TEXT NOT NULL,
    ontology_version INTEGER,
    payload          TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_journal_subject ON journal(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_journal_type ON journal(event_type);
CREATE TRIGGER IF NOT EXISTS journal_no_update BEFORE UPDATE ON journal
BEGIN SELECT RAISE(ABORT, 'Le journal est en ajout seul : modification interdite.'); END;
CREATE TRIGGER IF NOT EXISTS journal_no_delete BEFORE DELETE ON journal
BEGIN SELECT RAISE(ABORT, 'Le journal est en ajout seul : suppression interdite.'); END;

-- Questions d'investigation (phase 1) : signaux regroupés et priorisés.
CREATE TABLE IF NOT EXISTS questions (
    id               INTEGER PRIMARY KEY,
    signal_type      TEXT NOT NULL,     -- lacune | contradiction | nouveaute | ambiguite
    question         TEXT NOT NULL,     -- formulation destinée aux experts
    hypothesis       TEXT,              -- hypothèse proposée par l'agent (texte)
    agent_knowledge  TEXT,              -- ce que l'agent savait au moment du signal
    status           TEXT NOT NULL DEFAULT 'open', -- open | complement | deliberation | validated | rejected
    priority         REAL NOT NULL DEFAULT 0,
    occurrences      INTEGER NOT NULL DEFAULT 0,
    distinct_clients INTEGER NOT NULL DEFAULT 0,
    embedding        TEXT,              -- vecteur JSON, pour le regroupement
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    decided_at       TEXT,
    decision         TEXT               -- JSON : issue, expert, notes, assertion_id
);

-- Chaque signal rattaché à une question (extrait anonymisé de l'échange).
CREATE TABLE IF NOT EXISTS question_occurrences (
    id           INTEGER PRIMARY KEY,
    question_id  INTEGER NOT NULL REFERENCES questions(id),
    client_hash  TEXT,
    excerpt      TEXT,
    created_at   TEXT NOT NULL
);

-- Avis motivés des experts (délibération), sur une question ou une assertion.
CREATE TABLE IF NOT EXISTS opinions (
    id            INTEGER PRIMARY KEY,
    question_id   INTEGER,
    assertion_id  INTEGER,
    change_id     INTEGER,
    expert        TEXT NOT NULL,
    position      TEXT NOT NULL,     -- pour | contre | reserve
    argument      TEXT,
    created_at    TEXT NOT NULL
);

-- Assertions candidates (phases 2 et 3) : unité pivot de toute connaissance nouvelle.
CREATE TABLE IF NOT EXISTS assertions (
    id              INTEGER PRIMARY KEY,
    subject         TEXT NOT NULL,
    subject_class   TEXT,
    predicate       TEXT NOT NULL,
    object          TEXT NOT NULL,
    object_class    TEXT,
    object_is_literal INTEGER NOT NULL DEFAULT 0,
    scope           TEXT NOT NULL DEFAULT '{}',   -- JSON : chefferie, lignage, période, source...
    source_type     TEXT NOT NULL,                -- document | connecteur | question | conversation
    source_ref      TEXT,                         -- ex. document:12#chunk3, batch:4#record17
    citation        TEXT,                         -- passage ou valeur exacte de la source
    method          TEXT NOT NULL,                -- extraction_guidee | correspondance | detection_variantes | expert
    confidence      REAL,
    verdict         TEXT,                         -- conforme | en_tension | hors_ontologie
    access_level    TEXT NOT NULL DEFAULT 'public', -- niveau d'accès déclaré par le profil
    verdict_details TEXT NOT NULL DEFAULT '{}',   -- JSON : violations, contradictions, terme hors ontologie
    status          TEXT NOT NULL DEFAULT 'pending', -- pending | deliberation | validated | rejected | retired
    batch_id        INTEGER,
    question_id     INTEGER,
    created_at      TEXT NOT NULL,
    decided_at      TEXT,
    decided_by      TEXT,
    decision_notes  TEXT
);
CREATE INDEX IF NOT EXISTS idx_assertions_status ON assertions(status);
CREATE INDEX IF NOT EXISTS idx_assertions_subject ON assertions(subject);

-- Versions de l'ontologie (phase 3) : chaque changement publié crée une version.
CREATE TABLE IF NOT EXISTS ontology_versions (
    version     INTEGER PRIMARY KEY,
    created_at  TEXT NOT NULL,
    file        TEXT NOT NULL,       -- instantané dans data/ontology_versions/
    format      TEXT NOT NULL,       -- json | owl
    reason      TEXT NOT NULL,
    change_id   INTEGER
);

-- Propositions d'évolution de l'ontologie (phase 3), en opérations d'un catalogue fermé.
CREATE TABLE IF NOT EXISTS ontology_changes (
    id              INTEGER PRIMARY KEY,
    proposal_text   TEXT NOT NULL,     -- proposition en langage naturel
    operations      TEXT NOT NULL,     -- JSON : liste d'opérations du catalogue
    paraphrase      TEXT NOT NULL,     -- paraphrase générée depuis les opérations
    origin          TEXT,              -- ex. assertion:12, question:3, manuel
    status          TEXT NOT NULL DEFAULT 'proposed', -- proposed | deliberation | applied | rejected | reverted
    created_at      TEXT NOT NULL,
    applied_version INTEGER,
    decided_by      TEXT,
    notes           TEXT
);

-- Lots d'import des connecteurs (phase 3).
CREATE TABLE IF NOT EXISTS import_batches (
    id            INTEGER PRIMARY KEY,
    connector     TEXT NOT NULL,      -- csv | json
    filename      TEXT NOT NULL,
    mapping       TEXT NOT NULL,      -- JSON
    n_records     INTEGER NOT NULL DEFAULT 0,
    n_assertions  INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'running',  -- running | done | failed
    report        TEXT,                             -- JSON : bilan de l'import
    created_at    TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Connexion courte, validée à la sortie du bloc (ou annulée en cas d'erreur)."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        # Mise à niveau d'une base créée avant l'introduction des niveaux d'accès.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(assertions)").fetchall()}
        if "access_level" not in cols:
            conn.execute("ALTER TABLE assertions ADD COLUMN access_level TEXT NOT NULL DEFAULT 'public'")
        # Empreinte du fichier et de la correspondance d'un lot, pour refuser un import en double.
        bcols = {r[1] for r in conn.execute("PRAGMA table_info(import_batches)").fetchall()}
        if "file_hash" not in bcols:
            conn.execute("ALTER TABLE import_batches ADD COLUMN file_hash TEXT")


def row_to_dict(row: sqlite3.Row | None, json_fields: tuple[str, ...] = ()) -> dict | None:
    """Convertit une ligne en dictionnaire et décode les champs JSON indiqués."""
    if row is None:
        return None
    d = dict(row)
    for f in json_fields:
        if f in d and isinstance(d[f], str):
            try:
                d[f] = json.loads(d[f])
            except json.JSONDecodeError:
                pass
    return d


def fetch_all(sql: str, params: tuple = (), json_fields: tuple[str, ...] = ()) -> list[dict]:
    with connect() as conn:
        return [row_to_dict(r, json_fields) for r in conn.execute(sql, params).fetchall()]


def fetch_one(sql: str, params: tuple = (), json_fields: tuple[str, ...] = ()) -> dict | None:
    with connect() as conn:
        return row_to_dict(conn.execute(sql, params).fetchone(), json_fields)


def execute(sql: str, params: tuple = ()) -> int:
    """Exécute une écriture et renvoie l'identifiant de la ligne insérée."""
    with connect() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def migrate_legacy_json() -> dict:
    """Importe contributions.json et documents.json (version précédente) si les
    tables correspondantes sont vides, puis renomme les fichiers. Idempotent."""
    report = {"contributions": 0, "documents": 0}
    legacy_c = DATA_DIR / "contributions.json"
    legacy_d = DATA_DIR / "documents.json"
    with connect() as conn:
        if legacy_c.exists() and conn.execute("SELECT COUNT(*) FROM contributions").fetchone()[0] == 0:
            for c in json.loads(legacy_c.read_text(encoding="utf-8") or "[]"):
                conn.execute(
                    "INSERT INTO contributions (id, type, content, submitted_by, origin, status, created_at, reviewed_at, reviewed_notes)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        c["id"], c.get("type", "autre"), c["content"], c.get("submittedBy"),
                        "agent" if c.get("type") == "auto_extrait" else "usager",
                        c.get("status", "pending"), c.get("createdAt") or now_iso(), c.get("reviewedAt"), c.get("reviewedNotes"),
                    ),
                )
                report["contributions"] += 1
        if legacy_d.exists() and conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0:
            for d in json.loads(legacy_d.read_text(encoding="utf-8") or "[]"):
                conn.execute(
                    "INSERT INTO documents (id, filename, stored_as, size_bytes, submitted_by, note, extracted_text, extraction_error,"
                    " status, chunks_indexed, created_at, reviewed_at, reviewed_notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        d["id"], d["filename"], d.get("storedAs", ""), d.get("sizeBytes", 0), d.get("submittedBy"), d.get("note"),
                        d.get("extractedText"), d.get("extractionError"), d.get("status", "pending"), d.get("chunksIndexed"),
                        d.get("createdAt") or now_iso(), d.get("reviewedAt"), d.get("reviewedNotes"),
                    ),
                )
                report["documents"] += 1
    for p in (legacy_c, legacy_d):
        if p.exists():
            p.rename(p.with_suffix(".migrated.json"))
    return report
