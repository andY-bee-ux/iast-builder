"""evaluation/instanciation_reference.py — instanciation de référence de la toponymie coutumière (volet 3).

Réalisée par l'équipe du projet avec le corpus et les consignes remis aux participants, elle fournit un
point de comparaison pour l'étude. Le script démarre l'instance « toponymie » sur un répertoire neuf
(modèle de langage et embeddings simulés), importe le corpus, valide les connaissances conformes, lance
l'audit, vérifie que les lieux sacrés n'atteignent pas l'agent, et relève les mesures du protocole.

Usage (depuis brain/) : python -m evaluation.instanciation_reference
Sortie : evaluation/resultats/instanciation_reference.json
"""
from __future__ import annotations

import json, os, sys, tempfile, time
from collections import Counter
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
_tmp = Path(tempfile.mkdtemp(prefix="iab-topo-"))
os.environ.update(YOBAKOKO_PROFILE="toponymie", YOBAKOKO_DATA_DIR=str(_tmp / "data"), YOBAKOKO_UPLOAD_DIR=str(_tmp / "up"),
                  ANTHROPIC_API_KEY="test", INTERNAL_SECRET="")
sys.path.insert(0, str(BRAIN)); sys.path.insert(0, str(BRAIN / "tests"))
import logging; logging.disable(logging.INFO)  # noqa: E401,E702

from doublures import FakeLLM, fake_embed  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import anthropic_client, vectorstore  # noqa: E402
from app.main import app  # noqa: E402
from evaluation.etude.carnet import engine_fingerprint, profile_metrics  # noqa: E402


def _commit() -> str | None:
    """Version du dépôt utilisée, pour rejouer l'instanciation sur le même moteur."""
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=BRAIN, capture_output=True, text=True,
                              timeout=5).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def main():
    llm = FakeLLM(); vectorstore.embed = fake_embed; anthropic_client.messages = llm
    corpus = BRAIN / "profiles" / "toponymie" / "donnees" / "toponymie_illustrative.json"
    # Empreinte du moteur au début de l'exécution ; comparée à celle de la fin, elle établit que
    # l'instanciation n'a demandé aucune modification du code, quelle que soit la version du moteur.
    before = engine_fingerprint()
    result = {"profil": profile_metrics("toponymie"), "moteur": before, "commit": _commit()}
    with TestClient(app) as c:
        r = c.post("/api/admin/connectors/import", files={"file": ("corpus.json", corpus.read_bytes(), "application/json")},
                   data={"preset": "toponymie_illustrative"})
        bid = r.json()["batchId"]
        for _ in range(100):
            batch = next(b for b in c.get("/api/admin/connectors/batches").json() if b["id"] == bid)
            if batch["status"] != "running":
                break
            time.sleep(0.1)
        rep = batch["report"]
        rows = c.get(f"/api/admin/assertions?status=all&batch={bid}&limit=5000").json()
        sacred = [a for a in rows if (a.get("scope") or {}).get("type_de_lieu") == "bois sacré"]
        validated = c.post(f"/api/admin/batches/{bid}/validate-conforming", json={"expert": "Équipe du projet"}).json()["validated"]
        # Les connaissances en conflit (lieux sacrés, règle TP1) sont validées une à une par l'autorité, au niveau restreint.
        for a in rows:
            if a["verdict"] == "en_tension":
                c.post(f"/api/admin/assertions/{a['id']}/decide",
                       json={"decision": "validated", "expert": "Équipe du projet", "notes": "Lieu sacré, diffusion restreinte", "access_level": "restreint"})
        llm.queue.append("[EMOTION:neutre]\n[SIGNAL:none]\nRéponse.")
        c.post("/api/chat", json={"messages": [{"role": "user", "content": "Parle-moi de Ka'a Lé, Ka'a Mbe et Ka'a Tsi, et de Nkoum Fé."}]})
        dossier = llm.calls[-1]["system"].split("CONNAISSANCES VALIDÉES")[1] if "CONNAISSANCES VALIDÉES" in llm.calls[-1]["system"] else ""
        audit = c.get("/api/admin/audit").json()
        result["import"] = {
            "enregistrements": rep["records"], "connaissances": rep["assertions"], "variantes_proposees": rep["variants"],
            "variantes": sorted({tuple(sorted((a["subject"], a["object"]))) for a in rows if a["predicate"] == "estVarianteDe"}),
            "polysemies": rep.get("polysemies", []), "homonymes": rep.get("homonymes", []),
            "verdicts": dict(Counter(a["verdict"] for a in rows)),
            "niveaux_acces": dict(Counter(a["access_level"] for a in rows)),
            "connaissances_lieux_sacres": len(sacred), "validees_groupees": validated,
        }
        result["controles"] = {
            "lieux_sacres_absents_du_dossier": not any(n in dossier for n in ("Ka'a Lé", "Ka'a Mbe", "Ka'a Tsi")),
            "nkoum_fe_present_dans_le_dossier": "Nkoum Fé (quartier)" in dossier and "Nkoum Fé (cours d'eau)" in dossier,
            "audit_conforme": audit["conforms"],
        }
    verifs = [json.loads(l) for l in (BRAIN / "evaluation" / "resultats" / "instanciation_reference_verifications.jsonl").read_text().splitlines() if l.strip()]
    result["verifications"] = {"passages": len(verifs), "avant_conformite": next((i + 1 for i, v in enumerate(verifs) if v["conforme"]), None),
                               "problemes": [p for v in verifs for p in v["problemes"]]}
    after = engine_fingerprint()
    result["moteur_fin"] = after
    result["moteur_inchange"] = before["sha256"] == after["sha256"]
    out = BRAIN / "evaluation" / "resultats" / "instanciation_reference.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
