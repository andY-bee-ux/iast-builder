"""app/ontology_evolution.py — évolution automatique de l'ontologie (phase 3).

Règle de la conception : aucun expert n'écrit, ne lit ni ne corrige de syntaxe
formelle. La décision des experts suffit ; le système formalise et applique.

Quatre mécanismes, implémentés ici :

1. Catalogue fermé d'opérations (OPERATIONS). Toute évolution est une liste
   d'opérations élémentaires, chacune ayant une traduction formelle unique,
   dans l'ontologie JSON comme dans l'ontologie OWL.
2. Formalisation par le système, présentation en langage naturel. Le LLM
   propose les opérations à partir d'une proposition rédigée en français
   (formalize) ; le système en génère une paraphrase par gabarits (paraphrase_ops)
   et c'est cette paraphrase que l'expert valide.
3. Vérification automatique : chaque opération est contrôlée (identifiants,
   existence des classes citées, doublons) avant d'être présentée ; un problème
   est formulé en langage courant.
4. Application, versionnement, retour arrière. Une proposition validée est
   appliquée immédiatement ; chaque application crée une version, dont un
   instantané est conservé dans data/ontology_versions/. Tout changement peut
   être annulé (revert_change) et toute version rétablie (restore_version).

Après chaque application ou retour arrière, les assertions en attente sont
réévaluées : une assertion « hors ontologie » peut devenir conforme dès que la
notion qui lui manquait a été ajoutée.
"""
from __future__ import annotations

import copy
import json
import re
import shutil

import rdflib
from rdflib import OWL, RDF, RDFS, Literal, URIRef

from . import anthropic_client, assertions, db, journal
from .config import ONTOLOGY_VERSIONS_DIR
from .profile import active as active_profile
from .ontology_loader import (
    JSON_PATH, OWL_PATH, Vocabulary, add_owl_label, find_active_ontology_path, load_active,
    owl_base_namespace, save_json, save_owl_graph, vocabulary_brief,
)

ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,80}$")

# Catalogue fermé : nom de l'opération -> champs obligatoires.
OPERATIONS: dict[str, list[str]] = {
    "add_class": ["id", "definition"],               # + label, parent (facultatifs)
    "add_object_property": ["id", "domain", "range", "definition"],
    "add_data_property": ["id", "domain", "definition"],  # + datatype
    "add_rule": ["id", "statement"],                 # + comment
    "add_glossary_term": ["terme", "fr"],            # + variant ; langue fixée par le profil
    "add_individual": ["id", "class"],               # + label
    "update_definition": ["target", "definition"],
    "add_disjointness": ["classes"],
}


class ChangeError(ValueError):
    """Erreur de proposition, formulée pour être lue par un expert."""


# ---------------------------------------------------------------------------
# Paraphrase par gabarits (ce que l'expert lit = ce qui est appliqué)
# ---------------------------------------------------------------------------
def paraphrase_op(op: dict, vocab: Vocabulary) -> str:
    kind = op.get("op")
    if kind == "add_class":
        parent = f", comme cas particulier de « {vocab.class_label(op['parent'])} »" if op.get("parent") else ""
        return f"Ajouter la catégorie « {op.get('label') or op['id']} »{parent}, définie ainsi : {op['definition']}"
    if kind == "add_object_property":
        return (f"Ajouter la relation « {op.get('label') or op['id']} », qui relie un(e) « {vocab.class_label(op['domain'])} » "
                f"à un(e) « {vocab.class_label(op['range'])} » : {op['definition']}")
    if kind == "add_data_property":
        return f"Ajouter l'attribut « {op.get('label') or op['id']} » pour un(e) « {vocab.class_label(op['domain'])} » : {op['definition']}"
    if kind == "add_rule":
        comment = f" ({op['comment']})" if op.get("comment") else ""
        return f"Ajouter la règle d'attribution : {op['statement']}{comment}"
    if kind == "add_glossary_term":
        variant = f", variante « {op['variant']} »" if op.get("variant") else ""
        langue = active_profile().glossary.get("langue", "du domaine")
        return f"Ajouter au glossaire le terme {langue} « {op['terme']} », qui signifie « {op['fr']} »{variant}"
    if kind == "add_individual":
        return f"Ajouter « {op.get('label') or op['id']} » comme {vocab.class_label(op['class'])}"
    if kind == "update_definition":
        return f"Remplacer la définition de « {vocab.class_label(op['target'])} » par : {op['definition']}"
    if kind == "add_disjointness":
        return "Déclarer incompatibles les catégories " + " et ".join(f"« {vocab.class_label(c)} »" for c in op["classes"])
    return f"Opération inconnue : {kind}"


