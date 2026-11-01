"""AfriPharm : le moteur IAST-Builder, sans modification de code, instancié pour la pharmacopée
ouest-africaine à partir d'un corpus documentaire de référence.

Quatre cas éprouvent les points de variation du métamodèle :
- le baobab : noms dans plusieurs langues et pays, et un usage chez l'enfant appuyé par une
  étude clinique, qui déclenche néanmoins la règle d'examen renforcé (PH1) ;
- Acacia nilotica et Vernonia amygdalina : variantes graphiques de noms vernaculaires ;
- « doundaké » : un nom qui désigne deux espèces (polysémie) ;
- Ageratum conyzoides : précautions et contre-indications restituables, posologie conservée
  pour les experts mais jamais restituée ;
- Boscia senegalensis : une notion absente de l'ontologie (la reformulation d'une recette en
  phytomédicament), qui entre dans le modèle par une évolution décidée par les experts."""
import time
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "profiles" / "afripharm" / "donnees" / "pharmacopee_ouest_africaine.json"
STATE: dict = {}


def _import(client):
    files = {"file": ("pao.json", DATA.read_bytes(), "application/json")}
    bid = client.post("/api/admin/connectors/import", files=files, data={"preset": "pharmacopee_ouest_africaine"}).json()["batchId"]
    for _ in range(100):
        batch = next(b for b in client.get("/api/admin/connectors/batches").json() if b["id"] == bid)
        if batch["status"] != "running":
            return batch
        time.sleep(0.1)
    raise AssertionError("import non terminé")


def _rows(client, batch_id):
    return client.get(f"/api/admin/assertions?status=all&batch={batch_id}&limit=2000").json()


def test_documentary_ontology_installed(client):
    h = client.get("/health").json()
    assert h["profile"] == "afripharm" and h["ontologyVersion"] == 1
    p = client.get("/api/profile").json()
    assert p["agent"] == "AfriPharm" and p["risque"] == "eleve"
    vocab = client.get("/api/admin/vocabulary").json()
    assert {"Posologie", "ContreIndication", "Monographie", "EtudeClinique"} <= set(vocab["classes"])


def test_import_variants_polysemy_and_rules(client):
    batch = _import(client)
    assert batch["status"] == "done", batch
    STATE["batch"] = batch["id"]
    rep = batch["report"]
    rows = _rows(client, batch["id"])
    variants = {tuple(sorted((a["subject"], a["object"]))) for a in rows if a["predicate"] == "estVarianteDe"}
    assert ("ndole", "ndolé") in variants
    assert ("Gaoudi", "Gaudi") in variants
    # Deux transcriptions haoussa du même nom, sous le seuil de similarité : non rapprochées.
    assert ("Kouka", "Kuka") not in variants
    poly = {p["forme"]: p["entites"] for p in rep["polysemies"]}
    assert sorted(poly["doundaké"]) == ["Nauclea diderrichii", "Sarcocephalus latifolius"]
    # Un usage chez l'enfant, même appuyé par une étude clinique, appelle un examen renforcé.
    ada = [a for a in rows if a["subject"] == "U-ADA-1"]
    assert ada and all(a["verdict"] == "en_tension" for a in ada)
    assert ada[0]["verdict_details"]["rules"][0]["rule"] == "PH1"
    # La posologie est conservée, en diffusion restreinte ; le reste est destiné aux spécialistes.
    poso = [a for a in rows if a["predicate"] == "aPourPosologie"]
    assert poso and all(a["access_level"] == "restreint" for a in poso)
    assert all(a["access_level"] == "specialiste" for a in rows if a["predicate"] == "aPourPrecaution")
    client.post(f"/api/admin/batches/{batch['id']}/validate-conforming", json={"expert": "Comité"})


def test_posology_never_reaches_agent_but_precautions_do(client, llm):
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:none]\nRéponse.")
    client.post("/api/chat", json={"messages": [{"role": "user", "content": "Que sait-on d'Ageratum conyzoides ?"}]})
    dossier = llm.calls[-1]["system"].split("CONNAISSANCES VALIDÉES")[1]
    assert "Emploi avec prudence" in dossier and "Diabète" in dossier
    assert "Posologie documentée" not in dossier


