"""app/ontology_loader.py — chargement de l'ontologie active, JSON ou OWL.

Deux formats sont acceptés, de manière interchangeable :
- le schéma JSON propre au projet (classes, proprietes_objet, regles_attribution,
  glossaire, repertoire_bangangte...) ;
- OWL, dans toute sérialisation lue par rdflib (.owl/.rdf/.xml en RDF/XML,
  .ttl en Turtle, .n3), tel que produit par un éditeur comme Protégé.

Un seul fichier est actif à la fois : data/ontology.json OU data/ontology.ttl.
Tout import OWL est normalisé en Turtle, pour que le panneau d'administration et
le prompt ne présentent qu'une syntaxe.

Ce module fournit aussi une vue unifiée du vocabulaire (Vocabulary), quel que soit
le format : classes, propriétés, règles, individus, disjonctions. C'est cette vue
qu'utilisent l'extraction guidée (phase 2), la validation formelle (phase 2) et
l'évolution automatique de l'ontologie (phase 3). Le reste du système n'a donc
jamais à savoir dans quel format l'ontologie est rédigée.

Le chargement est mis en cache selon la date de modification du fichier : une
ontologie modifiée est relue dès la question suivante, sans redémarrage.
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import rdflib
from rdflib import OWL, RDF, RDFS, Literal, Namespace, URIRef
from rdflib.util import guess_format

from .config import DATA_DIR
from .profile import active as active_profile

JSON_PATH = DATA_DIR / "ontology.json"
OWL_PATH = DATA_DIR / "ontology.ttl"
OWL_UPLOAD_EXTENSIONS = {".owl", ".rdf", ".ttl", ".n3", ".xml"}

# Espace de noms des entités décrites par les assertions (noms, lignages, lieux, plantes...).
YKD = Namespace("http://iast.uqam.ca/yobakoko/data/")


def domain_ns() -> Namespace:
    """Espace de noms du domaine, déclaré par le profil actif (ex. http://iast.uqam.ca/ndab#).
    Il sert à exprimer en RDF une ontologie rédigée en JSON."""
    return Namespace(active_profile().namespace)

# Prédicat générique d'appartenance à une classe, disponible quel que soit le
# vocabulaire de l'ontologie (traduit par rdf:type en RDF).
INSTANCE_OF = "estUn"


# ---------------------------------------------------------------------------
# Vue unifiée du vocabulaire
# ---------------------------------------------------------------------------
@dataclass
class Vocabulary:
    format: str
    classes: dict[str, dict] = field(default_factory=dict)            # id -> {label, parents, definition, iri}
    object_properties: dict[str, dict] = field(default_factory=dict)  # id -> {label, domain, range, definition, iri}
    data_properties: dict[str, dict] = field(default_factory=dict)    # id -> {label, domain, datatype, definition, iri}
    rules: list[dict] = field(default_factory=list)                   # {id, text, comment}
    individuals: dict[str, dict] = field(default_factory=dict)        # id -> {label, class}
    disjoint: list[list[str]] = field(default_factory=list)
    repertoire_blocks: set[str] = field(default_factory=set)          # identifiants BGT_xx (JSON)

    def class_ancestors(self, cls: str) -> set[str]:
        """Classe elle-même et tous ses ancêtres (fermeture de la hiérarchie)."""
        seen, stack = set(), [cls]
        while stack:
            c = stack.pop()
            if c in seen or c not in self.classes:
                continue
            seen.add(c)
            stack.extend(self.classes[c].get("parents", []))
        return seen

    def predicate_ids(self) -> set[str]:
        return set(self.object_properties) | set(self.data_properties) | {INSTANCE_OF}

    def predicate_label(self, pid: str) -> str:
        """Libellé lisible : « estDeType » devient « est de type »."""
        if pid == INSTANCE_OF:
            return "est un(e)"
        info = self.object_properties.get(pid) or self.data_properties.get(pid) or {}
        label = info.get("label") or pid
        return re.sub(r"(?<=[a-zé])(?=[A-Z])", " ", label).lower()

    def class_label(self, cid: str | None) -> str:
        if not cid:
            return ""
        return (self.classes.get(cid) or {}).get("label") or cid


@dataclass
class OntologyBundle:
    format: str               # "json" ou "owl"
    raw_text: str             # texte JSON, ou Turtle
    data: dict | None         # objet JSON (format json seulement)
    graph: rdflib.Graph | None  # graphe RDF (format owl seulement)
    vocabulary: Vocabulary
    summary: dict | None = None


# ---------------------------------------------------------------------------
# Localisation et chargement
# ---------------------------------------------------------------------------
def find_active_ontology_path() -> Path:
    """Le fichier Turtle est prioritaire : s'il existe, c'est qu'un import OWL a eu lieu."""
    if OWL_PATH.exists():
        return OWL_PATH
    if JSON_PATH.exists():
        return JSON_PATH
    raise FileNotFoundError(
        "Aucune ontologie trouvée (ni data/ontology.json, ni data/ontology.ttl). "
        "Placez-en une avant de démarrer, ou importez-la depuis le panneau d'administration."
    )


_cache: dict = {"key": None, "bundle": None}


def load_active() -> OntologyBundle:
    path = find_active_ontology_path()
    key = (str(path), path.stat().st_mtime_ns)
    if _cache["key"] == key:
        return _cache["bundle"]
    if path.suffix == ".json":
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        bundle = OntologyBundle("json", text, data, None, vocabulary_from_json(data))
    else:
        g = rdflib.Graph()
        g.parse(str(path), format="turtle")
        bundle = OntologyBundle("owl", g.serialize(format="turtle"), None, g, vocabulary_from_owl(g))
        bundle.summary = summarize_owl_graph(g)
    _cache.update(key=key, bundle=bundle)
    return bundle


def invalidate_cache() -> None:
    _cache.update(key=None, bundle=None)


# ---------------------------------------------------------------------------
# Construction du vocabulaire
# ---------------------------------------------------------------------------
def vocabulary_from_json(data: dict) -> Vocabulary:
    NDAB = domain_ns()
    v = Vocabulary("json")
    for c in data.get("classes", []):
        v.classes[c["id"]] = {
            "label": c.get("label") or c["id"],
            "parents": [c["parent"]] if c.get("parent") else [],
            "definition": c.get("def_fr", ""),
            "iri": str(NDAB[c["id"]]),
        }
    for p in data.get("proprietes_objet", []):
        v.object_properties[p["id"]] = {
            "label": p.get("label") or p["id"], "domain": p.get("domaine"), "range": p.get("portee"),
            "definition": p.get("def_fr", ""), "iri": str(NDAB[p["id"]]),
        }
    for p in data.get("proprietes_donnees", []):
        v.data_properties[p["id"]] = {
            "label": p.get("label") or p["id"], "domain": p.get("domaine"), "datatype": p.get("type"),
            "definition": p.get("def_fr", ""), "iri": str(NDAB[p["id"]]),
        }
    for r in data.get("regles_attribution", []):
        v.rules.append({"id": r["id"], "text": r.get("enonce_fr", ""), "comment": r.get("commentaire", "")})
    for i in data.get("individus_seed", []):
        v.individuals[i["id"]] = {"label": i.get("nomChefferie") or i.get("label") or i["id"], "class": i.get("classe")}
    v.disjoint = [list(d) for d in data.get("disjointures", [])]
    # Blocs d'un répertoire de terrain embarqué dans l'ontologie (clé déclarée par le profil),
    # citables dans le dossier de réponse sous la forme REP:<identifiant>.
    rep_key = active_profile().raw.get("ontologie", {}).get("cle_repertoire", "repertoire_bangangte")
    rep = data.get(rep_key) or {}
    v.repertoire_blocks = {e["id"] for e in rep.get("entrees", []) if "id" in e}
    return v


def _local_name(uri) -> str:
    s = str(uri)
    return s.split("#")[-1].split("/")[-1]


def _label_or_local(g: rdflib.Graph, node) -> str:
    label = g.value(node, RDFS.label)
    return str(label) if label else _local_name(node)


def vocabulary_from_owl(g: rdflib.Graph) -> Vocabulary:
    v = Vocabulary("owl")
    for c in set(g.subjects(RDF.type, OWL.Class)):
        if not isinstance(c, URIRef):
            continue
        v.classes[_local_name(c)] = {
            "label": _label_or_local(g, c),
            "parents": [_local_name(p) for p in g.objects(c, RDFS.subClassOf) if isinstance(p, URIRef)],
            "definition": str(g.value(c, RDFS.comment) or ""),
            "iri": str(c),
        }
    for p in set(g.subjects(RDF.type, OWL.ObjectProperty)):
        dom, rng = g.value(p, RDFS.domain), g.value(p, RDFS.range)
        v.object_properties[_local_name(p)] = {
            "label": _label_or_local(g, p), "domain": _local_name(dom) if dom else None,
            "range": _local_name(rng) if rng else None, "definition": str(g.value(p, RDFS.comment) or ""), "iri": str(p),
        }
    for p in set(g.subjects(RDF.type, OWL.DatatypeProperty)):
        dom = g.value(p, RDFS.domain)
        v.data_properties[_local_name(p)] = {
            "label": _label_or_local(g, p), "domain": _local_name(dom) if dom else None,
            "datatype": str(g.value(p, RDFS.range) or ""), "definition": str(g.value(p, RDFS.comment) or ""), "iri": str(p),
        }
    for i in set(g.subjects(RDF.type, OWL.NamedIndividual)):
        types = [t for t in g.objects(i, RDF.type) if t != OWL.NamedIndividual]
        v.individuals[_local_name(i)] = {"label": _label_or_local(g, i), "class": _local_name(types[0]) if types else None}
    for a, b in g.subject_objects(OWL.disjointWith):
        v.disjoint.append([_local_name(a), _local_name(b)])
    return v


def summarize_owl_graph(g: rdflib.Graph) -> dict:
    """Résumé lisible d'un graphe OWL, placé en tête du bloc ontologique du prompt."""
    v = vocabulary_from_owl(g)
    return {
        "classes": [
            {"id": c["label"], "parents": [v.class_label(p) for p in c["parents"]], "comment": c["definition"] or None}
            for c in v.classes.values()
        ],
        "object_properties": [p["label"] for p in v.object_properties.values()],
        "data_properties": [p["label"] for p in v.data_properties.values()],
        "individuals": [i["label"] for i in v.individuals.values()],
    }


def iri_for_term(vocab: Vocabulary, term: str, cls: str | None = None) -> URIRef:
    """IRI d'une classe, d'une propriété ou d'un individu de l'ontologie ; à défaut,
    IRI d'une entité de données (nom, lignage, lieu) dans l'espace YKD.

    La classe de l'entité entre dans son IRI : une même forme peut désigner des
    entités de natures différentes (ex. « Gooun Tchoou », libellé de lignage et Ndab),
    qui ne doivent pas être confondues dans le graphe."""
    for table in (vocab.classes, vocab.object_properties, vocab.data_properties):
        if term in table:
            return URIRef(table[term]["iri"])
    if term in vocab.individuals:
        return URIRef(str(domain_ns()[term]))
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", term.strip()).strip("_") or "entite"
    return YKD[f"{cls}/{slug}"] if cls else YKD[slug]


def schema_graph(vocab: Vocabulary) -> rdflib.Graph:
    """Graphe RDFS du vocabulaire (hiérarchie, domaines, co-domaines), utilisé
    comme graphe d'ontologie par la validation SHACL, quel que soit le format source."""
    g = rdflib.Graph()
    for cid, c in vocab.classes.items():
        iri = URIRef(c["iri"])
        g.add((iri, RDF.type, RDFS.Class))
        for p in c.get("parents", []):
            if p in vocab.classes:
                g.add((iri, RDFS.subClassOf, URIRef(vocab.classes[p]["iri"])))
    for pid, p in vocab.object_properties.items():
        iri = URIRef(p["iri"])
        g.add((iri, RDF.type, RDF.Property))
        if p.get("domain") in vocab.classes:
            g.add((iri, RDFS.domain, URIRef(vocab.classes[p["domain"]]["iri"])))
        if p.get("range") in vocab.classes:
            g.add((iri, RDFS.range, URIRef(vocab.classes[p["range"]]["iri"])))
    return g


# ---------------------------------------------------------------------------
# Texte de l'ontologie pour le prompt
# ---------------------------------------------------------------------------
def prompt_block(bundle: OntologyBundle) -> str:
    """Bloc ontologique injecté dans le dossier de réponse (identifiant de fait : ONT)."""
    if bundle.format == "json":
        return (
            "[ONT] ONTOLOGIE DE BASE (JSON, source de vérité symbolique : classes, propriétés, règles d'attribution ; "
            "les blocs du répertoire de terrain se citent [REP:<identifiant du bloc>], les règles [<identifiant de la règle>]) :\n"
            + bundle.raw_text
        )
    s = bundle.summary or {}
    counts = (
        f"{len(s.get('classes', []))} classes, {len(s.get('object_properties', []))} propriétés d'objet, "
        f"{len(s.get('data_properties', []))} propriétés de données, {len(s.get('individuals', []))} individus."
    )
    class_list = "\n".join(
        f"- {c['id']}" + (f" (sous-classe de {', '.join(c['parents'])})" if c["parents"] else "")
        + (f" : {c['comment']}" if c["comment"] else "")
        for c in s.get("classes", [])
    )
    return (
        "[ONT] ONTOLOGIE DE BASE (format OWL, sérialisée en Turtle, source de vérité symbolique).\n"
        f"Résumé : {counts}\n\nHiérarchie des classes :\n{class_list}\n\nGraphe complet (syntaxe Turtle) :\n{bundle.raw_text}"
    )


# ---------------------------------------------------------------------------
# Écriture, sauvegardes et import (utilisés par le panneau d'administration)
# ---------------------------------------------------------------------------
def backup_active() -> str | None:
    """Copie horodatée du fichier actif dans data/ontology_backups/.
    Renvoie le nom de la copie, ou None s'il n'y avait encore aucune ontologie."""
    try:
        path = find_active_ontology_path()
    except FileNotFoundError:
        return None
    backup_dir = DATA_DIR / "ontology_backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")
    dest = backup_dir / f"ontology_{stamp}{path.suffix}"
    shutil.copyfile(path, dest)
    return dest.name


