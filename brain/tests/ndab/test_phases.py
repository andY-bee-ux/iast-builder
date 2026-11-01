"""Tests de bout en bout des trois phases, dans l'ordre d'usage réel.

Lancer : cd brain && python -m pytest -q
"""
import json
from pathlib import Path

REPERTOIRE = Path(__file__).resolve().parent / "fixtures" / "repertoire_extrait.json"


# ---------------------------------------------------------------------------
# Démarrage et migration
# ---------------------------------------------------------------------------
def test_health_and_initial_version(client):
    h = client.get("/health").json()
    assert h["ok"] and h["ontologyFormat"] == ".json"
    assert h["ontologyVersion"] == 1


def test_journal_is_append_only(client):
    from app import db
    import sqlite3
    import pytest

    with pytest.raises(sqlite3.DatabaseError):
        db.execute("DELETE FROM journal")
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("UPDATE journal SET actor = 'x'")


# ---------------------------------------------------------------------------
# Phase 1 : signaux, questions d'investigation, lissage
# ---------------------------------------------------------------------------
def test_chat_signal_creates_question_and_citations_are_stripped(client, llm):
    llm.queue.append(
        "[EMOTION:pensif]\n"
        "[SIGNAL:contradiction|Dans la chefferie X, quel Ndab reçoit une fille dans cette configuration ?|"
        "Dans la chefferie X, le Ndab N2 est attribué aux filles dans cette configuration.]\n"
        "C'est le nom qu'une fille reçoit de la famille de son père [[R1]]. "
        "Votre nom vient de Bangangté. [[REP:BGT_16]] Je transmets votre témoignage aux experts [[ZZZ]]. "
        "Voulez-vous savoir d'où viennent ces informations ?"
    )
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Chez nous à X les filles reçoivent N2."}],
                                        "clientId": "navigateur-1"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "[[" not in data["text"] and "[SIGNAL" not in data["text"]
    assert data["emotion"] == "pensif"
    ids = {s["id"] for s in data["sources"]}
    assert {"R1", "REP:BGT_16"} <= ids and "ZZZ" not in ids
    assert data["signal"]["type"] == "contradiction"
    # Le prompt contient bien le dossier, la charte et le protocole de balises.
    system = llm.calls[-1]["system"]
    assert "DOSSIER DE RÉPONSE" in system and "RESTITUTION" in system and "[SIGNAL:" in system


def test_similar_signals_are_grouped_and_prioritized(client, llm):
    llm.queue.append(
        "[EMOTION:pensif]\n[SIGNAL:contradiction|Dans la chefferie X, quel Ndab reçoit une fille dans cette configuration ?|none]\nRéponse."
    )
    client.post("/api/chat", json={"messages": [{"role": "user", "content": "Ma grand-mère dit N2."}], "clientId": "navigateur-2"})
    qs = client.get("/api/admin/questions").json()
    assert len(qs) == 1
    assert qs[0]["occurrences"] == 2 and qs[0]["distinct_clients"] == 2
    assert qs[0]["priority"] == 3 + 2 + 2 * 2


def test_legacy_memory_tag_creates_contribution(client, llm):
    llm.queue.append("[EMOTION:joyeux]\n[MEMORY:Le Ndab N9 est attesté à Bazou.]\nMerci, ce sera examiné.")
    data = client.post("/api/chat", json={"messages": [{"role": "user", "content": "N9 existe à Bazou."}]}).json()
    assert data["memoryQueued"] is True
    contribs = client.get("/api/admin/contributions").json()
    assert any(c["origin"] == "agent" and "N9" in c["content"] for c in contribs)