def test_boscia_extends_the_ontology_through_expert_decision(client):
    # Le résumé JSDC-5 rapporte la reformulation d'une recette en phytomédicament : notion absente du modèle.
    a = client.post("/api/admin/assertions", json={
        "subject": "U-BOS-1", "subject_class": "UsageRapporte", "predicate": "estReformuleEn",
        "object": "Phytomédicament antidiabétique à base de Boscia senegalensis", "object_class": "Phytomedicament",
        "scope": {"region": "Est du Tchad", "preuve": "étude clinique", "source": "JSDC-5"}, "expert": "Comité"}).json()
    assert a["verdict"] == "hors_ontologie"
    change = client.post("/api/admin/ontology/changes", json={
        "proposal": "Ajouter la notion de phytomédicament, issu de la reformulation d'une recette traditionnelle.",
        "operations": [
            {"op": "add_class", "id": "Phytomedicament", "label": "Phytomédicament",
             "definition": "Médicament à base de plantes issu de la reformulation d'une recette traditionnelle."},
            {"op": "add_object_property", "id": "estReformuleEn", "domain": "UsageRapporte", "range": "Phytomedicament",
             "definition": "Phytomédicament issu de la reformulation d'un usage traditionnel."}],
        "origin": "question", "expert": "Comité"}).json()
    assert "phytomédicament" in change["paraphrase"].lower()
    applied = client.post(f"/api/admin/ontology/changes/{change['id']}/apply", json={"expert": "Comité"}).json()
    assert applied["applied_version"] == 2 and applied["reevaluated_assertions"] >= 1
    after = client.get(f"/api/admin/assertions/{a['id']}").json()
    assert after["verdict"] == "conforme"


def test_safety_filter_removes_dosage(client, llm):
    llm.queue.append(
        "[EMOTION:neutre]\n[SIGNAL:none]\n"
        "La pulpe du fruit du baobab entre dans une solution étudiée au Sénégal [[ONT]]. "
        "Prenez 2 cuillères 3 fois par jour pendant une semaine. "
        "Je vous conseille d'en boire le matin."
    )
    data = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Comment utiliser le baobab ?"}]}).json()
    assert "cuillères" not in data["text"] and "conseille" not in data["text"]
    assert "baobab" in data["text"] and "professionnel de santé" in data["text"]
    events = client.get("/api/admin/journal?event_type=controle_surete").json()
    assert events and set(events[0]["payload"]["contraintes"]) == {"posologie", "prescription"}


def test_domain_shape_binomial_name(client):
    from app import validation

    v, d = validation.evaluate({"subject": "Adansonia digitata", "subject_class": "Plante", "predicate": "nomScientifique",
                                "object": "adansonia", "object_is_literal": True, "scope": {}})
    assert v == "en_tension" and any("binominale" in m for m in d["violations"])


def test_audit_conforms(client):
    report = client.get("/api/admin/audit").json()
    assert report["conforms"], report["violations"]


def test_collecte_defaults_follow_the_profile(client, llm):
    """AfriPharm : recueil des témoignages et formulaire fermés par défaut (consentement préalable),
    signalement des lacunes actif."""
    c = client.get("/api/admin/collecte").json()
    assert c["defauts"] == {"temoignages": False, "formulaire": False, "lacunes": True}
    assert client.post("/api/contribute", json={"type": "autre", "content": "Une recette."}).status_code == 403
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:nouveaute|La plante X soigne-t-elle Y ?|X soignerait Y.]\nMerci.")
    data = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Ma grand-mère soigne Y avec X."}]}).json()
    assert data["signal"] is None
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:lacune|Quels usages de Z ?|none]\nAucune donnée.")
    data = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Et la plante Z ?"}]}).json()
    assert data["signal"]["type"] == "lacune"


