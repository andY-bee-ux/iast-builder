"""app/validation.py — validation formelle d'une assertion candidate (phase 2).

Chaque assertion reçoit l'un des trois verdicts de la conception :

- hors_ontologie : elle mobilise un prédicat ou une classe absents de l'ontologie,
                   ou l'extracteur a signalé un terme sans équivalent. Elle alimente
                   le circuit conceptuel (propositions d'évolution de l'ontologie).
- en_tension     : elle viole une contrainte (SHACL, règle d'attribution) ou
                   contredit une assertion validée dont la portée recouvre la sienne.
                   Elle n'est pas écartée : l'expert la voit avec ce qu'elle contredit.
- conforme       : aucune des situations précédentes.

Trois contrôles successifs :
1. vocabulaire  : prédicat et classes connus de l'ontologie active ;
2. SHACL        : formes dérivées automatiquement des domaines et co-domaines de
                  l'ontologie, complétées au besoin par les formes propres au domaine
                  (profiles/<id>/formes.ttl), vérifiées par pySHACL. La hiérarchie des classes est
                  prise en compte en ajoutant au graphe de données tous les ancêtres
                  des classes déclarées. L'inférence RDFS n'est volontairement PAS
                  activée : elle déduirait le type du sujet à partir du domaine du
                  prédicat, ce qui rendrait le contrôle de domaine sans effet ;
3. règles et contradictions : règles contrôlées déclarées par le profil de domaine
                  (profile.json, clé « regles ») et confrontation aux assertions déjà validées,
                  en tenant compte des disjonctions déclarées dans l'ontologie.

Chaque problème est accompagné d'une formulation « question du domaine », destinée
à l'expert, qui ne suppose aucune connaissance technique (conception, section 8.3).
"""
from __future__ import annotations

import logging

import rdflib
from rdflib import RDF, Literal, Namespace, URIRef

from . import db, paraphrase
from .ontology_loader import INSTANCE_OF, Vocabulary, iri_for_term, load_active, schema_graph
from .profile import active as active_profile
from .text_utils import normalize_form

log = logging.getLogger("yobakoko.validation")
SH = Namespace("http://www.w3.org/ns/shacl#")


# ---------------------------------------------------------------------------
# Portées
# ---------------------------------------------------------------------------
def _norm(v) -> set[str]:
    values = v if isinstance(v, list) else [v]
    return {normalize_form(str(x)) for x in values if x not in (None, "")}


def scopes_overlap(a: dict | None, b: dict | None) -> bool:
    """Deux portées se recouvrent si, pour chaque clé renseignée des deux côtés,
    leurs valeurs ont au moins un élément commun. Une portée vide recouvre tout.
    Les clés purement documentaires (source, statut, bloc) ne séparent pas deux portées."""
    a, b = a or {}, b or {}
    for key in set(a) & set(b):
        if key in {"source", "statut", "bloc", "informateur"}:
            continue
        va, vb = _norm(a[key]), _norm(b[key])
        if va and vb and not (va & vb):
            return False
    return True


# ---------------------------------------------------------------------------
# Formes SHACL dérivées de l'ontologie
# ---------------------------------------------------------------------------
_shapes_cache: dict = {"key": None, "shapes": None, "schema": None}


def build_shapes(vocab: Vocabulary) -> rdflib.Graph:
    """Pour chaque propriété d'objet : son domaine s'impose au sujet, son co-domaine
    à l'objet. Pour chaque propriété de données : son domaine s'impose au sujet."""
    g = rdflib.Graph()
    g.bind("sh", SH)
    for i, (pid, p) in enumerate({**vocab.object_properties, **vocab.data_properties}.items()):
        prop = URIRef(p["iri"])
        dom = p.get("domain")
        if dom in vocab.classes:
            shape = URIRef(f"urn:yobakoko:shape:{i}:domaine")
            g.add((shape, RDF.type, SH.NodeShape))
            g.add((shape, SH.targetSubjectsOf, prop))
            g.add((shape, SH["class"], URIRef(vocab.classes[dom]["iri"])))
            g.add((shape, SH.message, Literal(f"Le sujet de « {pid} » doit être un(e) {vocab.class_label(dom)}.", lang="fr")))
        rng = p.get("range")
        if rng in vocab.classes:
            shape = URIRef(f"urn:yobakoko:shape:{i}:portee")
            g.add((shape, RDF.type, SH.NodeShape))
            g.add((shape, SH.targetObjectsOf, prop))
            g.add((shape, SH["class"], URIRef(vocab.classes[rng]["iri"])))
            g.add((shape, SH.message, Literal(f"L'objet de « {pid} » doit être un(e) {vocab.class_label(rng)}.", lang="fr")))
    return g