def paraphrase_ops(ops: list[dict], vocab: Vocabulary) -> str:
    return "\n".join(f"{i + 1}. {paraphrase_op(op, vocab)}." for i, op in enumerate(ops))


# ---------------------------------------------------------------------------
# Vérification des opérations
# ---------------------------------------------------------------------------
def check_operations(ops: list[dict], vocab: Vocabulary) -> list[str]:
    """Renvoie la liste des problèmes (vide si tout est applicable). Les opérations
    sont vérifiées dans l'ordre : une classe ajoutée peut servir de parent ensuite."""
    problems: list[str] = []
    classes = set(vocab.classes)
    props = set(vocab.object_properties) | set(vocab.data_properties)
    individuals = set(vocab.individuals)
    rule_ids = {r["id"] for r in vocab.rules}
    if not ops:
        return ["La proposition ne contient aucune opération."]
    for i, op in enumerate(ops, 1):
        kind = op.get("op")
        if kind not in OPERATIONS:
            problems.append(f"Opération {i} : type « {kind} » hors du catalogue autorisé.")
            continue
        missing = [f for f in OPERATIONS[kind] if not op.get(f)]
        if missing:
            problems.append(f"Opération {i} : il manque {', '.join(missing)}.")
            continue
        if "id" in op and not ID_RE.match(op["id"]):
            problems.append(f"Opération {i} : l'identifiant « {op['id']} » doit être un mot sans espace ni accent.")
        if kind == "add_class":
            if op["id"] in classes:
                problems.append(f"Opération {i} : la catégorie « {op['id']} » existe déjà.")
            if op.get("parent") and op["parent"] not in classes:
                problems.append(f"Opération {i} : la catégorie parente « {op['parent']} » n'existe pas.")
            classes.add(op["id"])
        elif kind in {"add_object_property", "add_data_property"}:
            if op["id"] in props:
                problems.append(f"Opération {i} : la relation « {op['id']} » existe déjà.")
            for f in ("domain", "range") if kind == "add_object_property" else ("domain",):
                if op[f] not in classes:
                    problems.append(f"Opération {i} : la catégorie « {op[f]} » n'existe pas.")
            props.add(op["id"])
        elif kind == "add_rule" and op["id"] in rule_ids:
            problems.append(f"Opération {i} : une règle « {op['id']} » existe déjà.")
        elif kind == "add_individual":
            if op["class"] not in classes:
                problems.append(f"Opération {i} : la catégorie « {op['class']} » n'existe pas.")
            if op["id"] in individuals:
                problems.append(f"Opération {i} : « {op['id']} » existe déjà.")
            individuals.add(op["id"])
        elif kind == "update_definition" and op["target"] not in classes | props:
            problems.append(f"Opération {i} : « {op['target']} » n'existe pas dans l'ontologie.")
        elif kind == "add_disjointness":
            unknown = [c for c in op["classes"] if c not in classes]
            if len(op["classes"]) < 2 or unknown:
                problems.append(f"Opération {i} : il faut au moins deux catégories existantes.")
    return problems


# ---------------------------------------------------------------------------
# Application aux deux formats
# ---------------------------------------------------------------------------
def _apply_json(data: dict, ops: list[dict]) -> dict:
    d = copy.deepcopy(data)
    for op in ops:
        kind = op["op"]
        if kind == "add_class":
            d.setdefault("classes", []).append({"id": op["id"], "label": op.get("label") or op["id"],
                                                "parent": op.get("parent"), "def_fr": op["definition"]})
        elif kind == "add_object_property":
            d.setdefault("proprietes_objet", []).append({"id": op["id"], "domaine": op["domain"], "portee": op["range"],
                                                         "def_fr": op["definition"]})
        elif kind == "add_data_property":
            d.setdefault("proprietes_donnees", []).append({"id": op["id"], "domaine": op["domain"],
                                                           "type": op.get("datatype", "string"), "def_fr": op["definition"]})
        elif kind == "add_rule":
            d.setdefault("regles_attribution", []).append({"id": op["id"], "enonce_fr": op["statement"],
                                                           "commentaire": op.get("comment", "")})
        elif kind == "add_glossary_term":
            g = active_profile().glossary
            term = {g.get("langue", "terme"): op["terme"], "fr": op["fr"]}
            if op.get("variant"):
                term["variante"] = op["variant"]
            d.setdefault(g.get("cle", "glossaire"), {}).setdefault("termes", []).append(term)
        elif kind == "add_individual":
            d.setdefault("individus_seed", []).append({"id": op["id"], "classe": op["class"], "label": op.get("label") or op["id"]})
        elif kind == "update_definition":
            for coll in ("classes", "proprietes_objet", "proprietes_donnees"):
                for item in d.get(coll, []):
                    if item["id"] == op["target"]:
                        item["def_fr"] = op["definition"]
        elif kind == "add_disjointness":
            d.setdefault("disjointures", []).append(list(op["classes"]))
    return d