def validate_json_text(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON invalide : {exc}") from exc


def validate_and_normalize_owl_text(text: str, hint_format: str | None = None) -> str:
    """Analyse un texte OWL (Turtle, RDF/XML ou N3) et le renvoie en Turtle."""
    tried = ([hint_format] if hint_format else []) + ["turtle", "xml", "n3"]
    last_error = None
    for fmt in tried:
        g = rdflib.Graph()
        try:
            g.parse(data=text, format=fmt)
            return g.serialize(format="turtle")
        except Exception as exc:  # noqa: BLE001 — plusieurs syntaxes sont essayées volontairement
            last_error = exc
    raise ValueError(f"Ontologie OWL invalide (essayé en Turtle, RDF/XML, N3) : {last_error}")


def save_json(text_or_data) -> None:
    data = validate_json_text(text_or_data) if isinstance(text_or_data, str) else text_or_data
    JSON_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    if OWL_PATH.exists():
        OWL_PATH.unlink()  # un seul fichier actif
    invalidate_cache()


def save_owl_text(text: str, hint_format: str | None = None) -> None:
    OWL_PATH.write_text(validate_and_normalize_owl_text(text, hint_format), encoding="utf-8")
    if JSON_PATH.exists():
        JSON_PATH.unlink()
    invalidate_cache()


def save_owl_graph(g: rdflib.Graph) -> None:
    OWL_PATH.write_text(g.serialize(format="turtle"), encoding="utf-8")
    if JSON_PATH.exists():
        JSON_PATH.unlink()
    invalidate_cache()


def save_owl_upload(file_path: Path, original_filename: str) -> None:
    """Import d'un fichier OWL : format deviné d'après l'extension, puis normalisation en Turtle."""
    fmt = guess_format(original_filename) or "xml"
    g = rdflib.Graph()
    g.parse(str(file_path), format=fmt)
    save_owl_graph(g)


def owl_base_namespace(g: rdflib.Graph) -> Namespace:
    """Espace de noms de l'ontologie OWL (IRI de owl:Ontology suivi de '#'),
    utilisé pour nommer les éléments ajoutés automatiquement (phase 3)."""
    onto = next(iter(g.subjects(RDF.type, OWL.Ontology)), None)
    if onto is None:
        return domain_ns()
    base = str(onto)
    return Namespace(base if base.endswith(("#", "/")) else base + "#")


def add_owl_label(g: rdflib.Graph, node: URIRef, label: str | None, comment: str | None) -> None:
    if label:
        g.add((node, RDFS.label, Literal(label, lang="fr")))
    if comment:
        g.add((node, RDFS.comment, Literal(comment, lang="fr")))


def vocabulary_brief(vocab: Vocabulary) -> str:
    """Description compacte du vocabulaire, fournie au LLM pour les tâches
    structurées (extraction guidée, formalisation). Elle constitue la « contrainte
    en amont » de la conception : le modèle ne peut employer que ces termes."""
    lines = ["CLASSES (identifiant : définition ; parent) :"]
    for cid, c in vocab.classes.items():
        parent = f" ; sous-classe de {', '.join(c['parents'])}" if c.get("parents") else ""
        lines.append(f"- {cid} : {c.get('definition', '')[:180]}{parent}")
    lines.append("\nRELATIONS ENTRE ENTITÉS (identifiant : domaine -> co-domaine : définition) :")
    lines.append(f"- {INSTANCE_OF} : entité -> classe : appartenance d'une entité à une classe")
    for pid, p in vocab.object_properties.items():
        lines.append(f"- {pid} : {p.get('domain')} -> {p.get('range')} : {p.get('definition', '')[:160]}")
    lines.append("\nATTRIBUTS (identifiant : domaine -> type de valeur) :")
    for pid, p in vocab.data_properties.items():
        lines.append(f"- {pid} : {p.get('domain')} -> {p.get('datatype')}")
    if vocab.individuals:
        lines.append("\nINDIVIDUS CONNUS : " + ", ".join(list(vocab.individuals)[:60]))
    return "\n".join(lines)
