"""app/connectors.py — connecteurs de données structurées et semi-structurées (phase 3).

Principe : plus la source est structurée, plus l'extraction est déterministe.
Un fichier CSV ou JSON est converti en assertions candidates par une
CORRESPONDANCE DÉCLARATIVE (mapping), sans modèle de langage. Seuls les champs
de texte libre déclarés dans « text_fields » passent par l'extraction guidée
(phase 2), ce qui couvre les données semi-structurées.

Format d'une correspondance (JSON) ; les correspondances prédéfinies d'un domaine se trouvent dans
profiles/<id>/correspondances/ :

{
  "connector": "json" | "csv",
  "records_path": "entrees",           # JSON : chemin (a.b.c) vers la liste des enregistrements
  "delimiter": ",",                    # CSV : séparateur
  "subjects": [                        # une ou plusieurs familles de sujets par enregistrement
    {
      "field": "nom"  |  "from_list": "liste_de_noms",   # un sujet, ou un sujet par élément de liste
      "class": "Ndab",
      "facts": [                       # assertions produites pour chaque sujet
        {"predicate": "estDeType", "value": "NdabNgonLa", "object_class": "TypeDeNdab"},
        {"predicate": "provientDuLignage", "field": "lignage_paternel_labels", "object_class": "GroupeLignager"},
        {"predicate": "nomNdab", "field": "graphie", "literal": true}
      ]
    }
  ],
  "scope": {"chefferie": {"field": "chefferie"}, "statut": {"value": "hypothèse, à valider"}},
  "confidence": 0.6,
  "text_fields": ["commentaire"],      # champs libres soumis à l'extraction guidée
  "detect_variants": true              # proposer les variantes graphiques (estSynonymeDe)
}

Un champ dont la valeur est une liste produit une assertion par élément.
Chaque assertion garde sa provenance exacte : lot, numéro d'enregistrement, champ.

Détection des variantes : les sujets d'un même lot et d'une même classe dont les
formes normalisées se ressemblent au-delà de VARIANT_SIMILARITY donnent lieu à
une assertion candidate « estSynonymeDe », soumise aux experts. Le bilan d'import
signale aussi les HOMONYMES : une même forme normalisée employée pour des entités
de classes différentes (ex. un nom de personne et un libellé de lignage).
"""
from __future__ import annotations

import csv
import io
import json
import logging
from itertools import combinations
from pathlib import Path

from . import assertions, db, extraction, journal
from .config import VARIANT_SIMILARITY
from .profile import active as active_profile
from .text_utils import normalize_form, similarity

log = logging.getLogger("yobakoko.connectors")


def mappings_dir() -> Path:
    """Les correspondances prédéfinies appartiennent au profil de domaine (profiles/<id>/correspondances/)."""
    return active_profile().mappings_dir


class MappingError(ValueError):
    pass


def list_presets() -> list[dict]:
    out = []
    for p in sorted(mappings_dir().glob("*.json")):
        m = json.loads(p.read_text(encoding="utf-8"))
        out.append({"name": p.stem, "description": m.get("description", ""), "connector": m.get("connector")})
    return out


def load_preset(name: str) -> dict:
    p = mappings_dir() / f"{Path(name).stem}.json"
    if not p.exists():
        raise MappingError(f"Correspondance « {name} » introuvable.")
    return json.loads(p.read_text(encoding="utf-8"))


def _get_path(obj, path: str | None):
    if not path:
        return obj
    for part in path.split("."):
        obj = obj.get(part) if isinstance(obj, dict) else None
    return obj


def _values(record: dict, spec: dict) -> list[str]:
    """Valeur(s) désignée(s) par une spécification {"field"|"column"|"from_list"|"value"|"template"}.
    Un gabarit compose un identifiant à partir de plusieurs champs, par exemple "{lieu} ({type})" pour
    distinguer un quartier et un cours d'eau qui portent le même nom ; il ne produit rien si l'un des
    champs manque."""
    if "template" in spec:
        import string
        fields = [f for _, f, _, _ in string.Formatter().parse(spec["template"]) if f]
        if any(record.get(f) in (None, "", []) or isinstance(record.get(f), list) for f in fields):
            return []
        return [spec["template"].format(**{f: str(record[f]).strip() for f in fields})]
    if "value" in spec:
        raw = spec["value"]
    else:
        key = spec.get("field") or spec.get("column") or spec.get("from_list")
        raw = record.get(key)
    items = raw if isinstance(raw, list) else [raw]
    return [str(x).strip() for x in items if x not in (None, "") and str(x).strip() not in ("", "???")]