def _apply_owl(g: rdflib.Graph, ops: list[dict], vocab: Vocabulary) -> rdflib.Graph:
    ns = owl_base_namespace(g)

    def iri(term: str) -> URIRef:
        for table in (vocab.classes, vocab.object_properties, vocab.data_properties):
            if term in table:
                return URIRef(table[term]["iri"])
        return ns[term]

    for op in ops:
        kind = op["op"]
        if kind == "add_class":
            node = ns[op["id"]]
            g.add((node, RDF.type, OWL.Class))
            if op.get("parent"):
                g.add((node, RDFS.subClassOf, iri(op["parent"])))
            add_owl_label(g, node, op.get("label") or op["id"], op["definition"])
        elif kind == "add_object_property":
            node = ns[op["id"]]
            g.add((node, RDF.type, OWL.ObjectProperty))
            g.add((node, RDFS.domain, iri(op["domain"])))
            g.add((node, RDFS.range, iri(op["range"])))
            add_owl_label(g, node, op.get("label") or op["id"], op["definition"])
        elif kind == "add_data_property":
            node = ns[op["id"]]
            g.add((node, RDF.type, OWL.DatatypeProperty))
            g.add((node, RDFS.domain, iri(op["domain"])))
            add_owl_label(g, node, op.get("label") or op["id"], op["definition"])
        elif kind == "add_rule":
            # Les règles sont conservées comme individus annotés de la classe RegleAttribution.
            cls = ns["RegleAttribution"]
            g.add((cls, RDF.type, OWL.Class))
            node = ns[op["id"]]
            g.add((node, RDF.type, OWL.NamedIndividual))
            g.add((node, RDF.type, cls))
            add_owl_label(g, node, op["id"], op["statement"] + (f" ({op['comment']})" if op.get("comment") else ""))
        elif kind == "add_glossary_term":
            # Terme du glossaire, décrit comme individu annoté ; la langue (code ISO 639-3) vient du profil.
            code = active_profile().glossary.get("code", "und")
            cls = ns["TermeDuGlossaire"]
            g.add((cls, RDF.type, OWL.Class))
            slug = re.sub(r"[^A-Za-z0-9]+", "_", op["terme"]).strip("_") or "terme"
            node = ns[f"terme_{slug}"]
            g.add((node, RDF.type, OWL.NamedIndividual))
            g.add((node, RDF.type, cls))
            g.add((node, RDFS.label, Literal(op["terme"], lang=code)))
            g.add((node, RDFS.label, Literal(op["fr"], lang="fr")))
            if op.get("variant"):
                g.add((node, RDFS.label, Literal(op["variant"], lang=code)))
        elif kind == "add_individual":
            node = ns[op["id"]]
            g.add((node, RDF.type, OWL.NamedIndividual))
            g.add((node, RDF.type, iri(op["class"])))
            add_owl_label(g, node, op.get("label") or op["id"], None)
        elif kind == "update_definition":
            node = iri(op["target"])
            g.remove((node, RDFS.comment, None))
            g.add((node, RDFS.comment, Literal(op["definition"], lang="fr")))
        elif kind == "add_disjointness":
            cs = [iri(c) for c in op["classes"]]
            for a in cs:
                for b in cs:
                    if a != b:
                        g.add((a, OWL.disjointWith, b))
    return g


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------
def _next_version() -> int:
    row = db.fetch_one("SELECT MAX(version) AS v FROM ontology_versions")
    return (row["v"] or 0) + 1


