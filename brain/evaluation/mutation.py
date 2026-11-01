"""evaluation/mutation.py — volet 1 : la vérification de conformité détecte-t-elle les profils défectueux ?

Analyse par mutation. À partir des profils valides (ndab, afripharm), on génère des profils défectueux
par des opérateurs de mutation appliqués systématiquement (à chaque règle, chaque contrainte, chaque
fait de correspondance...). Chaque mutant est soumis au vérificateur (invariants IP1 à IP8 et cohérence
avec l'ontologie). Deux familles d'opérateurs :

- défauts structurels (S) : le vérificateur doit les détecter ;
- erreurs sémantiques plausibles (P) : profils bien formés mais erronés pour le domaine ; le vérificateur
  n'est pas conçu pour les voir. Les mesurer situe la limite de la vérification.

Usage (depuis brain/) : python -m evaluation.mutation
Sorties : evaluation/resultats/mutation.csv, mutation.json
"""
from __future__ import annotations

import copy
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import profile_check  # noqa: E402
from app.profile import Profile, load_profile  # noqa: E402

OUT = Path(__file__).resolve().parent / "resultats"


def _mappings(p: Profile) -> list[tuple[Path, dict]]:
    return [(m, json.loads(m.read_text(encoding="utf-8"))) for m in sorted(p.mappings_dir.glob("*.json"))]