def parse_records(content: bytes, mapping: dict) -> list[dict]:
    kind = mapping.get("connector")
    if kind == "csv":
        text = content.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text), delimiter=mapping.get("delimiter", ",")))
    if kind == "json":
        data = json.loads(content.decode("utf-8"))
        records = _get_path(data, mapping.get("records_path"))
        if not isinstance(records, list):
            raise MappingError("Le chemin « records_path » ne désigne pas une liste d'enregistrements.")
        return records
    raise MappingError("Le champ « connector » doit valoir « csv » ou « json ».")


def check_mapping(mapping: dict) -> None:
    if not mapping.get("subjects"):
        raise MappingError("La correspondance doit déclarer au moins un sujet (« subjects »).")
    for s in mapping["subjects"]:
        if not any(k in s for k in ("field", "column", "from_list", "template")):
            raise MappingError("Chaque sujet doit indiquer « field », « column », « from_list » ou « template ».")
        for f in s.get("facts", []):
            if "predicate" not in f or not any(k in f for k in ("field", "column", "value", "template")):
                raise MappingError("Chaque fait doit indiquer « predicate » et « field », « column », « value » ou « template ».")


def import_fingerprint(content: bytes, mapping: dict) -> str:
    """Empreinte d'un import : le même fichier importé avec la même correspondance."""
    import hashlib
    h = hashlib.sha256(content)
    h.update(json.dumps(mapping, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()


def find_duplicate_batch(fingerprint: str) -> dict | None:
    """Lot déjà importé avec la même empreinte, hors lots annulés ou en échec."""
    return db.fetch_one("SELECT id, filename, created_at, status FROM import_batches WHERE file_hash = ? "
                        "AND status NOT IN ('annule', 'failed') ORDER BY id LIMIT 1", (fingerprint,))


def create_batch(connector: str, filename: str, mapping: dict, fingerprint: str | None = None) -> int:
    bid = db.execute(
        "INSERT INTO import_batches (connector, filename, mapping, status, created_at, file_hash) VALUES (?,?,?,?,?,?)",
        (connector, filename, db.dumps(mapping), "running", db.now_iso(), fingerprint),
    )
    journal.append("import_connecteur", "lot", bid, "connecteur", {"filename": filename, "connector": connector})
    return bid


async def run_import(batch_id: int, content: bytes, mapping: dict) -> None:
    """Tâche de fond : applique la correspondance et crée les assertions candidates."""
    report = {"records": 0, "assertions": 0, "variants": 0, "homonymes": [], "extraction": None, "errors": []}
    try:
        records = parse_records(content, mapping)
        report["records"] = len(records)
        scope_spec = mapping.get("scope", {})
        confidence = mapping.get("confidence")
        # classe -> {forme normalisée -> ensemble des formes brutes rencontrées}
        seen_subjects: dict[str, dict[str, set[str]]] = {}
        for idx, rec in enumerate(records):
            scope = {}
            for key, spec in scope_spec.items():
                vals = _values(rec, spec)
                if vals:
                    scope[key] = vals if len(vals) > 1 else vals[0]
            for sspec in mapping["subjects"]:
                cls = sspec.get("class")
                for subject in _values(rec, sspec):
                    seen_subjects.setdefault(cls or "", {}).setdefault(normalize_form(subject), set()).add(subject)
                    for fact in sspec.get("facts", []):
                        for obj in _values(rec, fact):
                            field_name = fact.get("field") or fact.get("column") or "valeur fixe"
                            assertions.create({
                                "subject": subject, "subject_class": cls, "predicate": fact["predicate"], "object": obj,
                                "object_class": fact.get("object_class"), "object_is_literal": bool(fact.get("literal")),
                                "scope": scope, "source_type": "connecteur",
                                "source_ref": f"lot:{batch_id}#enregistrement{idx}.{field_name}",
                                "citation": f"{subject} → {obj}", "method": "correspondance",
                                "confidence": confidence, "batch_id": batch_id,
                            }, "connecteur")
                            report["assertions"] += 1
            for tf in mapping.get("text_fields", []):
                text = rec.get(tf)
                if isinstance(text, str) and text.strip():
                    sub = await extraction.extract_from_text(text, "connecteur", f"lot:{batch_id}#enregistrement{idx}.{tf}",
                                                             "connecteur", batch_id=batch_id)
                    report["extraction"] = report["extraction"] or {"created": 0, "irrecevables": 0}
                    report["extraction"]["created"] += sub["created"]
                    report["extraction"]["irrecevables"] += sub["irrecevables"]

        if mapping.get("detect_variants"):
            report["variants"] = _propose_variants(batch_id, seen_subjects)
        report["homonymes"] = _homonyms(seen_subjects)
        report["polysemies"] = _polysemies(batch_id)
        db.execute("UPDATE import_batches SET status = 'done', n_records = ?, n_assertions = ?, report = ? WHERE id = ?",
                   (report["records"], report["assertions"] + report["variants"], db.dumps(report), batch_id))
    except Exception as exc:  # noqa: BLE001 — l'échec doit être visible dans le panneau
        log.exception("Import du lot %s impossible", batch_id)
        report["errors"].append(str(exc))
        db.execute("UPDATE import_batches SET status = 'failed', report = ? WHERE id = ?", (db.dumps(report), batch_id))
    journal.append("import_termine", "lot", batch_id, "connecteur", report)


def _propose_variants(batch_id: int, seen: dict[str, dict[str, set[str]]]) -> int:
    """Propose la relation de variante du profil (par exemple estSynonymeDe entre deux Ndab,
    estVarianteDe entre deux noms vernaculaires) entre formes voisines de la classe variable."""
    variant = active_profile().variant
    var_class, var_pred = variant.get("classe"), variant.get("predicat")
    if not var_class or not var_pred:
        return 0
    count = 0
    for cls, forms in seen.items():
        if cls != var_class:
            continue
        # Toutes les formes brutes distinctes sont comparées, y compris celles qui ne diffèrent
        # que par un accent ou une majuscule (« ndolé » et « ndole »), dont la similarité vaut 1.
        raw_forms = sorted({f for group in forms.values() for f in group})
        for a, b in combinations(raw_forms, 2):
            score = similarity(a, b)
            if score >= VARIANT_SIMILARITY:
                assertions.create({
                    "subject": a, "subject_class": var_class, "predicate": var_pred, "object": b, "object_class": var_class,
                    "scope": {}, "source_type": "connecteur", "source_ref": f"lot:{batch_id}#variantes",
                    "citation": f"similarité des formes : {score:.2f}", "method": "detection_variantes",
                    "confidence": round(score, 2), "batch_id": batch_id,
                }, "connecteur")
                count += 1
    return count


def _homonyms(seen: dict[str, dict[str, set[str]]]) -> list[dict]:
    """Formes normalisées employées pour des entités de classes différentes."""
    by_form: dict[str, dict[str, str]] = {}
    for cls, forms in seen.items():
        for norm, raws in forms.items():
            by_form.setdefault(norm, {})[cls or "?"] = sorted(raws)[0]
    return [{"forme": next(iter(v.values())), "classes": sorted(v), "formes": v} for v in by_form.values() if len(v) > 1]


def _polysemies(batch_id: int) -> list[dict]:
    """Formes qui désignent plusieurs entités distinctes par la relation de désignation du profil
    (par exemple un même nom vernaculaire appliqué à deux espèces). Signalées aux experts."""
    pred = active_profile().variant.get("designation")
    if not pred:
        return []
    rows = db.fetch_all("SELECT subject, object FROM assertions WHERE batch_id = ? AND predicate = ?", (batch_id, pred))
    by_form: dict[str, dict] = {}
    for r in rows:
        entry = by_form.setdefault(normalize_form(r["subject"]), {"forme": r["subject"], "entites": set()})
        entry["entites"].add(r["object"])
    return [{"forme": v["forme"], "entites": sorted(v["entites"])} for v in by_form.values() if len(v["entites"]) > 1]


def cancel_batch(batch_id: int, expert: str, motif: str | None = None) -> dict:
    """Annulation d'un lot (par exemple importé par erreur ou en double). Rien n'est effacé :
    les connaissances en attente du lot sont rejetées, celles déjà validées sont retirées, le lot
    est marqué annulé, et chaque décision est signée et journalisée."""
    batch = db.fetch_one("SELECT * FROM import_batches WHERE id = ?", (batch_id,))
    if not batch:
        raise ValueError(f"Lot inconnu : {batch_id}")
    if batch["status"] == "annule":
        raise ValueError(f"Le lot n° {batch_id} est déjà annulé.")
    if batch["status"] == "running":
        raise ValueError(f"Le lot n° {batch_id} est en cours d'import ; attendez la fin avant de l'annuler.")
    note = f"Annulation du lot {batch_id}" + (f" : {motif}" if motif else "")
    rejected = retired = 0
    for row in db.fetch_all("SELECT id, status FROM assertions WHERE batch_id = ?", (batch_id,)):
        if row["status"] in ("pending", "deliberation"):
            assertions.decide(row["id"], "rejected", expert, note); rejected += 1
        elif row["status"] == "validated":
            assertions.retire(row["id"], expert, note); retired += 1
    db.execute("UPDATE import_batches SET status = 'annule' WHERE id = ?", (batch_id,))
    journal.append("lot_annule", "lot", batch_id, f"expert:{expert}", {"motif": motif, "rejetees": rejected, "retirees": retired})
    return {"lot": batch_id, "rejetees": rejected, "retirees": retired}


def list_batches() -> list[dict]:
    return db.fetch_all("SELECT * FROM import_batches ORDER BY id DESC", json_fields=("mapping", "report"))