def test_question_validation_requires_confirmation_on_tension(client):
    qid = client.get("/api/admin/questions").json()[0]["id"]
    # Un garçon ne reçoit pas de Ndab ngon là' (R2) : tension, confirmation requise.
    bad = {"subject": "N2", "subject_class": "Ndab", "predicate": "estDeType", "object": "NdabNgonLa",
           "object_class": "TypeDeNdab", "scope": {"chefferie": "X", "sexe": "masculin"}}
    r = client.post(f"/api/admin/questions/{qid}/decide", json={"outcome": "validated", "expert": "Expert A", "assertions": [bad]})
    assert r.status_code == 409
    assert r.json()["tensions"][0]["details"]["rules"][0]["rule"] == "R2"
    good = {**bad, "scope": {"chefferie": "X", "sexe": "feminin"}}
    r = client.post(f"/api/admin/questions/{qid}/decide", json={"outcome": "validated", "expert": "Expert A",
                                                                  "notes": "Usage attesté à X", "assertions": [good]})
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["status"] == "validated" and q["assertions"][0]["status"] == "validated"


def test_validated_knowledge_enters_next_dossier(client, llm):
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:none]\nÀ X, les filles peuvent recevoir N2 [[E1]].")
    data = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Et le Ndab N2 à X ?"}]}).json()
    assert any(s["id"] == "E1" for s in data["sources"])
    assert "Connaissance validée" in data["sources"][0]["label"]
    assert "[E1]" in llm.calls[-1]["system"]


# ---------------------------------------------------------------------------
# Phase 2 : validation formelle et extraction guidée
# ---------------------------------------------------------------------------
def test_verdicts(client):
    from app import validation

    ok, _ = validation.evaluate({"subject": "Gooun Test", "subject_class": "Ndab", "predicate": "estDeType",
                                 "object": "NdabNgonLa", "object_class": "TypeDeNdab", "scope": {}})
    assert ok == "conforme"
    v, d = validation.evaluate({"subject": "Gooun Test", "predicate": "aPourSurnom", "object": "x", "scope": {}})
    assert v == "hors_ontologie" and d["term"]["term"] == "aPourSurnom"
    # SHACL : le sujet de estDeType doit être un Ndab ; une chefferie ne convient pas.
    v, d = validation.evaluate({"subject": "Bangangté", "subject_class": "Chefferie", "predicate": "estDeType",
                                "object": "NdabNgonLa", "object_class": "TypeDeNdab", "scope": {}})
    assert v == "en_tension" and d["violations"]
    # Contradiction avec une connaissance validée (types disjoints, portées recouvrantes).
    v, d = validation.evaluate({"subject": "N2", "subject_class": "Ndab", "predicate": "estDeType",
                                "object": "NdabDeMekat", "object_class": "TypeDeNdab", "scope": {"chefferie": "X"}})
    assert v == "en_tension" and d["contradictions"]
    # Portée disjointe : pas de contradiction.
    v, _ = validation.evaluate({"subject": "N2", "subject_class": "Ndab", "predicate": "estDeType",
                                "object": "NdabDeMekat", "object_class": "TypeDeNdab", "scope": {"chefferie": "Bazou"}})
    assert v == "conforme"


def test_document_extraction(client, llm):
    import time

    text = ("Au cours de l'entretien, l'informateur précise que le nom Gooun Essai est un Ndab ngon là' "
            "de la chefferie de Bangangté. Il parle aussi du Ndab de circonstance, donné lors d'un événement.")
    files = {"file": ("entretien.txt", text.encode(), "text/plain")}
    doc_id = client.post("/api/documents", files=files, data={"submittedBy": "enquêteur"}).json()["id"]
    assert client.post(f"/api/admin/documents/{doc_id}/review", json={"decision": "approved"}).status_code == 200
    llm.queue.append({
        "assertions": [
            {"subject": "Gooun Essai", "subject_class": "Ndab", "predicate": "estDeType", "object": "NdabNgonLa",
             "object_class": "TypeDeNdab", "scope": {"chefferie": "Bangangté"},
             "citation": "le nom Gooun Essai est un Ndab ngon là'", "confidence": 0.9},
            {"subject": "Inventé", "predicate": "estDeType", "object": "NdabNgonLa", "citation": "phrase absente du texte"},
        ],
        "hors_ontologie": [{"term": "Ndab de circonstance", "citation": "Ndab de circonstance",
                            "justification": "catégorie non modélisée"}],
    })
    assert client.post(f"/api/admin/documents/{doc_id}/extract").status_code == 200
    for _ in range(50):
        d = client.get(f"/api/admin/documents/{doc_id}").json()
        if d["assertionExtraction"] in ("done", "failed"):
            break
        time.sleep(0.1)
    report = json.loads(d["assertionExtractionDetail"])
    assert report["created"] == 1 and report["irrecevables"] == 1 and report["hors_ontologie"] == 1
    pending = client.get("/api/admin/assertions?source=document").json()
    verdicts = sorted(a["verdict"] for a in pending)
    assert verdicts == ["conforme", "hors_ontologie"]