def snapshot(reason: str, actor: str, change_id: int | None = None) -> int:
    """Enregistre l'ontologie active comme nouvelle version."""
    path = find_active_ontology_path()
    version = _next_version()
    dest = ONTOLOGY_VERSIONS_DIR / f"v{version:04d}{path.suffix}"
    shutil.copyfile(path, dest)
    db.execute(
        "INSERT INTO ontology_versions (version, created_at, file, format, reason, change_id) VALUES (?,?,?,?,?,?)",
        (version, db.now_iso(), dest.name, "json" if path.suffix == ".json" else "owl", reason, change_id),
    )
    journal.append("version_ontologie", "ontologie", version, actor, {"reason": reason, "change_id": change_id, "file": dest.name})
    return version


def ensure_initial_version() -> None:
    """Au premier démarrage, l'ontologie active devient la version 1."""
    if db.fetch_one("SELECT version FROM ontology_versions LIMIT 1") is None:
        try:
            snapshot("Version initiale (ontologie active au premier démarrage)", "systeme")
        except FileNotFoundError:
            pass


def list_versions() -> list[dict]:
    return db.fetch_all("SELECT * FROM ontology_versions ORDER BY version DESC")


def restore_version(version: int, actor: str) -> int:
    """Rétablit le contenu d'une version antérieure. Le rétablissement crée lui-même
    une nouvelle version : l'historique n'est jamais réécrit."""
    row = db.fetch_one("SELECT * FROM ontology_versions WHERE version = ?", (version,))
    if not row:
        raise ChangeError(f"La version {version} n'existe pas.")
    src = ONTOLOGY_VERSIONS_DIR / row["file"]
    if row["format"] == "json":
        save_json(json.loads(src.read_text(encoding="utf-8")))
    else:
        g = rdflib.Graph()
        g.parse(str(src), format="turtle")
        save_owl_graph(g)
    new_version = snapshot(f"Retour au contenu de la version {version}", actor)
    journal.append("retour_version", "ontologie", new_version, actor, {"restored": version})
    assertions.reevaluate_pending()
    return new_version


# ---------------------------------------------------------------------------
# Propositions d'évolution
# ---------------------------------------------------------------------------
def get_change(change_id: int) -> dict | None:
    return db.fetch_one("SELECT * FROM ontology_changes WHERE id = ?", (change_id,), json_fields=("operations",))


def list_changes(status: str | None = None) -> list[dict]:
    if status:
        return db.fetch_all("SELECT * FROM ontology_changes WHERE status = ? ORDER BY id DESC", (status,), json_fields=("operations",))
    return db.fetch_all("SELECT * FROM ontology_changes ORDER BY id DESC", json_fields=("operations",))


def create_change(proposal_text: str, operations: list[dict], origin: str, actor: str) -> dict:
    vocab = load_active().vocabulary
    problems = check_operations(operations, vocab)
    if problems:
        raise ChangeError(" ".join(problems))
    para = paraphrase_ops(operations, vocab)
    cid = db.execute(
        "INSERT INTO ontology_changes (proposal_text, operations, paraphrase, origin, status, created_at) VALUES (?,?,?,?,?,?)",
        (proposal_text, db.dumps(operations), para, origin, "proposed", db.now_iso()),
    )
    journal.append("evolution_proposee", "evolution", cid, actor, {"proposal": proposal_text, "paraphrase": para, "origin": origin})
    return get_change(cid)


FORMALIZE_SYSTEM = """Tu traduis une proposition d'évolution d'une ontologie, rédigée en français par des experts
d'un savoir traditionnel qui ne sont pas informaticiens, en opérations d'un catalogue fermé.

CATALOGUE (seules ces opérations sont permises ; identifiants en CamelCase, sans accents ni espaces) :
- {"op":"add_class","id":...,"label":...,"parent":<classe existante ou null>,"definition":...}
- {"op":"add_object_property","id":...,"label":...,"domain":<classe>,"range":<classe>,"definition":...}
- {"op":"add_data_property","id":...,"label":...,"domain":<classe>,"datatype":"string|integer|boolean|date","definition":...}
- {"op":"add_rule","id":...,"statement":<énoncé de la règle en français>,"comment":...}
- {"op":"add_glossary_term","terme":<terme dans la langue du glossaire>,"fr":...,"variant":<facultatif>}
- {"op":"add_individual","id":...,"label":...,"class":<classe>}
- {"op":"update_definition","target":<classe ou relation existante>,"definition":...}
- {"op":"add_disjointness","classes":[<classe>, <classe>]}

Utilise les classes et relations EXISTANTES chaque fois que c'est possible ; n'invente que ce que la
proposition demande explicitement. Ne formalise rien qui ne figure pas dans la proposition.
Format de sortie : {"operations":[...], "commentaire":"<remarque éventuelle pour l'expert, en français courant>"}"""


