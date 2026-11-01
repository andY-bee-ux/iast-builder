"""Toponymie coutumière : instanciation de référence d'IAST-Builder (volet 3 de l'évaluation), sur un corpus
fictif. Variantes graphiques, noms partagés par un quartier et un cours d'eau, lieux sacrés à diffusion restreinte."""
import time
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "profiles" / "toponymie" / "donnees" / "toponymie_illustrative.json"


def test_instance_and_import(client, llm):
    assert client.get("/health").json()["profile"] == "toponymie"
    r = client.post("/api/admin/connectors/import", files={"file": ("c.json", DATA.read_bytes(), "application/json")},
                    data={"preset": "toponymie_illustrative"})
    bid = r.json()["batchId"]
    for _ in range(100):
        batch = next(b for b in client.get("/api/admin/connectors/batches").json() if b["id"] == bid)
        if batch["status"] != "running":
            break
        time.sleep(0.1)
    rep = batch["report"]
    assert rep["records"] == 20 and rep["variants"] == 25
    assert sorted(p["forme"] for p in rep["polysemies"]) == ["Ndé Kou", "Nkoum Fé"]
    rows = client.get(f"/api/admin/assertions?status=all&batch={bid}&limit=5000").json()
    sacred = [a for a in rows if (a.get("scope") or {}).get("type_de_lieu") == "bois sacré"]
    assert len(sacred) == 12 and all(a["access_level"] == "restreint" and a["verdict"] == "en_tension" for a in sacred)
    client.post(f"/api/admin/batches/{bid}/validate-conforming", json={"expert": "Équipe"})
    for a in sacred:
        client.post(f"/api/admin/assertions/{a['id']}/decide", json={"decision": "validated", "expert": "Équipe", "access_level": "restreint"})
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:none]\nRéponse.")
    client.post("/api/chat", json={"messages": [{"role": "user", "content": "Parle-moi de Ka'a Lé et de Nkoum Fé."}]})
    dossier = llm.calls[-1]["system"].split("CONNAISSANCES VALIDÉES")[1]
    assert "Ka'a Lé" not in dossier and "Nkoum Fé (quartier)" in dossier and "Nkoum Fé (cours d'eau)" in dossier
    assert client.get("/api/admin/audit").json()["conforms"]