# ---------------------------------------------------------------------------
# Phase 3 : connecteurs, évolution de l'ontologie, versions
# ---------------------------------------------------------------------------
def test_connector_import_detects_variants_and_homonyms(client):
    import time

    files = {"file": ("repertoire.json", REPERTOIRE.read_bytes(), "application/json")}
    r = client.post("/api/admin/connectors/import", files=files, data={"preset": "repertoire_bangangte"})
    assert r.status_code == 200, r.text
    bid = r.json()["batchId"]
    for _ in range(100):
        batch = next(b for b in client.get("/api/admin/connectors/batches").json() if b["id"] == bid)
        if batch["status"] != "running":
            break
        time.sleep(0.1)
    assert batch["status"] == "done", batch
    rep = batch["report"]
    assert rep["assertions"] > 0 and rep["variants"] >= 1
    assert any("tchou" in h["forme"].lower() and h["classes"] == ["GroupeLignager", "Ndab"] for h in rep["homonymes"]), rep["homonymes"]
    res = client.post(f"/api/admin/batches/{bid}/validate-conforming", json={"expert": "Expert B"}).json()
    assert res["validated"] > 0
    ttl = client.get("/api/admin/enrichments.ttl").text
    noms = {n for b in json.loads(REPERTOIRE.read_text(encoding="utf-8"))["entrees"]
            for k in ("liste_hypothese_ndab_ngon_la", "liste_hypothese_ndab_mekat") for n in b[k]}
    assert "prov:wasAttributedTo" in ttl and any(n in ttl for n in noms)


def test_duplicate_import_refused_then_cancel_and_reimport(client):
    """Un même fichier importé deux fois avec la même correspondance est refusé ; annuler le lot
    rejette ses connaissances en attente et retire celles validées, puis autorise un nouvel import."""
    import time

    files = {"file": ("repertoire.json", REPERTOIRE.read_bytes(), "application/json")}
    r = client.post("/api/admin/connectors/import", files=files, data={"preset": "repertoire_bangangte"})
    assert r.status_code == 409 and "déjà été importé" in r.json()["detail"]
    first = min(b["id"] for b in client.get("/api/admin/connectors/batches").json())
    assert client.post(f"/api/admin/batches/{first}/cancel", json={"expert": ""}).status_code == 400
    res = client.post(f"/api/admin/batches/{first}/cancel", json={"expert": "Expert B", "motif": "essai"}).json()
    assert res["retirees"] > 0 and res["rejetees"] >= 0
    remaining = client.get(f"/api/admin/assertions?status=validated&batch={first}&limit=5000").json()
    assert remaining == []
    batch = next(b for b in client.get("/api/admin/connectors/batches").json() if b["id"] == first)
    assert batch["status"] == "annule"
    r = client.post("/api/admin/connectors/import", files=files, data={"preset": "repertoire_bangangte"})
    assert r.status_code == 200
    bid = r.json()["batchId"]
    for _ in range(100):
        if next(b for b in client.get("/api/admin/connectors/batches").json() if b["id"] == bid)["status"] != "running":
            break
        time.sleep(0.1)
    ev = client.get("/api/admin/journal?event_type=lot_annule").json()
    assert ev and ev[0]["payload"]["motif"] == "essai"


