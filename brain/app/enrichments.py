"""app/enrichments.py — graphe des enrichissements validés (phase 3).

La base SQLite (table assertions, statut 'validated') est la source de vérité.
Ce module en dérive :

1. un graphe RDF exporté dans data/enrichments.ttl, séparé de l'ontologie de
   référence. Chaque assertion validée y figure deux fois :
     - comme triplet direct (sujet, prédicat, objet), interrogeable en SPARQL ;
     - comme entité PROV-O décrivant sa provenance (source, méthode, expert,
       date de validation, portée).
   Le fichier est régénéré à chaque validation ou retrait ; il peut être chargé
   dans un éditeur OWL pour intégrer les enrichissements à une future version
   de l'ontologie de référence ;

2. la sélection des assertions validées pertinentes pour une question, qui
   entrent dans le dossier de réponse de l'agent (identifiants E<n>).
"""
from __future__ import annotations

import re

import json

import rdflib
from rdflib import RDF, RDFS, XSD, Literal, Namespace

from . import db, paraphrase
from .config import ENRICHMENTS_TTL, MAX_ENRICHMENTS_IN_PROMPT
from .ontology_loader import INSTANCE_OF, iri_for_term, load_active
from .profile import active as active_profile
from .text_utils import normalize_form, tokens

PROV = Namespace("http://www.w3.org/ns/prov#")
YK = Namespace("http://iast.uqam.ca/yobakoko/vocab#")
YKA = Namespace("http://iast.uqam.ca/yobakoko/assertion/")


def validated() -> list[dict]:
    return db.fetch_all("SELECT * FROM assertions WHERE status = 'validated' ORDER BY id", json_fields=("scope",))


def rebuild() -> int:
    """Régénère data/enrichments.ttl depuis la base. Renvoie le nombre d'assertions."""
    vocab = load_active().vocabulary
    g = rdflib.Graph()
    for prefix, ns in (("prov", PROV), ("yk", YK), ("yka", YKA)):
        g.bind(prefix, ns)
    rows = validated()
    for a in rows:
        s = iri_for_term(vocab, a["subject"], a.get("subject_class"))
        g.add((s, RDFS.label, Literal(a["subject"])))
        if a["predicate"] == INSTANCE_OF:
            o = iri_for_term(vocab, a["object"])
            g.add((s, RDF.type, o))
        else:
            p = iri_for_term(vocab, a["predicate"])
            o = Literal(a["object"]) if a["object_is_literal"] else iri_for_term(vocab, a["object"], a.get("object_class"))
            g.add((s, p, o))
            if not a["object_is_literal"]:
                g.add((o, RDFS.label, Literal(a["object"])))
        node = YKA[str(a["id"])]
        g.add((node, RDF.type, PROV.Entity))
        g.add((node, RDF.type, YK.AssertionValidee))
        g.add((node, YK.sujet, s))
        g.add((node, YK.predicat, iri_for_term(vocab, a["predicate"])))
        g.add((node, YK.objet, Literal(a["object"])))
        g.add((node, YK.paraphrase, Literal(paraphrase.assertion_text(a, vocab), lang="fr")))
        g.add((node, YK.portee, Literal(json.dumps(a["scope"], ensure_ascii=False))))
        g.add((node, YK.methode, Literal(a["method"])))
        g.add((node, YK.niveauDAcces, Literal(a.get("access_level") or "public")))
        if a.get("source_ref"):
            g.add((node, PROV.wasDerivedFrom, Literal(a["source_ref"])))
        if a.get("decided_by"):
            g.add((node, PROV.wasAttributedTo, Literal(a["decided_by"])))
        if a.get("decided_at"):
            g.add((node, PROV.generatedAtTime, Literal(a["decided_at"], datatype=XSD.dateTime)))
    ENRICHMENTS_TTL.write_text(g.serialize(format="turtle"), encoding="utf-8")
    return len(rows)


def relevant(text: str, limit: int = MAX_ENRICHMENTS_IN_PROMPT, context=()) -> list[dict]:
    """Connaissances validées en rapport avec la question en cours, puis avec les messages précédents,
    du plus récent au plus ancien. Une question qui renvoie au contexte (« et ses usages ? », « oui »)
    s'appuie ainsi d'abord sur le dernier échange, et non sur une réponse ancienne qui citait toute la base.
    `context` est la liste des messages précédents, du plus récent au plus ancien (une chaîne est acceptée)."""
    messages = [context] if isinstance(context, str) else list(context)
    chosen: list[dict] = []
    seen: set[int] = set()
    for i, chunk in enumerate([text, *messages]):
        if len(chosen) >= limit:
            break
        # Un terme partagé (une source, une préparation) n'est suivi que s'il est nommé dans la question en cours.
        for a in _relevant_one(chunk, limit, allow_hubs=(i == 0)):
            if a["id"] not in seen:
                seen.add(a["id"]); chosen.append(a)
    return chosen[:limit]