def test_restitution_rules_and_malformed_citations(client, llm):
    """La charte demande de répondre pour chaque entité sans relancer à vide, avec la formule d'incertitude
    du profil ; les renvois mal écrits par le modèle ne sont jamais affichés."""
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:none]\n"
                     "Le nom « doundaké » désigne deux espèces. [[E1][E5]] Une autre phrase sur le baobab [E2].")
    data = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Que désigne doundaké ?"}]}).json()
    system = llm.calls[-1]["system"]
    assert "au lieu de demander laquelle intéresse la personne" in system
    assert "ce point n'a pas encore été validé par les experts du projet" in system and "anciens" not in system
    assert "[" not in data["text"] and "]" not in data["text"]
    assert "doundaké" in data["text"] and "baobab" in data["text"]


def test_repeated_question_is_not_new(client, llm):
    client.put("/api/admin/collecte", json={"mode": "lacunes", "actif": True, "expert": "Comité"})
    for expected in (True, False):
        llm.queue.append("[EMOTION:neutre]\n[SIGNAL:lacune|Quels usages sont rapportés pour Nauclea diderrichii ?|none]\nRien.")
        data = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Et Nauclea diderrichii ?"}]}).json()
        assert data["signal"]["nouvelle"] is expected


def test_personas_declared_by_profile(client, llm):
    p = client.get("/api/profile").json()
    assert [x["id"] for x in p["personnalites"]] == ["chercheur", "guide"] and p["personnalite_par_defaut"] == "chercheur"
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:none]\nRéponse.")
    client.post("/api/chat", json={"messages": [{"role": "user", "content": "Bonjour"}], "persona": "sage"})
    assert "spécialiste qui s'adresse à des pairs" in llm.calls[-1]["system"]   # « sage » n'existe pas ici : défaut du profil


def test_displayed_text_is_plain(client, llm):
    """Ni mise en forme Markdown ni renvoi au dossier dans le texte affiché ; la charte demande un texte simple."""
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:none]\n---\n\n### Deux espèces\n\n"
                     "Le nom « doundaké » désigne ***Nauclea diderrichii*** et *Sarcocephalus latifolius*. [[E1][E5]]\n\n"
                     "- **Sarcocephalus latifolius** est aussi appelé quinquina africain [E2].\n\n> Ce point reste à vérifier.\n\n---")
    data = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Que désigne doundaké ?"}]}).json()
    text = data["text"]
    for symbol in ("*", "#", "---", "[", "]", ">"):
        assert symbol not in text, (symbol, text)
    assert "Nauclea diderrichii" in text and "• Sarcocephalus latifolius est aussi appelé quinquina africain" in text
    assert "sans titres, pas de séparateurs" in llm.calls[-1]["system"] or "pas de titres, pas de séparateurs" in llm.calls[-1]["system"]


def test_conversational_style(client, llm):
    """Réponse courte, à la première personne, sans évoquer le dossier ; relance seulement s'il y a plus à dire."""
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:none]\nLe dossier confirme que ce nom désigne deux espèces. "
                     "Selon le dossier, la seconde est aussi appelée quinquina africain.")
    data = client.post("/api/chat", json={"messages": [{"role": "user", "content": "doundaké ?"}]}).json()
    system = llm.calls[-1]["system"]
    assert "deux à quatre phrases" in system and "Parle en ton nom" in system and "N'évoque jamais" in system
    assert "dossier" not in data["text"].lower() and data["text"].startswith("À ma connaissance")


def test_safety_never_leaves_a_question_without_answer(client, llm):
    """Une phrase banale commençant par « Pour votre… » n'est plus retirée ; si le contrôle retire tout le
    contenu informatif, la réponse l'explique au lieu de ne laisser qu'une relance ; les phrases retirées
    sont journalisées."""
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:none]\nPour votre question sur doundaké, voici ce que je sais. "
                     "Ce nom désigne deux espèces. Voulez-vous en savoir plus ?")
    data = client.post("/api/chat", json={"messages": [{"role": "user", "content": "doundaké ?"}]}).json()
    assert "Pour votre question sur doundaké" in data["text"] and "professionnel de santé" not in data["text"]
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:none]\nPrenez 2 cuillères 3 fois par jour. Voulez-vous en savoir plus ?")
    data = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Comment le prendre ?"}]}).json()
    assert data["text"].startswith("Je ne peux pas vous répondre sous cette forme") and "Voulez-vous" not in data["text"]
    ev = client.get("/api/admin/journal?event_type=controle_surete&limit=1").json()[0]["payload"]
    assert ev["reponse_videe"] is True and ev["phrases_retirees"] == ["Prenez 2 cuillères 3 fois par jour."]


