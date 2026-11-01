"""app/routers/knowledge.py — assertions (phases 2 et 3), connecteurs, évolution de
l'ontologie, versions, graphe d'enrichissements et journal épistémique."""
import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from .. import anthropic_client, assertions, connectors, db, enrichments, journal, ontology_evolution
from ..config import ENRICHMENTS_TTL, ONTOLOGY_VERSIONS_DIR
from ..internal_auth import require_internal
from ..ontology_loader import INSTANCE_OF, load_active

router = APIRouter(dependencies=[Depends(require_internal)])


# ---------------------------------------------------------------------------
# Vocabulaire (listes déroulantes du panneau)
# ---------------------------------------------------------------------------
@router.get("/admin/vocabulary")
async def vocabulary():
    v = load_active().vocabulary
    return {
        "format": v.format,
        "classes": sorted(v.classes),
        "predicates": sorted(v.predicate_ids()),
        "objectProperties": {k: {"domain": p.get("domain"), "range": p.get("range")} for k, p in v.object_properties.items()},
        "instanceOf": INSTANCE_OF,
    }


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------
@router.get("/admin/assertions")
async def list_assertions(status: str | None = "pending", verdict: str | None = None, batch: int | None = None,
                          source: str | None = None, limit: int = 300, offset: int = 0):
    return assertions.list_assertions(None if status == "all" else status, verdict, batch, source, limit, offset)


@router.get("/admin/assertions/{aid}")
async def get_assertion(aid: int):
    a = assertions.get(aid)
    if not a:
        raise HTTPException(404, "Assertion introuvable.")
    a["history"] = journal.history("assertion", aid)
    a["opinions"] = db.fetch_all("SELECT * FROM opinions WHERE assertion_id = ? ORDER BY id", (aid,))
    return a


class AssertionIn(BaseModel):
    subject: str
    predicate: str
    object: str
    subject_class: str | None = None
    object_class: str | None = None
    object_is_literal: bool = False
    scope: dict = {}
    citation: str | None = None
    expert: str


@router.post("/admin/assertions")
async def create_assertion(req: AssertionIn):
    """Assertion saisie directement par un expert (source : expert)."""
    data = req.model_dump()
    expert = data.pop("expert")
    return assertions.create({**data, "source_type": "expert", "source_ref": f"expert:{expert}", "method": "expert"}, expert)


class AssertionDecision(BaseModel):
    decision: str                # validated | rejected | deliberation
    expert: str
    notes: str | None = None
    scope: dict | None = None    # portée restreinte ou reformulée
    access_level: str | None = None   # niveau d'accès décidé par l'expert (niveaux du profil)


@router.post("/admin/assertions/{aid}/decide")
async def decide_assertion(aid: int, req: AssertionDecision):
    try:
        return assertions.decide(aid, req.decision, req.expert.strip() or "expert", req.notes, req.scope, req.access_level)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class RetireRequest(BaseModel):
    expert: str
    notes: str | None = None


