"""app/audit.py — audit de l'état du système au regard des invariants d'exécution du métamodèle.

L'état courant (assertions, décisions, versions de l'ontologie, journal) est exporté en RDF,
comme instance du métamodèle IAST-Builder, puis validé par les formes SHACL IE1 à IE4 de
metamodele/iast-builder-invariants.ttl. Les invariants IE-C1 et IE-C2 (aucune assertion non validée
dans le dossier de réponse ; journal non modifiable) relèvent du comportement du moteur et
sont vérifiés par les tests.

Usage : python -m app.audit      (ou GET /api/admin/audit)
"""
from __future__ import annotations

import json

import rdflib
from rdflib import RDF, Literal, Namespace
from rdflib.namespace import XSD

from . import db
from .profile_check import METAMODEL_DIR, IAB

STATUS = {"pending": IAB.enAttente, "deliberation": IAB.enDeliberation, "validated": IAB.validee,
          "rejected": IAB.rejetee, "retired": IAB.retiree}
VERDICT = {"conforme": IAB.conforme, "en_tension": IAB.enTension, "hors_ontologie": IAB.horsOntologie}


def state_graph(journal_limit: int = 2000) -> rdflib.Graph:
    g = rdflib.Graph()
    X = Namespace("http://iast.uqam.ca/iast-builder/etat/")
    for a in db.fetch_all("SELECT * FROM assertions"):
        node = X[f"assertion/{a['id']}"]
        g.add((node, RDF.type, IAB.AssertionCandidate))
        if a["source_ref"]:
            g.add((node, IAB.reference, Literal(a["source_ref"])))
        if a["verdict"] in VERDICT:
            g.add((node, IAB.aPourVerdict, VERDICT[a["verdict"]]))
        g.add((node, IAB.aPourStatut, STATUS.get(a["status"], IAB.enAttente)))
        if a.get("access_level"):
            g.add((node, IAB.aPourNiveauDAcces, X[f"niveau/{a['access_level']}"]))
        if a["decided_by"] and a["status"] in {"validated", "retired"}:
            dec = X[f"decision/{a['id']}"]
            g.add((dec, RDF.type, IAB.Decision))
            g.add((dec, IAB.decidePar, X[f"expert/{a['decided_by']}"]))
            g.add((node, IAB.valideePar, dec))
    versions = db.fetch_all("SELECT * FROM ontology_versions ORDER BY version")
    for v in versions:
        node = X[f"version/{v['version']}"]
        g.add((node, RDF.type, IAB.VersionDOntologie))
        g.add((node, IAB.numero, Literal(v["version"], datatype=XSD.integer)))
        g.add((node, IAB.motifDeVersion, Literal(v["reason"])))
        if v["version"] > 1:
            g.add((node, IAB.versionPrecedente, X[f"version/{v['version'] - 1}"]))
    for e in db.fetch_all("SELECT * FROM journal ORDER BY id DESC LIMIT ?", (journal_limit,)):
        node = X[f"evenement/{e['id']}"]
        g.add((node, RDF.type, IAB.EvenementDeJournal))
        g.add((node, IAB.acteur, Literal(e["actor"])))
        g.add((node, IAB.typeDEvenement, Literal(e["event_type"])))
        if e["ontology_version"] is not None:
            g.add((node, IAB.sousVersion, X[f"version/{e['ontology_version']}"]))
    return g


def run() -> dict:
    from pyshacl import validate

    shapes = rdflib.Graph()
    shapes.parse(str(METAMODEL_DIR / "iast-builder-invariants.ttl"), format="turtle")
    g = state_graph()
    conforms, results, _ = validate(g, shacl_graph=shapes, inference="none", advanced=True)
    SH = Namespace("http://www.w3.org/ns/shacl#")
    messages = sorted({str(m) for m in results.objects(None, SH.resultMessage)})
    return {"conforms": conforms, "violations": messages, "triples": len(g)}


if __name__ == "__main__":
    db.init_db()
    print(json.dumps(run(), ensure_ascii=False, indent=2))