def test_graph_selection_follows_names_and_usages(client, llm):
    """« baobab » mène à Adansonia digitata, à sa description et à ses usages ; un « oui » qui suit une réponse
    sur Sarcocephalus latifolius apporte l'usage complet (écorce, décoction, paludisme)."""
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:none]\nRéponse.")
    client.post("/api/chat", json={"messages": [{"role": "user", "content": "Quels usages du baobab sont rapportés ?"}]})
    dossier = llm.calls[-1]["system"].split("CONNAISSANCES VALIDÉES")[1]
    assert "Adansonia digitata" in dossier and "Bombacaceae" in dossier and "Paludisme" in dossier and "Nguta" in dossier
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:none]\nRéponse.")
    client.post("/api/chat", json={"messages": [
        {"role": "user", "content": "Quelles espèces désigne doundaké ?"},
        {"role": "assistant", "content": "Deux espèces : Nauclea diderrichii et Sarcocephalus latifolius. Voulez-vous ses usages ?"},
        {"role": "user", "content": "oui"}]})
    dossier = llm.calls[-1]["system"].split("CONNAISSANCES VALIDÉES")[1]
    assert "U-SAR-1" in dossier and "Ecorce" in dossier and "Decoction" in dossier and "Paludisme" in dossier
    assert "Posologie documentée" not in dossier


def test_current_question_comes_first_in_long_conversation(client, llm):
    """Un long échange sur d'autres espèces n'évince pas les connaissances de la question en cours."""
    history = []
    for q, a in [("Quelles espèces désigne doundaké ?", "Sarcocephalus latifolius et Nauclea diderrichii."),
                 ("Usages de Sarcocephalus latifolius ?", "Écorce en décoction contre le paludisme, quinquina africain."),
                 ("Et le baobab, Adansonia digitata ?", "Feuilles en décoction contre le paludisme ; noms Twèga, Sira, Zira, Kouka."),
                 ("Et Acacia nilotica ?", "Fruit en décoction contre la diarrhée ; noms Gaoudi, Gaudi, Bagana, Gonakier.")]:
        history += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    history.append({"role": "user", "content": "c'est quoi Ageratum conyzoides"})
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:none]\nRéponse.")
    client.post("/api/chat", json={"messages": history})
    system = llm.calls[-1]["system"]
    dossier = system.split("CONNAISSANCES VALIDÉES")[1]
    assert "U-AGE-1" in dossier and "Cataplasme" in dossier and "Plaies" in dossier
    assert "validée avec portée" not in system and "lot:" not in dossier
    assert "deux réponses de suite par la même tournure" in system


def test_reference_corpus_available_and_no_dossier_wording(client, llm):
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:none]\nJe n'ai pas d'information sur d'autres sources dans mon dossier actuel. "
                     "Vous pouvez consulter la Pharmacopée de l'Afrique de l'Ouest [[C1]].")
    data = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Quelles autres sources consulter ?"}]}).json()
    system = llm.calls[-1]["system"]
    assert "SOURCES DE RÉFÉRENCE DU DOMAINE" in system and "Eklu-Natey" in system and "OOAS (2020)" in system
    assert "dossier" not in data["text"].lower() and "[" not in data["text"]
    assert data["text"].startswith("Je n'ai pas d'information sur d'autres sources.")


