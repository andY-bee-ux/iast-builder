"""app/profile_check.py — conformité d'un profil de domaine au métamodèle IAST-Builder.

Deux familles de vérifications :

1. Invariants de profil (IP1 à IP7). Le profil est traduit en graphe RDF, comme instance
   du métamodèle (metamodele/iast-builder-metamodele.ttl), puis validé par les formes SHACL de
   metamodele/iast-builder-invariants.ttl.
2. Cohérence avec l'ontologie du domaine. Les termes que le profil mobilise doivent exister
   dans l'ontologie initiale : prédicats et objets des règles contrôlées et des règles
   d'accès, classe et relations de variante, dimensions de portée citées par les règles.

Usage : python -m app.profile_check [identifiant du profil]
Le service refuse de démarrer avec un profil non conforme (app/main.py).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import rdflib
from rdflib import RDF, Literal, Namespace, URIRef
from rdflib.namespace import XSD

from .profile import BRAIN_DIR, Profile, load_profile

IAB = Namespace("http://iast.uqam.ca/iast-builder#")
METAMODEL_DIR = BRAIN_DIR.parent / "metamodele"
if not METAMODEL_DIR.exists():                      # installation où le métamodèle est rangé dans brain/
    METAMODEL_DIR = BRAIN_DIR / "metamodele"

# Composants neuronaux du moteur : modèles pré-entraînés utilisés comme opérateurs (IP7).
NEURAL_COMPONENTS = ["GrandModeleDeLangage", "ModeleDEmbeddings"]


def profile_graph(p: Profile) -> rdflib.Graph:
    """Traduit un profil en instance du métamodèle."""
    g = rdflib.Graph()
    base = Namespace(f"http://iast.uqam.ca/iast-builder/profil/{p.id}/")
    prof = base["profil"]
    g.add((prof, RDF.type, IAB.ProfilDeDomaine))
    onto = base["ontologie"]
    g.add((onto, RDF.type, IAB.OntologieDeDomaine))
    g.add((prof, IAB.utiliseOntologie, onto))
    onto_decl = p.raw.get("ontologie", {})
    origins = {"terrain": IAB.origineTerrain, "documentaire": IAB.origineDocumentaire, "mixte": IAB.origineMixte}
    if onto_decl.get("origine"):
        g.add((onto, IAB.origine, origins.get(onto_decl["origine"], IAB[f"origineInconnue_{onto_decl['origine']}"])))
    for ref in onto_decl.get("corpus", []):
        g.add((onto, IAB.corpusDeReference, Literal(ref)))
    if p.raw.get("autorite"):
        auth = base["autorite"]
        g.add((auth, RDF.type, IAB.AutoriteDeValidation))
        g.add((auth, IAB.description, Literal(p.raw["autorite"])))
        g.add((prof, IAB.sousAutorite, auth))
    for d in p.raw.get("portee", []):
        node = base[f"portee/{d['cle']}"]
        g.add((node, RDF.type, IAB.DimensionDePortee))
        g.add((prof, IAB.declareDimension, node))
    for i, r in enumerate(p.raw.get("regles", [])):
        node = base[f"regle/{i}"]
        g.add((node, RDF.type, IAB.RegleControlee))
        g.add((prof, IAB.declareRegle, node))
        if r.get("id"):
            g.add((node, IAB.identifiant, Literal(r["id"])))
        if r.get("description"):
            g.add((node, IAB.description, Literal(r["description"])))
    acces = p.raw.get("acces", {})
    for n in acces.get("niveaux", []):
        node = base[f"niveau/{n['id']}"]
        g.add((node, RDF.type, IAB.NiveauDAcces))
        g.add((node, IAB.rang, Literal(n.get("rang", 0), datatype=XSD.integer)))
        g.add((prof, IAB.declareNiveau, node))
    if acces.get("niveau_diffusion_agent"):
        g.add((prof, IAB.niveauDiffusionAgent, base[f"niveau/{acces['niveau_diffusion_agent']}"]))
    for i, r in enumerate(acces.get("regles", [])):
        node = base[f"regle-acces/{i}"]
        g.add((node, RDF.type, IAB.RegleDAcces))
        g.add((prof, IAB.declareRegleDAcces, node))
        for key, prop in (("id", IAB.identifiant), ("description", IAB.description)):
            if r.get(key):
                g.add((node, prop, Literal(r[key])))
        g.add((node, IAB.attribueNiveau, base[f"niveau/{r.get('niveau')}"]))
    surete = p.raw.get("surete", {})
    g.add((prof, IAB.niveauDeRisque, IAB.risqueEleve if surete.get("risque") == "eleve" else IAB.risqueFaible))
    for c in surete.get("contraintes", []):
        node = base[f"surete/{c.get('id', 'x')}"]
        g.add((node, RDF.type, IAB.ContrainteDeSurete))
        g.add((prof, IAB.declareContrainte, node))
        for key, prop in (("id", IAB.identifiant), ("description", IAB.description)):
            if c.get(key):
                g.add((node, prop, Literal(c[key])))
        for m in c.get("motifs", []):
            g.add((node, IAB.motif, Literal(m)))
    collecte = p.raw.get("collecte", {})
    for key, prop in (("temoignages", IAB.recueilTemoignagesParDefaut), ("formulaire", IAB.formulaireParDefaut),
                      ("lacunes", IAB.signalementLacunesParDefaut)):
        if isinstance(collecte.get(key), bool):
            g.add((prof, prop, Literal(collecte[key])))
    for comp in NEURAL_COMPONENTS:
        node = IAB[comp]
        g.add((node, RDF.type, IAB.ComposantNeuronal))
        g.add((node, IAB.sansEtat, Literal(True)))
        g.add((onto, IAB.gouverne, node))
    return g


def check_invariants(p: Profile) -> list[str]:
    from pyshacl import validate

    shapes = rdflib.Graph()
    shapes.parse(str(METAMODEL_DIR / "iast-builder-invariants.ttl"), format="turtle")
    conforms, results, _ = validate(profile_graph(p), shacl_graph=shapes, inference="none", advanced=True)
    if conforms:
        return []
    SH = Namespace("http://www.w3.org/ns/shacl#")
    return sorted({str(m) for m in results.objects(None, SH.resultMessage)})


def check_consistency(p: Profile) -> list[str]:
    """Cohérence entre les termes du profil et l'ontologie initiale du domaine."""
    problems: list[str] = []
    if not p.ontology_file.exists():
        return [f"Fichier d'ontologie introuvable : {p.ontology_file.name}"]
    data = json.loads(p.ontology_file.read_text(encoding="utf-8")) if p.ontology_file.suffix == ".json" else None
    if data is None:
        return problems   # ontologie OWL : cohérence vérifiée au chargement par le moteur
    # Les identifiants de l'ontologie deviennent des IRI : ni espace, ni apostrophe, ni accent. Sans ce
    # contrôle, un identifiant comme « cours d'eau » passe la vérification et fait échouer le moteur à la
    # première validation. Le libellé, lui, peut s'écrire librement.
    for kind, items in (("classe", data.get("classes", [])), ("relation", data.get("proprietes_objet", [])),
                        ("attribut", data.get("proprietes_donnees", [])), ("individu", data.get("individus_seed", []))):
        for item in items:
            ident = item.get("id", "")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.\-]*", ident):
                problems.append(f"Identifiant de {kind} invalide : « {ident} ». Un identifiant ne contient ni espace, ni "
                                f"apostrophe, ni accent (par exemple CoursDEau) ; le texte lisible va dans le libellé.")
    classes = {c["id"] for c in data.get("classes", [])}
    predicates = {x["id"] for x in data.get("proprietes_objet", []) + data.get("proprietes_donnees", [])} | {"estUn"}
    individuals = {i["id"] for i in data.get("individus_seed", [])}
    dims = {d["cle"] for d in p.raw.get("portee", [])}
    levels = set(p.access_levels)

    def check_condition(label: str, cond: dict):
        for pred in cond.get("predicat", []):
            if pred not in predicates:
                problems.append(f"{label} : prédicat « {pred} » absent de l'ontologie.")
        for cls in cond.get("classe_sujet", []):
            if cls not in classes:
                problems.append(f"{label} : classe « {cls} » absente de l'ontologie.")
        for dim in cond.get("portee", {}):
            if dim not in dims:
                problems.append(f"{label} : dimension de portée « {dim} » non déclarée par le profil.")

    for r in p.raw.get("regles", []):
        check_condition(f"Règle {r.get('id')}", r.get("si", {}))
    for r in p.raw.get("acces", {}).get("regles", []):
        check_condition(f"Règle d'accès {r.get('id')}", r.get("si", {}))
        if r.get("niveau") not in levels:
            problems.append(f"Règle d'accès {r.get('id')} : niveau « {r.get('niveau')} » non déclaré.")
    if p.default_access not in levels:
        problems.append(f"Niveau par défaut « {p.default_access} » non déclaré.")
    v = p.variant
    if v.get("classe") and v["classe"] not in classes:
        problems.append(f"Variantes : classe « {v['classe']} » absente de l'ontologie.")
    for key in ("predicat", "designation"):
        if v.get(key) and v[key] not in predicates:
            problems.append(f"Variantes : relation « {v[key]} » absente de l'ontologie.")
    for mapping in sorted(p.mappings_dir.glob("*.json")) if p.mappings_dir.exists() else []:
        m = json.loads(mapping.read_text(encoding="utf-8"))
        for s in m.get("subjects", []):
            if s.get("class") and s["class"] not in classes:
                problems.append(f"Correspondance {mapping.name} : classe « {s['class']} » absente de l'ontologie.")
            for f in s.get("facts", []):
                if f["predicate"] not in predicates:
                    problems.append(f"Correspondance {mapping.name} : prédicat « {f['predicate']} » absent de l'ontologie.")
                if f.get("object_class") and f["object_class"] not in classes:
                    problems.append(f"Correspondance {mapping.name} : classe « {f['object_class']} » absente de l'ontologie.")
                if "value" in f and f.get("object_class") and f["value"] not in classes | individuals:
                    problems.append(f"Correspondance {mapping.name} : valeur « {f['value']} » absente de l'ontologie.")
        for key in m.get("scope", {}):
            if key not in dims:
                problems.append(f"Correspondance {mapping.name} : dimension de portée « {key} » non déclarée.")
    return problems


def check(profile_id: str | None = None) -> list[str]:
    p = load_profile(profile_id)
    return check_invariants(p) + check_consistency(p)


if __name__ == "__main__":
    pid = sys.argv[1] if len(sys.argv) > 1 else None
    issues = check(pid)
    name = pid or "actif"
    if issues:
        print(f"Profil {name} non conforme au métamodèle IAST-Builder :")
        for i in issues:
            print(f"  - {i}")
        sys.exit(1)
    print(f"Profil {name} conforme au métamodèle IAST-Builder (invariants IP1 à IP8, cohérence avec l'ontologie).")