async def formalize(proposal_text: str, context: str | None = None) -> dict:
    """Demande au LLM de traduire une proposition en opérations du catalogue.
    Renvoie {operations, paraphrase, problems, commentaire} sans rien enregistrer :
    l'expert relit la paraphrase avant de créer la proposition."""
    vocab = load_active().vocabulary
    user = f"ONTOLOGIE ACTUELLE :\n{vocabulary_brief(vocab)}\n\nPROPOSITION DES EXPERTS :\n{proposal_text}"
    if context:
        user += f"\n\nCONTEXTE :\n{context}"
    result = await anthropic_client.complete_json(FORMALIZE_SYSTEM, user)
    ops = result.get("operations", []) if isinstance(result, dict) else []
    problems = check_operations(ops, vocab)
    return {
        "operations": ops,
        "paraphrase": paraphrase_ops(ops, vocab) if not problems else "",
        "problems": problems,
        "commentaire": result.get("commentaire") if isinstance(result, dict) else None,
    }


def apply_change(change_id: int, expert: str, notes: str | None = None) -> dict:
    """Applique une proposition validée par les experts et publie une nouvelle version."""
    change = get_change(change_id)
    if not change:
        raise ChangeError("Proposition introuvable.")
    if change["status"] not in {"proposed", "deliberation"}:
        raise ChangeError(f"Cette proposition a déjà été traitée (statut : {change['status']}).")
    bundle = load_active()
    problems = check_operations(change["operations"], bundle.vocabulary)
    if problems:
        raise ChangeError("L'ontologie a changé depuis la proposition : " + " ".join(problems))
    if bundle.format == "json":
        save_json(_apply_json(bundle.data, change["operations"]))
    else:
        g = rdflib.Graph()
        g.parse(data=bundle.raw_text, format="turtle")
        save_owl_graph(_apply_owl(g, change["operations"], bundle.vocabulary))
    version = snapshot(f"Évolution n° {change_id} : {change['proposal_text'][:120]}", expert, change_id)
    db.execute(
        "UPDATE ontology_changes SET status = 'applied', applied_version = ?, decided_by = ?, notes = ? WHERE id = ?",
        (version, expert, notes, change_id),
    )
    journal.append("evolution_appliquee", "evolution", change_id, expert, {"version": version, "notes": notes})
    reevaluated = assertions.reevaluate_pending()
    return {**get_change(change_id), "reevaluated_assertions": reevaluated}


def reject_change(change_id: int, expert: str, notes: str | None = None) -> dict:
    change = get_change(change_id)
    if not change or change["status"] not in {"proposed", "deliberation"}:
        raise ChangeError("Proposition introuvable ou déjà traitée.")
    db.execute("UPDATE ontology_changes SET status = 'rejected', decided_by = ?, notes = ? WHERE id = ?", (expert, notes, change_id))
    journal.append("evolution_rejetee", "evolution", change_id, expert, {"notes": notes})
    return get_change(change_id)


def set_deliberation(change_id: int, expert: str) -> dict:
    db.execute("UPDATE ontology_changes SET status = 'deliberation' WHERE id = ? AND status = 'proposed'", (change_id,))
    journal.append("evolution_en_deliberation", "evolution", change_id, expert, {})
    return get_change(change_id)


def revert_change(change_id: int, expert: str) -> dict:
    """Annule d'une seule action la dernière évolution appliquée, en rétablissant
    la version qui la précédait. Pour une évolution plus ancienne, utiliser
    restore_version, qui annule aussi les évolutions postérieures."""
    change = get_change(change_id)
    if not change or change["status"] != "applied":
        raise ChangeError("Seule une évolution appliquée peut être annulée.")
    latest = db.fetch_one("SELECT MAX(applied_version) AS v FROM ontology_changes WHERE status = 'applied'")
    if latest["v"] != change["applied_version"]:
        raise ChangeError(
            "D'autres évolutions ont été appliquées depuis celle-ci. Pour l'annuler, rétablissez la version "
            f"{change['applied_version'] - 1} depuis la liste des versions (les évolutions postérieures seront aussi annulées)."
        )
    new_version = restore_version(change["applied_version"] - 1, expert)
    db.execute("UPDATE ontology_changes SET status = 'reverted' WHERE id = ?", (change_id,))
    journal.append("evolution_annulee", "evolution", change_id, expert, {"new_version": new_version})
    return get_change(change_id)