def _relevant_one(text: str, limit: int, allow_hubs: bool = True) -> list[dict]:
    """Connaissances validées liées aux entités nommées dans `text`, regroupées par entité.

    1. Ancrage : une connaissance est retenue si son sujet ou son objet est nommé dans le texte, comme
       mot ou groupe de mots entiers (« Sira » n'est pas reconnu à l'intérieur d'un autre mot).
    2. Pour chaque entité ancrée, dans l'ordre où elle apparaît : sa description (les connaissances dont
       elle est le sujet ou l'objet), puis les entités qui s'y rattachent (un usage qui concerne une
       plante, un nom qui la désigne) avec toutes leurs connaissances. Tout ce qui concerne une entité
       est ainsi présenté d'un seul tenant.
    3. Les termes partagés (« pivots ») ne servent pas de passage : une source, une préparation ou une
       maladie citée par plusieurs entités sans être décrite elle-même (« OOAS 2013 », « Décoction »)
       ramènerait sinon les connaissances d'autres plantes. Un pivot n'est suivi que s'il est nommé
       dans la question en cours (allow_hubs)."""
    if not text.strip():
        return []
    allowed = set(active_profile().allowed_levels_for_agent())
    pool = [a for a in validated() if (a.get("access_level") or "public") in allowed]
    def spaced(t: str) -> str:
        return " ".join(normalize_form(w) for w in re.findall(r"\w+", t) if normalize_form(w))

    spaced_text = " " + spaced(text) + " "
    concat_text = normalize_form(text)
    text_tokens = tokens(text)

    def entity_obj(a):
        return None if a.get("object_is_literal") else a["object"]

    subjects = {a["subject"] for a in pool}
    pointing: dict[str, set] = {}
    for a in pool:
        o = entity_obj(a)
        if o:
            pointing.setdefault(o, set()).add(a["subject"])
    hubs = {e for e, subs in pointing.items() if e not in subjects and len(subs) >= 2}

    def named(term: str) -> bool:
        """Le terme est nommé dans le texte comme mot ou groupe de mots entiers ; une forme longue est aussi
        reconnue écrite sans espace (« GoounTchoouh » pour « Gooun Tchoouh »)."""
        st = spaced(term)
        if len(st) >= 2 and f" {st} " in spaced_text:
            return True
        nt = normalize_form(term)
        return len(nt) >= 8 and nt in concat_text

    # 1. Ancrage, dans l'ordre d'apparition des connaissances concernées.
    seeds: list[dict] = []
    anchors: list[str] = []
    for a in pool:
        terms = [t for t in (a["subject"], entity_obj(a)) if t and named(t) and (allow_hubs or t not in hubs)]
        fallback = allow_hubs and not terms and len(tokens(a["subject"] + " " + a["object"]) & text_tokens) >= 2
        if terms or fallback:
            seeds.append(a)
            # Les deux extrémités d'une connaissance ancrée sont à décrire (« baobab » désigne « Adansonia
            # digitata » : on décrit aussi Adansonia digitata), sauf les termes partagés.
            for t in (a["subject"], entity_obj(a)):
                if t and t not in anchors and t not in hubs:
                    anchors.append(t)
    # Les entités nommées dans le texte passent avant celles qui ne sont atteintes que par une connaissance.
    anchors.sort(key=lambda e: 0 if named(e) else 1)

    # 2. Regroupement par entité ancrée.
    chosen: list[dict] = []
    seen: set[int] = set()

    def add(items):
        for a in items:
            if a["id"] not in seen:
                seen.add(a["id"]); chosen.append(a)

    for anchor in anchors:
        add(a for a in seeds if anchor in (a["subject"], entity_obj(a)))
        add(a for a in pool if a["subject"] == anchor or entity_obj(a) == anchor)
        attached = [sub for sub in sorted(pointing.get(anchor, ())) if sub not in anchors and sub not in hubs]
        for sub in attached:
            add(a for a in pool if a["subject"] == sub)
        if len(chosen) >= limit:
            break
    add(seeds)
    return chosen[:limit]


def inventory() -> list[str]:
    """Vue d'ensemble de ce que l'agent sait, déclarée par le profil (clé « inventaire ») : pour chaque
    classe, le nombre d'entités documentées et, dans la limite fixée, leur liste avec un attribut
    (par exemple la famille d'une plante). Sans elle, l'agent ne voit que les connaissances liées aux
    entités nommées dans la conversation, et peut prendre ce fragment pour l'ensemble de sa base."""
    spec = active_profile().raw.get("inventaire") or []
    if not spec:
        return []
    allowed = set(active_profile().allowed_levels_for_agent())
    pool = [a for a in validated() if (a.get("access_level") or "public") in allowed]
    lines = []
    for item in spec:
        cls, attr, cap = item["classe"], item.get("attribut"), item.get("max", 50)
        entities = sorted({a["subject"] for a in pool if a.get("subject_class") == cls}
                          | {a["object"] for a in pool if a.get("object_class") == cls and not a.get("object_is_literal")})
        if not entities:
            continue
        values = {}
        if attr:
            for a in pool:
                if a["predicate"] == attr and a["subject"] in entities:
                    values.setdefault(a["subject"], a["object"])
        label = item.get("libelle", cls)
        if cap == 0:
            lines.append(f"{label} : {len(entities)}.")
            continue
        # Une absence écrite se laisse moins combler qu'une absence silencieuse.
        missing = f"{attr} non renseignée" if attr else ""
        shown = [f"{e} ({values[e]})" if e in values else (f"{e} ({missing})" if attr else e) for e in entities[:cap]]
        more = f", et {len(entities) - cap} autres" if len(entities) > cap else ""
        lines.append(f"{label} ({len(entities)}) : " + ", ".join(shown) + more + ".")
        if attr and values:
            # Décompte tout fait : le modèle n'a pas à compter lui-même.
            distinct = sorted(set(values.values()))
            without = len([e for e in entities if e not in values])
            lines.append(f"{item.get('libelle_attribut', attr)} ({len(distinct)}) : {', '.join(distinct)}"
                         + (f" ; {without} entité(s) sans cette information." if without else "."))
    return lines