def test_deduplicate_keeps_oldest(client):
    body = {"subject": "Zdoublon", "subject_class": "Ndab", "predicate": "estSynonymeDe", "object": "Zdoublon2",
            "object_class": "Ndab", "scope": {}, "expert": "Expert B"}
    ids = [client.post("/api/admin/assertions", json=body).json()["id"] for _ in range(3)]
    res = client.post("/api/admin/assertions/deduplicate", json={"expert": "Expert B"}).json()
    assert res["rejetees"] >= 2
    statuses = [client.get(f"/api/admin/assertions/{i}").json()["status"] for i in ids]
    assert statuses[0] == "pending" and statuses[1:] == ["rejected", "rejected"]


def test_ontology_evolution_apply_and_revert(client, llm):
    llm.queue.append({"operations": [
        {"op": "add_class", "id": "NdabDeCirconstance", "label": "Ndab de circonstance", "parent": "TypeDeNdab",
         "definition": "Ndab donné en lien avec un événement survenu autour de la naissance."}
    ], "commentaire": "Nouvelle catégorie."})
    f = client.post("/api/admin/ontology/changes/formalize", json={"proposal": "Ajouter le Ndab de circonstance."}).json()
    assert not f["problems"] and "Ajouter la catégorie « Ndab de circonstance »" in f["paraphrase"]
    change = client.post("/api/admin/ontology/changes", json={"proposal": "Ajouter le Ndab de circonstance.",
                                                             "operations": f["operations"], "expert": "Expert A"}).json()
    applied = client.post(f"/api/admin/ontology/changes/{change['id']}/apply", json={"expert": "Expert A"}).json()
    assert applied["status"] == "applied" and applied["applied_version"] == 2
    vocab = client.get("/api/admin/vocabulary").json()
    assert "NdabDeCirconstance" in vocab["classes"]
    reverted = client.post(f"/api/admin/ontology/changes/{change['id']}/revert", json={"expert": "Expert A"}).json()
    assert reverted["status"] == "reverted"
    assert "NdabDeCirconstance" not in client.get("/api/admin/vocabulary").json()["classes"]
    assert [v["version"] for v in client.get("/api/admin/ontology/versions").json()][:2] == [3, 2]


def test_invalid_operation_is_explained(client):
    r = client.post("/api/admin/ontology/changes", json={"proposal": "x", "expert": "E", "operations": [
        {"op": "add_class", "id": "Nouvelle", "parent": "Inexistante", "definition": "d"}]})
    assert r.status_code == 400 and "n'existe pas" in r.json()["detail"]


def test_owl_import_and_evolution(client):
    owl = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">
  <owl:Ontology rdf:about="http://example.org/ndab"/>
  <owl:Class rdf:about="http://example.org/ndab#Ndab"><rdfs:label>Ndab</rdfs:label></owl:Class>
  <owl:Class rdf:about="http://example.org/ndab#TypeDeNdab"/>
  <owl:ObjectProperty rdf:about="http://example.org/ndab#estDeType">
    <rdfs:domain rdf:resource="http://example.org/ndab#Ndab"/><rdfs:range rdf:resource="http://example.org/ndab#TypeDeNdab"/>
  </owl:ObjectProperty>
</rdf:RDF>"""
    r = client.post("/api/admin/ontology/upload", files={"file": ("ndab.owl", owl.encode(), "application/rdf+xml")})
    assert r.status_code == 200 and r.json()["format"] == "owl"
    change = client.post("/api/admin/ontology/changes", json={"proposal": "p", "expert": "E", "operations": [
        {"op": "add_class", "id": "NdabDeMekat", "parent": "TypeDeNdab", "definition": "Ndab du lignage maternel."}]}).json()
    applied = client.post(f"/api/admin/ontology/changes/{change['id']}/apply", json={"expert": "E"}).json()
    assert applied["status"] == "applied"
    content = client.get("/api/admin/ontology").json()["content"]
    assert "NdabDeMekat" in content and "Ndab du lignage maternel" in content
    # Retour à la version JSON d'origine.
    assert client.post("/api/admin/ontology/versions/1/restore", json={"expert": "E"}).status_code == 200
    assert client.get("/health").json()["ontologyFormat"] == ".json"


def test_journal_traces_everything(client):
    # Le journal compte désormais plusieurs milliers d'événements (deux imports complets et une annulation) :
    # on vérifie chaque type par une requête filtrée plutôt que dans les derniers événements.
    events = {t for t in ("signal_recu", "question_creee", "question_regroupee", "question_decidee", "assertion_proposee",
                          "verdict_formel", "assertion_decidee", "evolution_appliquee", "version_ontologie",
                          "retour_version", "import_connecteur", "extraction_terminee", "lot_annule")
              if client.get(f"/api/admin/journal?event_type={t}&limit=1").json()}
    for expected in ("signal_recu", "question_creee", "question_regroupee", "question_decidee", "assertion_proposee",
                     "verdict_formel", "assertion_decidee", "evolution_appliquee", "version_ontologie",
                     "retour_version", "import_connecteur", "extraction_terminee"):
        assert expected in events, expected


def test_audit_conforms_to_metamodel(client):
    """Après l'ensemble du circuit, l'état du système respecte les invariants d'exécution IE1 à IE4."""
    report = client.get("/api/admin/audit").json()
    assert report["conforms"], report["violations"]
    assert client.get("/api/profile").json()["agent"] == "YobaKoko"