def mutants(p: Profile):
    """Produit (famille, opérateur, cible, invariant attendu, raw muté, correspondances mutées ou None)."""
    raw = p.raw

    def mut(fn):
        r = copy.deepcopy(raw)
        fn(r)
        return r

    # --- S : défauts structurels ---
    yield "S", "autorite_absente", "-", "IP2", mut(lambda r: r.pop("autorite", None)), None
    yield "S", "portee_vide", "-", "IP3", mut(lambda r: r.__setitem__("portee", [])), None
    yield "S", "niveaux_absents", "-", "IP4", mut(lambda r: r["acces"].__setitem__("niveaux", [])), None
    yield "S", "diffusion_non_declaree", "-", "IP4", mut(lambda r: r["acces"].__setitem__("niveau_diffusion_agent", "inexistant")), None
    yield "S", "corpus_absent", "-", "IP1", mut(lambda r: r["ontologie"].pop("corpus", None)), None
    yield "S", "origine_invalide", "-", "IP1", mut(lambda r: r["ontologie"].__setitem__("origine", "inconnue")), None
    yield "S", "fichier_ontologie_absent", "-", "coherence", mut(lambda r: r["ontologie"].__setitem__("fichier", "absent.json")), None
    for mode in ("temoignages", "formulaire", "lacunes"):
        yield "S", "collecte_non_declaree", mode, "IP8", mut(lambda r, m=mode: r["collecte"].pop(m, None)), None
    # Risque élevé : sans contrainte, avec un seul niveau, contrainte sans motif.
    def high_no_constraint(r):
        r["surete"]["risque"] = "eleve"; r["surete"]["contraintes"] = []
    yield "S", "risque_eleve_sans_contrainte", "-", "IP5", mut(high_no_constraint), None
    def high_one_level(r):
        r["surete"]["risque"] = "eleve"
        r["surete"].setdefault("contraintes", []) or r["surete"].__setitem__("contraintes", [{"id": "c", "description": "d", "motifs": ["x"]}])
        lvl = r["acces"]["niveau_diffusion_agent"]
        r["acces"]["niveaux"] = [n for n in r["acces"]["niveaux"] if n["id"] == lvl]
        r["acces"]["niveau_par_defaut"] = lvl
        r["acces"]["regles"] = []
    yield "S", "risque_eleve_un_seul_niveau", "-", "IP5", mut(high_one_level), None
    for i, c in enumerate(raw["surete"].get("contraintes", [])):
        yield "S", "contrainte_sans_motif", c["id"], "IP6", mut(lambda r, i=i: r["surete"]["contraintes"][i].__setitem__("motifs", [])), None
        yield "S", "contrainte_sans_description", c["id"], "IP6", mut(lambda r, i=i: r["surete"]["contraintes"][i].pop("description")), None
    for i, rule in enumerate(raw.get("regles", [])):
        tag = f"{rule['id']}#{i}"
        yield "S", "regle_sans_description", tag, "IP6", mut(lambda r, i=i: r["regles"][i].pop("description")), None
        yield "S", "regle_sans_identifiant", tag, "IP6", mut(lambda r, i=i: r["regles"][i].pop("id")), None
        yield "S", "regle_predicat_inconnu", tag, "coherence", mut(lambda r, i=i: r["regles"][i]["si"].__setitem__("predicat", ["predicatInexistant"])), None
        yield "S", "regle_dimension_non_declaree", tag, "coherence", mut(lambda r, i=i: r["regles"][i]["si"].setdefault("portee", {}).__setitem__("dimensionInexistante", ["x"])), None
        yield "S", "regle_classe_inconnue", tag, "coherence", mut(lambda r, i=i: r["regles"][i]["si"].__setitem__("classe_sujet", ["ClasseInexistante"])), None
    for i, rule in enumerate(raw["acces"].get("regles", [])):
        yield "S", "regle_acces_niveau_inconnu", rule["id"], "coherence", mut(lambda r, i=i: r["acces"]["regles"][i].__setitem__("niveau", "inexistant")), None
        yield "S", "regle_acces_sans_description", rule["id"], "IP6", mut(lambda r, i=i: r["acces"]["regles"][i].pop("description")), None
    yield "S", "defaut_non_declare", "-", "coherence", mut(lambda r: r["acces"].__setitem__("niveau_par_defaut", "inexistant")), None
    yield "S", "variante_classe_inconnue", "-", "coherence", mut(lambda r: r["variantes"].__setitem__("classe", "ClasseInexistante")), None
    yield "S", "variante_relation_inconnue", "-", "coherence", mut(lambda r: r["variantes"].__setitem__("predicat", "relationInexistante")), None
    for mpath, m in _mappings(p):
        for si, subj in enumerate(m.get("subjects", [])):
            for fi, fact in enumerate(subj.get("facts", [])):
                tag = f"{mpath.stem}:{si}.{fi}"
                mm = copy.deepcopy(m); mm["subjects"][si]["facts"][fi]["predicate"] = "predicatInexistant"
                yield "S", "correspondance_predicat_inconnu", tag, "coherence", copy.deepcopy(raw), (mpath.name, mm)
                if fact.get("object_class"):
                    mm = copy.deepcopy(m); mm["subjects"][si]["facts"][fi]["object_class"] = "ClasseInexistante"
                    yield "S", "correspondance_classe_inconnue", tag, "coherence", copy.deepcopy(raw), (mpath.name, mm)
            mm = copy.deepcopy(m); mm["subjects"][si]["class"] = "ClasseInexistante"
            yield "S", "correspondance_sujet_inconnu", f"{mpath.stem}:{si}", "coherence", copy.deepcopy(raw), (mpath.name, mm)
        for key in m.get("scope", {}):
            mm = copy.deepcopy(m); mm["scope"]["x_" + key] = mm["scope"].pop(key)
            yield "S", "correspondance_dimension_non_declaree", f"{mpath.stem}:{key}", "coherence", copy.deepcopy(raw), (mpath.name, mm)

    # --- P : erreurs sémantiques plausibles (hors de portée de la vérification) ---
    for i, rule in enumerate(raw.get("regles", [])):
        tag = f"{rule['id']}#{i}"
        def typo(r, i=i):
            for dim, vals in r["regles"][i]["si"].get("portee", {}).items():
                r["regles"][i]["si"]["portee"][dim] = [v[:-1] + "x" for v in vals]
        yield "P", "regle_valeur_mal_orthographiee", tag, "aucun", mut(typo), None
        if rule["si"].get("objet"):
            yield "P", "regle_objet_permute", tag, "aucun", mut(lambda r, i=i: r["regles"][i]["si"].__setitem__("objet", ["Inconnu"] if False else list(reversed(r["regles"][i]["si"]["objet"])) + ["Autre"])), None
    for i, c in enumerate(raw["surete"].get("contraintes", [])):
        yield "P", "motif_de_surete_inoperant", c["id"], "aucun", mut(lambda r, i=i: r["surete"]["contraintes"][i].__setitem__("motifs", ["(?!x)x"])), None
    if raw["acces"].get("regles"):
        yield "P", "regles_acces_supprimees", "-", "aucun", mut(lambda r: r["acces"].__setitem__("regles", [])), None
    if len(raw["acces"]["niveaux"]) > 1:
        low = min(raw["acces"]["niveaux"], key=lambda n: n.get("rang", 0))["id"]
        yield "P", "defaut_abaisse", "-", "aucun", mut(lambda r: r["acces"].__setitem__("niveau_par_defaut", low)), None