@router.post("/admin/assertions/{aid}/retire")
async def retire_assertion(aid: int, req: RetireRequest):
    try:
        return assertions.retire(aid, req.expert.strip() or "expert", req.notes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class OpinionIn(BaseModel):
    expert: str
    position: str
    argument: str | None = None


@router.post("/admin/assertions/{aid}/opinions")
async def assertion_opinion(aid: int, req: OpinionIn):
    if req.position not in {"pour", "contre", "reserve"}:
        raise HTTPException(400, "La position doit être 'pour', 'contre' ou 'reserve'.")
    db.execute("INSERT INTO opinions (assertion_id, expert, position, argument, created_at) VALUES (?,?,?,?,?)",
               (aid, req.expert, req.position, req.argument, db.now_iso()))
    journal.append("avis_depose", "assertion", aid, req.expert, {"position": req.position, "argument": req.argument})
    return await get_assertion(aid)


class BatchValidate(BaseModel):
    expert: str


class BatchCancel(BaseModel):
    expert: str
    motif: str | None = None


@router.post("/admin/batches/{bid}/cancel")
async def cancel_batch(bid: int, req: BatchCancel):
    """Annulation d'un lot : connaissances en attente rejetées, connaissances validées retirées."""
    if not req.expert.strip():
        raise HTTPException(400, "Le nom de l'expert est requis pour annuler un lot.")
    try:
        return connectors.cancel_batch(bid, req.expert.strip(), req.motif)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class Dedup(BaseModel):
    expert: str


@router.post("/admin/assertions/deduplicate")
async def deduplicate(req: Dedup):
    """Retrait des connaissances en double (même sujet, prédicat, objet et portée)."""
    if not req.expert.strip():
        raise HTTPException(400, "Le nom de l'expert est requis.")
    return assertions.deduplicate(req.expert.strip())


@router.post("/admin/batches/{bid}/validate-conforming")
async def validate_batch(bid: int, req: BatchValidate):
    return assertions.validate_conforming_in_batch(bid, req.expert.strip() or "expert")


# ---------------------------------------------------------------------------
# Connecteurs
# ---------------------------------------------------------------------------
@router.get("/admin/connectors/presets")
async def presets():
    return connectors.list_presets()


@router.get("/admin/connectors/presets/{name}")
async def preset(name: str):
    try:
        return connectors.load_preset(name)
    except connectors.MappingError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/admin/connectors/batches")
async def batches():
    return connectors.list_batches()


@router.post("/admin/connectors/import")
async def import_file(background: BackgroundTasks, file: UploadFile = File(...),
                      preset: str = Form(default=""), mapping: str = Form(default=""), force: str = Form(default="")):
    """Import d'un fichier CSV ou JSON selon une correspondance prédéfinie (preset)
    ou fournie en JSON (mapping). Le traitement s'exécute en tâche de fond."""
    try:
        m = connectors.load_preset(preset) if preset else json.loads(mapping)
        connectors.check_mapping(m)
    except (connectors.MappingError, json.JSONDecodeError) as exc:
        raise HTTPException(400, f"Correspondance invalide : {exc}") from exc
    content = await file.read()
    try:
        connectors.parse_records(content, m)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Fichier illisible avec cette correspondance : {exc}") from exc
    fingerprint = connectors.import_fingerprint(content, m)
    dup = connectors.find_duplicate_batch(fingerprint)
    if dup and force not in ("1", "true", "oui"):
        raise HTTPException(409, f"Ce fichier a déjà été importé avec cette correspondance (lot n° {dup['id']}, "
                                 f"{dup['created_at'][:10]}). Pour l'importer de nouveau, annulez d'abord ce lot.")
    bid = connectors.create_batch(m["connector"], file.filename, m, fingerprint)
    background.add_task(connectors.run_import, bid, content, m)
    return {"ok": True, "batchId": bid, "message": "Import lancé. Suivez son avancement dans la liste des lots."}


# ---------------------------------------------------------------------------
# Évolution de l'ontologie et versions
# ---------------------------------------------------------------------------
@router.get("/admin/ontology/changes")
async def list_changes(status: str | None = None):
    return ontology_evolution.list_changes(status)


class FormalizeChange(BaseModel):
    proposal: str
    context: str | None = None


@router.post("/admin/ontology/changes/formalize")
async def formalize_change(req: FormalizeChange):
    try:
        return await ontology_evolution.formalize(req.proposal, req.context)
    except anthropic_client.AnthropicError as exc:
        raise HTTPException(502, str(exc)) from exc


class ChangeIn(BaseModel):
    proposal: str
    operations: list[dict]
    origin: str | None = None
    expert: str


@router.post("/admin/ontology/changes")
async def create_change(req: ChangeIn):
    try:
        return ontology_evolution.create_change(req.proposal, req.operations, req.origin or "manuel", req.expert)
    except ontology_evolution.ChangeError as exc:
        raise HTTPException(400, str(exc)) from exc


class ChangeDecision(BaseModel):
    expert: str
    notes: str | None = None


def _change_action(fn, cid: int, req: ChangeDecision, *extra):
    try:
        return fn(cid, req.expert.strip() or "expert", *extra)
    except ontology_evolution.ChangeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/admin/ontology/changes/{cid}/apply")
async def apply_change(cid: int, req: ChangeDecision):
    return _change_action(ontology_evolution.apply_change, cid, req, req.notes)


@router.post("/admin/ontology/changes/{cid}/reject")
async def reject_change(cid: int, req: ChangeDecision):
    return _change_action(ontology_evolution.reject_change, cid, req, req.notes)


@router.post("/admin/ontology/changes/{cid}/deliberate")
async def deliberate_change(cid: int, req: ChangeDecision):
    return _change_action(ontology_evolution.set_deliberation, cid, req)


@router.post("/admin/ontology/changes/{cid}/revert")
async def revert_change(cid: int, req: ChangeDecision):
    return _change_action(ontology_evolution.revert_change, cid, req)


@router.post("/admin/ontology/changes/{cid}/opinions")
async def change_opinion(cid: int, req: OpinionIn):
    db.execute("INSERT INTO opinions (change_id, expert, position, argument, created_at) VALUES (?,?,?,?,?)",
               (cid, req.expert, req.position, req.argument, db.now_iso()))
    journal.append("avis_depose", "evolution", cid, req.expert, {"position": req.position, "argument": req.argument})
    return db.fetch_all("SELECT * FROM opinions WHERE change_id = ? ORDER BY id", (cid,))


@router.get("/admin/ontology/versions")
async def versions():
    return ontology_evolution.list_versions()


@router.get("/admin/ontology/versions/{version}/download")
async def download_version(version: int):
    row = db.fetch_one("SELECT file FROM ontology_versions WHERE version = ?", (version,))
    if not row:
        raise HTTPException(404, "Version introuvable.")
    return FileResponse(ONTOLOGY_VERSIONS_DIR / row["file"], filename=row["file"])


@router.post("/admin/ontology/versions/{version}/restore")
async def restore(version: int, req: ChangeDecision):
    try:
        return {"ok": True, "version": ontology_evolution.restore_version(version, req.expert.strip() or "expert")}
    except ontology_evolution.ChangeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/admin/enrichments.ttl")
async def enrichments_ttl():
    if not ENRICHMENTS_TTL.exists():
        enrichments.rebuild()
    return PlainTextResponse(ENRICHMENTS_TTL.read_text(encoding="utf-8"), media_type="text/turtle")


# ---------------------------------------------------------------------------
# Journal épistémique
# ---------------------------------------------------------------------------
@router.get("/admin/journal")
async def get_journal(subject_type: str | None = None, subject_id: str | None = None, event_type: str | None = None,
                      limit: int = 200, before: int | None = None):
    return journal.history(subject_type, subject_id, event_type, min(limit, 1000), before)


@router.get("/admin/journal.jsonl")
async def export_journal():
    rows = db.fetch_all("SELECT * FROM journal ORDER BY id", json_fields=("payload",))
    return PlainTextResponse("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), media_type="application/x-ndjson")