def test_collecte_can_be_suspended_and_restored(client, llm):
    """Collecte communautaire réglable : active par défaut pour YobaKoko, suspendue et rétablie par un expert."""
    assert client.get("/api/profile").json()["collecte"] == {"temoignages": True, "formulaire": True, "lacunes": True}
    assert client.put("/api/admin/collecte", json={"mode": "temoignages", "actif": False, "expert": ""}).status_code == 400
    r = client.put("/api/admin/collecte", json={"mode": "temoignages", "actif": False, "expert": "Expert A",
                                                 "motif": "Avis de consentement en cours de révision"})
    assert r.status_code == 200 and r.json()["etat"]["temoignages"] is False

    # L'agent ne promet plus de transmission et ne sollicite pas le savoir de l'usager.
    questions_before = len(client.get("/api/admin/questions?status=all").json())
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:nouveaute|Le nom X est-il attesté ?|Le nom X serait attesté.]\nMerci.")
    data = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Je sais que X vient de ce lignage."}]}).json()
    system = llm.calls[-1]["system"]
    assert "sera transmis aux experts" not in system and "recueil des témoignages est suspendu" in system
    assert data["signal"] is None
    assert len(client.get("/api/admin/questions?status=all").json()) == questions_before
    ev = client.get("/api/admin/journal?event_type=signal_non_transmis").json()
    assert ev and ev[0]["payload"] == {"type": "nouveaute"}

    # Les lacunes restent signalées aux experts.
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:lacune|Quel est le Ndab Y ?|none]\nJe ne sais pas.")
    data = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Quel est le Ndab Y ?"}]}).json()
    assert data["signal"] and data["signal"]["type"] == "lacune"

    # Formulaire fermé : contributions et documents refusés.
    client.put("/api/admin/collecte", json={"mode": "formulaire", "actif": False, "expert": "Expert A"})
    assert client.post("/api/contribute", json={"type": "autre", "content": "Un témoignage."}).status_code == 403
    assert client.post("/api/documents", files={"file": ("a.txt", b"texte", "text/plain")}).status_code == 403
    assert client.get("/api/profile").json()["collecte"]["formulaire"] is False

    # Rétablissement, et trace de chaque changement dans le journal.
    for mode in ("temoignages", "formulaire"):
        client.put("/api/admin/collecte", json={"mode": mode, "actif": True, "expert": "Expert A"})
    assert client.get("/api/admin/collecte").json()["etat"] == {"temoignages": True, "formulaire": True, "lacunes": True}
    changes = client.get("/api/admin/journal?event_type=reglage_collecte").json()
    assert len(changes) == 4 and all(e["actor"] == "expert:Expert A" for e in changes)
    assert any(e["payload"].get("motif") == "Avis de consentement en cours de révision" for e in changes)


def test_ndab_uncertainty_phrase(client, llm):
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:none]\nRéponse.")
    client.post("/api/chat", json={"messages": [{"role": "user", "content": "Bonjour"}]})
    assert "les anciens et les chercheurs du projet sont encore en train de le vérifier" in llm.calls[-1]["system"]