def check(p: Profile, raw: dict, mapping: tuple[str, dict] | None) -> list[str]:
    q = Profile(p.id, raw, p.directory)
    if mapping is None:
        return profile_check.check_invariants(q) + profile_check.check_consistency(q)
    # Correspondance mutée : écrite dans un répertoire temporaire qui remplace celui du profil.
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(p.directory, tmp / p.id)
    (tmp / p.id / "correspondances" / mapping[0]).write_text(json.dumps(mapping[1], ensure_ascii=False), encoding="utf-8")
    q = Profile(p.id, raw, tmp / p.id)
    out = profile_check.check_invariants(q) + profile_check.check_consistency(q)
    shutil.rmtree(tmp)
    return out


def main():
    OUT.mkdir(exist_ok=True)
    rows = []
    for pid in ("ndab", "afripharm"):
        p = load_profile(pid)
        baseline = profile_check.check(pid)
        rows.append({"profil": pid, "famille": "V", "operateur": "profil_valide", "cible": "-", "attendu": "aucun",
                     "detecte": bool(baseline), "messages": " | ".join(baseline)})
        for fam, op, target, expected, raw, mapping in mutants(p):
            issues = check(p, raw, mapping)
            rows.append({"profil": pid, "famille": fam, "operateur": op, "cible": target, "attendu": expected,
                         "detecte": bool(issues), "messages": " | ".join(issues)})
    with open(OUT / "mutation.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)

    summary = {"total": len(rows), "par_famille": {}, "par_operateur": {}, "non_detectes_S": []}
    for fam in ("V", "S", "P"):
        sub = [r for r in rows if r["famille"] == fam]
        summary["par_famille"][fam] = {"mutants": len(sub), "detectes": sum(r["detecte"] for r in sub)}
    ops = defaultdict(lambda: Counter())
    for r in rows:
        if r["famille"] in ("S", "P"):
            ops[(r["famille"], r["operateur"], r["attendu"])]["total"] += 1
            ops[(r["famille"], r["operateur"], r["attendu"])]["detectes"] += int(r["detecte"])
    summary["par_operateur"] = [{"famille": f, "operateur": o, "invariant": e, **c} for (f, o, e), c in sorted(ops.items())]
    def right_reason(r):
        msgs = [m for m in r["messages"].split(" | ") if m]
        if r["attendu"] == "coherence":
            return any(not m.startswith("IP") for m in msgs)
        return any(m.startswith(r["attendu"]) for m in msgs)
    s_rows = [r for r in rows if r["famille"] == "S"]
    summary["S_bonne_raison"] = sum(right_reason(r) for r in s_rows)
    summary["S_mauvaise_raison"] = [f"{r['profil']}:{r['operateur']}:{r['cible']} -> {r['messages']}" for r in s_rows if r["detecte"] and not right_reason(r)]
    summary["operateurs_distincts"] = {"S": len({r["operateur"] for r in s_rows}), "P": len({r["operateur"] for r in rows if r["famille"] == "P"})}
    summary["non_detectes_S"] = [f"{r['profil']}:{r['operateur']}:{r['cible']}" for r in rows if r["famille"] == "S" and not r["detecte"]]
    (OUT / "mutation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("total", "par_famille", "operateurs_distincts", "S_bonne_raison", "S_mauvaise_raison", "non_detectes_S")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
