"""evaluation/proprietes.py — volet 2 : les garanties tiennent-elles à l'exécution ?

Tests fondés sur les propriétés. Le moteur, instancié par un profil, reçoit des séquences
d'opérations tirées au hasard (création de connaissances, décisions, retraits, évolutions de
l'ontologie et retours arrière, réglages de la collecte, conversations simulées). Après chaque
conversation et à intervalles réguliers, on vérifie :

  P1  aucune connaissance non validée n'entre dans le dossier de réponse (IE-C1) ;
  P2  aucune connaissance d'un niveau d'accès supérieur à celui de l'agent n'y entre (IE-C1) ;
  P3  un signal relevant d'un mode de collecte suspendu n'est pas transmis, et ne crée aucune
      question ; un signal relevant d'un mode actif est transmis (IE-C3) ;
  P4  aucune phrase enfreignant une contrainte de sûreté n'atteint l'usager ;
  P5  l'état du système respecte les invariants d'exécution IE1 à IE4 (audit SHACL) ;
  P6  aucun événement du journal ne peut être modifié ni supprimé (IE-C2).

Le modèle de langage et les embeddings sont simulés : on éprouve le moteur, non le modèle.

Usage (depuis brain/) : python -m evaluation.proprietes <profil> [sequences] [operations] [graine]
Sortie : evaluation/resultats/proprietes_<profil>.json
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import string
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
PROFILE = sys.argv[1] if len(sys.argv) > 1 else "ndab"
N_SEQ = int(sys.argv[2]) if len(sys.argv) > 2 else 40
N_OPS = int(sys.argv[3]) if len(sys.argv) > 3 else 50
SEED = int(sys.argv[4]) if len(sys.argv) > 4 else 2026

_tmp = Path(tempfile.mkdtemp(prefix=f"iab-prop-{PROFILE}-"))
os.environ.update(YOBAKOKO_PROFILE=PROFILE, YOBAKOKO_DATA_DIR=str(_tmp / "data"), YOBAKOKO_UPLOAD_DIR=str(_tmp / "up"),
                  ANTHROPIC_API_KEY="test", INTERNAL_SECRET="")
sys.path.insert(0, str(BRAIN)); sys.path.insert(0, str(BRAIN / "tests"))

import logging  # noqa: E402
logging.disable(logging.INFO)

from doublures import FakeLLM, fake_embed  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import anthropic_client, vectorstore  # noqa: E402
from app.config import DB_PATH  # noqa: E402
from app.main import app  # noqa: E402
from app.profile import active as active_profile  # noqa: E402

DOSAGE_SENTENCES = ["Prenez 2 cuillères 3 fois par jour pendant une semaine.", "Buvez 250 ml de cette préparation.",
                    "Je vous conseille d'en boire le matin.", "La posologie est d'une tasse."]
SIGNALS = ["lacune", "ambiguite", "nouveaute", "contradiction"]


def token(rng: random.Random) -> str:
    return "Zq" + "".join(rng.choice(string.ascii_lowercase + string.digits) for _ in range(7))


def run():
    rng = random.Random(SEED)
    llm = FakeLLM()
    vectorstore.embed = fake_embed
    anthropic_client.messages = llm
    stats = Counter()
    violations: list[str] = []
    started = time.time()

    with TestClient(app) as c:
        profile = active_profile()
        allowed_levels = set(profile.allowed_levels_for_agent())
        levels = profile.access_levels
        dims = [d["cle"] for d in profile.raw.get("portee", [])]
        vocab = c.get("/api/admin/vocabulary").json()
        props = [{"id": k, **v} for k, v in vocab["objectProperties"].items() if v.get("domain") and v.get("range")]
        special_values = ["enfant", "femme enceinte", "secret de lignée", "masculin", "maternelle", "paternelle"]
        assertions: dict[str, dict] = {}   # jeton -> {id, status, level}
        applied_changes: list[int] = []

        def create():
            p = rng.choice(props)
            subj, obj = token(rng), token(rng)
            scope = {d: rng.choice(special_values + [token(rng)]) for d in rng.sample(dims, k=min(len(dims), rng.randint(0, 2)))}
            body = {"subject": subj, "subject_class": p["domain"], "predicate": p["id"], "object": obj,
                    "object_class": p["range"], "scope": scope, "expert": "Expert"}
            r = c.post("/api/admin/assertions", json=body)
            if r.status_code == 200:
                a = r.json()
                assertions[subj] = {"id": a["id"], "status": "pending", "level": a.get("access_level", "public"), "obj": obj}
                stats["creation"] += 1

        def decide():
            pend = [t for t, a in assertions.items() if a["status"] in ("pending", "deliberation")]
            if not pend:
                return
            t = rng.choice(pend)
            decision = rng.choices(["validated", "rejected", "deliberation"], weights=[6, 2, 1])[0]
            body = {"decision": decision, "expert": "Expert"}
            if decision == "validated" and rng.random() < 0.3:
                body["access_level"] = rng.choice(levels)
            r = c.post(f"/api/admin/assertions/{assertions[t]['id']}/decide", json=body)
            if r.status_code == 200:
                a = r.json()
                assertions[t]["status"] = a["status"]
                assertions[t]["level"] = a.get("access_level", assertions[t]["level"])
                stats["decision"] += 1

        def retire():
            val = [t for t, a in assertions.items() if a["status"] == "validated"]
            if val:
                t = rng.choice(val)
                if c.post(f"/api/admin/assertions/{assertions[t]['id']}/retire", json={"expert": "Expert"}).status_code == 200:
                    assertions[t]["status"] = "retired"; stats["retrait"] += 1

        def evolve():
            if applied_changes and rng.random() < 0.3:
                cid = applied_changes.pop()
                if c.post(f"/api/admin/ontology/changes/{cid}/revert", json={"expert": "Expert"}).status_code == 200:
                    stats["retour_arriere"] += 1
                return
            cls = "Classe" + token(rng).capitalize()
            ch = c.post("/api/admin/ontology/changes", json={"proposal": "Ajout d'une notion.", "origin": "question", "expert": "Expert",
                                                             "operations": [{"op": "add_class", "id": cls, "label": cls, "definition": "Notion ajoutée."}]})
            if ch.status_code == 200 and c.post(f"/api/admin/ontology/changes/{ch.json()['id']}/apply", json={"expert": "Expert"}).status_code == 200:
                applied_changes.append(ch.json()["id"]); stats["evolution"] += 1

        def toggle():
            mode = rng.choice(["temoignages", "formulaire", "lacunes"])
            c.put("/api/admin/collecte", json={"mode": mode, "actif": rng.random() < 0.6, "expert": "Expert"})
            stats["reglage_collecte"] += 1

        def chat():
            sample = rng.sample(list(assertions), k=min(6, len(assertions))) if assertions else []
            message = "Que sait-on de " + ", ".join(sample) + " ?"
            sig = rng.choice(SIGNALS)
            body_text = "Réponse fondée sur le dossier [[ONT]]."
            dosage = rng.random() < 0.4
            if dosage:
                body_text += " " + rng.choice(DOSAGE_SENTENCES)
            llm.queue.append(f"[EMOTION:neutre]\n[SIGNAL:{sig}|Question {token(rng)} ?|none]\n{body_text}")
            collecte = c.get("/api/admin/collecte").json()["etat"]
            q_before = len(c.get("/api/admin/questions?status=all").json())
            data = c.post("/api/chat", json={"messages": [{"role": "user", "content": message}]}).json()
            system = llm.calls[-1]["system"]
            stats["conversation"] += 1
            for t in sample:
                a = assertions[t]
                present = t in system
                if a["status"] != "validated" and present:
                    violations.append(f"P1 : connaissance {a['status']} {t} dans le dossier")
                if a["status"] == "validated" and a["level"] not in allowed_levels and present:
                    violations.append(f"P2 : connaissance de niveau {a['level']} {t} dans le dossier")
                if a["status"] == "validated" and a["level"] in allowed_levels and present:
                    stats["controle_positif_dossier"] += 1
                stats["controles_dossier"] += 1
            mode = {"nouveaute": "temoignages", "contradiction": "temoignages"}.get(sig, "lacunes")
            q_after = len(c.get("/api/admin/questions?status=all").json())
            if not collecte[mode] and (data.get("signal") is not None or q_after != q_before):
                violations.append(f"P3 : signal {sig} transmis alors que le mode {mode} est suspendu")
            if collecte[mode] and data.get("signal") is None:
                violations.append(f"P3 : signal {sig} non transmis alors que le mode {mode} est actif")
            stats["controles_collecte"] += 1
            if profile.safety_patterns():
                for cid, pat in profile.safety_patterns():
                    if pat.search(data["text"]):
                        violations.append(f"P4 : contrainte {cid} enfreinte dans la réponse")
                stats["controles_surete"] += 1
                stats["reponses_avec_posologie_simulee"] += int(dosage)

        def audit():
            rep = c.get("/api/admin/audit").json()
            stats["audits"] += 1
            if not rep["conforms"]:
                violations.extend(f"P5 : {v}" for v in rep["violations"])
            conn = sqlite3.connect(DB_PATH)
            for sql in ("UPDATE journal SET actor = 'pirate' WHERE id = (SELECT MIN(id) FROM journal)",
                        "DELETE FROM journal WHERE id = (SELECT MIN(id) FROM journal)"):
                try:
                    conn.execute(sql); conn.commit()
                    violations.append(f"P6 : opération acceptée sur le journal : {sql.split()[0]}")
                except sqlite3.DatabaseError:
                    stats["tentatives_journal_refusees"] += 1
            conn.close()

        ops = [(create, 30), (decide, 25), (retire, 4), (evolve, 4), (toggle, 7), (chat, 30)]
        fns, weights = zip(*ops)
        for _seq in range(N_SEQ):
            for _ in range(N_OPS):
                rng.choices(fns, weights=weights)[0]()
            audit()

    result = {"profil": PROFILE, "graine": SEED, "sequences": N_SEQ, "operations_par_sequence": N_OPS,
              "duree_s": round(time.time() - started, 1), "operations": dict(stats),
              "violations": violations, "nombre_violations": len(violations)}
    out = BRAIN / "evaluation" / "resultats" / f"proprietes_{PROFILE}_{SEED}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:2500])


if __name__ == "__main__":
    run()