def _shapes_for(vocab: Vocabulary) -> tuple[rdflib.Graph, rdflib.Graph]:
    key = id(vocab)
    if _shapes_cache["key"] != key:
        shapes = build_shapes(vocab)
        extra = active_profile().directory / "formes.ttl"
        if extra.exists():   # contraintes de données propres au domaine (point de variation)
            shapes.parse(str(extra), format="turtle")
        _shapes_cache.update(key=key, shapes=shapes, schema=schema_graph(vocab))
    return _shapes_cache["shapes"], _shapes_cache["schema"]


def _data_graph(a: dict, vocab: Vocabulary) -> rdflib.Graph:
    g = rdflib.Graph()

    def typed(node, cls):
        # Le nœud reçoit sa classe et tous ses ancêtres (fermeture de la hiérarchie).
        for c in vocab.class_ancestors(cls):
            g.add((node, RDF.type, URIRef(vocab.classes[c]["iri"])))

    s = iri_for_term(vocab, a["subject"], a.get("subject_class"))
    if a.get("subject_class") in vocab.classes:
        typed(s, a["subject_class"])
    if a["predicate"] == INSTANCE_OF:
        if a["object"] in vocab.classes:
            typed(s, a["object"])
        return g
    p = iri_for_term(vocab, a["predicate"])
    if a.get("object_is_literal"):
        g.add((s, p, Literal(a["object"])))
    else:
        o = iri_for_term(vocab, a["object"], a.get("object_class"))
        g.add((s, p, o))
        if a.get("object_class") in vocab.classes:
            typed(o, a["object_class"])
    return g


def shacl_violations(a: dict, vocab: Vocabulary) -> list[str]:
    from pyshacl import validate

    shapes, _schema = _shapes_for(vocab)
    if len(shapes) == 0:
        return []
    conforms, results_graph, _ = validate(_data_graph(a, vocab), shacl_graph=shapes, inference="none", abort_on_first=False)
    if conforms:
        return []
    return sorted({str(m) for m in results_graph.objects(None, SH.resultMessage)}) or ["Contrainte SHACL non respectée."]


# ---------------------------------------------------------------------------
# Règles contrôlées, déclarées par le profil de domaine
# ---------------------------------------------------------------------------
def rule_violations(a: dict) -> list[dict]:
    """Règles du profil dont la condition est satisfaite par l'assertion. Une règle contrôlée
    décrit une configuration qui appelle l'examen d'un expert (par exemple, pour les Ndab,
    un Ndab ngon là' attribué à un garçon ; pour une pharmacopée, un usage rapporté chez
    une population vulnérable)."""
    return [{"rule": r["id"], "text": r.get("description", r["id"])}
            for r, cond in active_profile().controlled_rules() if cond.matches(a)]


# ---------------------------------------------------------------------------
# Contradictions avec les assertions validées
# ---------------------------------------------------------------------------
def _disjoint(vocab: Vocabulary, c1: str, c2: str) -> bool:
    return any(c1 in grp and c2 in grp and c1 != c2 for grp in vocab.disjoint)