def test_overview_for_general_questions(client, llm):
    """Une question générale sur le domaine dispose de la vue d'ensemble de la base : toutes les plantes
    documentées et leurs familles, et pas seulement celles de la conversation."""
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:none]\nRéponse.")
    client.post("/api/chat", json={"messages": [{"role": "user", "content": "Quelles familles de plantes connais-tu ?"}]})
    system = llm.calls[-1]["system"]
    overview = system.split("VUE D'ENSEMBLE DE CE QUE TU SAIS")[1].split("\n\n")[0]
    for expected in ("Adansonia digitata (Bombacaceae)", "Acacia nilotica (Mimosaceae)", "Ageratum conyzoides (Asteraceae)",
                     "Sarcocephalus latifolius (Rubiaceae)", "Nauclea diderrichii"):
        assert expected in overview, (expected, overview)
    assert "Une question\n   générale sur ton domaine" in system or "générale sur ton domaine" in system


def test_follow_up_relies_on_latest_exchange(client, llm):
    """Reproduit l'échange signalé : une réponse ancienne qui cite toute la base ne doit pas évincer
    le dernier échange quand la question renvoie au contexte (« Quels en sont les usages ? »)."""
    history = [
        {"role": "user", "content": "Quelles plantes connais-tu ?"},
        {"role": "assistant", "content": "Sept espèces : Acacia nilotica, Adansonia digitata, Ageratum conyzoides, "
                                         "Boscia senegalensis, Nauclea diderrichii, Sarcocephalus latifolius et Vernonia amygdalina."},
        {"role": "user", "content": "Quelles familles de plantes connais-tu ?"},
        {"role": "assistant", "content": "Mimosaceae, Bombacaceae, Asteraceae et Rubiaceae."},
        {"role": "user", "content": "Quelles espèces désigne le nom « doundaké » ?"},
        {"role": "assistant", "content": "Le nom « doundaké » désigne deux espèces : Sarcocephalus latifolius et Nauclea diderrichii."},
        {"role": "user", "content": "Quels en sont les usages ?"},
    ]
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:none]\nRéponse.")
    client.post("/api/chat", json={"messages": history})
    system = llm.calls[-1]["system"]
    dossier = system.split("CONNAISSANCES VALIDÉES")[1]
    assert "Ecorce" in dossier and "Decoction" in dossier and "Paludisme" in dossier
    assert "Familles représentées (4) : Asteraceae, Bombacaceae, Mimosaceae, Rubiaceae" in system
    assert "que tu n'as pas dites" in system


def test_shared_terms_do_not_pull_other_plants(client, llm):
    """Reproduit l'échange signalé : la mention de « l'OOAS (2013) » dans une réponse précédente ne ramène pas
    les usages des autres plantes ; l'usage de Sarcocephalus latifolius est présenté d'un seul tenant."""
    h = [
        {"role": "user", "content": "Quelles espèces désigne le nom « doundaké ?"},
        {"role": "assistant", "content": "Deux espèces : Sarcocephalus latifolius et Nauclea diderrichii. Voulez-vous les usages ?"},
        {"role": "user", "content": "oui"},
        {"role": "assistant", "content": "Pour Sarcocephalus latifolius, un usage est documenté par l'OOAS (2013) : une décoction d'écorce contre le paludisme."},
        {"role": "user", "content": "oui"},
        {"role": "assistant", "content": "Sarcocephalus latifolius est décrit dans la monographie de l'OOAS (2013) ; synonyme Nauclea latifolia."},
        {"role": "user", "content": "oui mais quel en est l'usage ?"}]
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:none]\nRéponse.")
    client.post("/api/chat", json={"messages": h})
    dossier = llm.calls[-1]["system"].split("CONNAISSANCES VALIDÉES")[1].split("\n\n")[0]
    assert "Ecorce" in dossier and "Decoction" in dossier and "Paludisme" in dossier
    for other in ("U-ACN-1", "U-AGE-1", "Adansonia digitata", "Sira"):
        assert other not in dossier, other


def test_missing_attribute_written_and_relaunch_rule(client, llm):
    llm.queue.append("[EMOTION:neutre]\n[SIGNAL:none]\nRéponse.")
    client.post("/api/chat", json={"messages": [{"role": "user", "content": "Quelles espèces désigne doundaké ?"}]})
    system = llm.calls[-1]["system"]
    assert "Nauclea diderrichii (famille non renseignée)" in system
    assert "se contente de\n   nommer des entités" in system or "se contente de nommer des entités" in system