def contradictions(a: dict, vocab: Vocabulary) -> tuple[list[dict], int | None]:
    """Renvoie (contradictions, identifiant d'un doublon exact éventuel)."""
    found, duplicate = [], None
    rows = db.fetch_all(
        "SELECT * FROM assertions WHERE status = 'validated' AND predicate = ? AND id != ?",
        (a["predicate"], a.get("id") or -1), json_fields=("scope",),
    )
    key = normalize_form(a["subject"])
    for other in rows:
        if normalize_form(other["subject"]) != key or not scopes_overlap(a.get("scope"), other.get("scope")):
            continue
        if normalize_form(other["object"]) == normalize_form(a["object"]):
            duplicate = other["id"]
        elif a["predicate"] in {"estDeType", INSTANCE_OF} and _disjoint(vocab, a["object"], other["object"]):
            found.append({"assertion_id": other["id"], "text": paraphrase.assertion_text(other, vocab)})
    return found, duplicate


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------
def evaluate(a: dict, vocab: Vocabulary | None = None) -> tuple[str, dict]:
    """Calcule le verdict formel d'une assertion (dictionnaire au format de la table
    assertions). Complète au passage les classes manquantes à partir du domaine et du
    co-domaine du prédicat, en le signalant dans les détails."""
    vocab = vocab or load_active().vocabulary
    details: dict = {"violations": [], "rules": [], "contradictions": [], "notes": [], "questions_domaine": []}

    # 1. Vocabulaire
    if a.get("out_of_ontology_term"):
        details["term"] = a["out_of_ontology_term"]
        details["questions_domaine"].append(
            f"La notion « {a['out_of_ontology_term'].get('term')} » n'existe pas dans l'ontologie. Faut-il l'y ajouter ?"
        )
        return "hors_ontologie", details
    if a["predicate"] not in vocab.predicate_ids():
        details["term"] = {"term": a["predicate"], "kind": "relation"}
        details["questions_domaine"].append(
            f"La relation « {a['predicate']} » n'existe pas dans l'ontologie. Faut-il l'y ajouter ?"
        )
        return "hors_ontologie", details
    for field_name in ("subject_class", "object_class"):
        cls = a.get(field_name)
        if cls and cls not in vocab.classes:
            details["term"] = {"term": cls, "kind": "classe"}
            details["questions_domaine"].append(f"La catégorie « {cls} » n'existe pas dans l'ontologie. Faut-il l'y ajouter ?")
            return "hors_ontologie", details
    if a["predicate"] == INSTANCE_OF and a["object"] not in vocab.classes:
        details["term"] = {"term": a["object"], "kind": "classe"}
        details["questions_domaine"].append(f"La catégorie « {a['object']} » n'existe pas dans l'ontologie. Faut-il l'y ajouter ?")
        return "hors_ontologie", details

    prop = vocab.object_properties.get(a["predicate"]) or vocab.data_properties.get(a["predicate"]) or {}
    if not a.get("subject_class") and prop.get("domain"):
        a["subject_class"] = prop["domain"]
        details["notes"].append(f"Catégorie du sujet déduite du domaine de « {a['predicate']} ».")
    if not a.get("object_is_literal") and not a.get("object_class") and prop.get("range"):
        a["object_class"] = prop["range"]
        details["notes"].append(f"Catégorie de l'objet déduite du co-domaine de « {a['predicate']} ».")

    # 2. SHACL
    try:
        details["violations"] = shacl_violations(a, vocab)
    except Exception as exc:  # noqa: BLE001 — la validation ne doit jamais bloquer le circuit
        log.warning("Validation SHACL impossible : %s", exc)
        details["notes"].append(f"Validation SHACL non effectuée : {exc}")
    for v in details["violations"]:
        details["questions_domaine"].append(
            f"{v} Or {paraphrase.assertion_text(a, vocab, with_scope=False)}. Faut-il revoir la nature de « {a['subject']} » ?"
        )

    # 3. Règles et contradictions
    for violation in rule_violations(a):
        details["rules"].append(violation)
        details["questions_domaine"].append(
            f"Cette proposition relève de la règle « {violation['text']} ». "
            "S'agit-il d'un usage local différent, d'un cas à examiner avec attention, ou d'une erreur ?"
        )
    found, duplicate = contradictions(a, vocab)
    details["contradictions"] = found
    for c in found:
        details["questions_domaine"].append(
            f"Cette proposition contredit une connaissance validée : {c['text']}. S'agit-il d'une variante propre à un autre contexte ?"
        )
    if duplicate:
        details["duplicate_of"] = duplicate

    verdict = "en_tension" if (details["violations"] or details["rules"] or details["contradictions"]) else "conforme"
    return verdict, details
