"""evaluation/etude/analyse.py — analyse des données du carnet d'étude (volet 3).

Pour chaque participant : temps actif par étape (somme des intervalles début-pause/fin), temps total,
nombre de vérifications, nombre de vérifications et temps jusqu'au premier profil conforme,
problèmes par invariant, difficultés par étape, score SUS (Brooke, 1996), items propres à l'étude,
taille de ce qui a été produit et intégrité du moteur (empreinte identique au début et à la fin).

Usage (depuis brain/) : python -m evaluation.etude.analyse
Sorties : evaluation/etude/resultats_participants.csv et resultats_synthese.md
"""
from __future__ import annotations

import csv
import json
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "donnees"
ETAPES = ["E1", "E2", "E3", "E4", "E5", "E6", "E7"]


def sus_score(answers: list) -> float | None:
    if not answers or any(a is None for a in answers) or len(answers) != 10:
        return None
    odd = sum(a - 1 for a in answers[0::2]); even = sum(5 - a for a in answers[1::2])
    return (odd + even) * 2.5


def analyse_participant(path: Path) -> dict:
    events = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    pid = path.stem
    active: dict[str, float] = defaultdict(float)
    open_at: dict[str, float] = {}
    verifs, difficulties = [], Counter()
    invariants = Counter()
    start = next((e for e in events if e["type"] == "session_debut"), {})
    final = next((e for e in events if e["type"] == "mesures_finales"), {})
    quest = next((e for e in events if e["type"] == "questionnaire"), {})
    for e in events:
        t, et = e["t"], e.get("etape")
        if e["type"] == "etape_debut":
            open_at[et] = t
        elif e["type"] in ("pause", "etape_fin") and et in open_at:
            active[et] += t - open_at.pop(et)
        elif e["type"] == "verification":
            verifs.append(e)
            for p in e.get("problemes", []):
                invariants[p.split(" :")[0] if p.startswith("IP") else "coherence"] += 1
        elif e["type"] == "difficulte":
            difficulties[et or "hors étape"] += 1
    first_ok = next((i for i, v in enumerate(verifs) if v["conforme"]), None)
    t0 = start.get("t", events[0]["t"])
    row = {
        "participant": pid,
        "formation": start.get("formation"), "experience_ontologies": start.get("experience_ontologies"),
        "familiarite_json": start.get("familiarite_json"),
        **{f"temps_{e}_min": round(active.get(e, 0) / 60, 1) for e in ETAPES},
        "temps_total_min": round(sum(active.values()) / 60, 1),
        "verifications": len(verifs),
        "verifications_avant_conformite": (first_ok + 1) if first_ok is not None else None,
        "minutes_jusqu_a_conformite": round((verifs[first_ok]["t"] - t0) / 60, 1) if first_ok is not None else None,
        "problemes_par_famille": json.dumps(dict(invariants), ensure_ascii=False),
        "difficultes": sum(difficulties.values()),
        "difficultes_par_etape": json.dumps(dict(difficulties), ensure_ascii=False),
        "sus": sus_score(quest.get("sus", [])),
        **{f"S{i + 1}": v for i, v in enumerate(quest.get("specifiques", []) or [])},
        "moteur_inchange": (start.get("moteur", {}).get("sha256") == final.get("moteur", {}).get("sha256")) if final else None,
    }
    prof = final.get("profil", {})
    for k in ("lignes_profil", "lignes_ontologie", "lignes_correspondances", "classes", "relations", "dimensions", "regles", "regles_acces", "niveaux"):
        row[k] = prof.get(k)
    row["ouvertes"] = json.dumps(quest.get("ouvertes", []), ensure_ascii=False)
    return row


def describe(values):
    v = [x for x in values if isinstance(x, (int, float))]
    if not v:
        return "n.d."
    if len(v) == 1:
        return f"{v[0]}"
    return f"moyenne {st.mean(v):.1f} ; médiane {st.median(v):.1f} ; min {min(v)} ; max {max(v)}"


def main():
    rows = [analyse_participant(p) for p in sorted(DATA.glob("*.jsonl"))]
    if not rows:
        print("Aucune donnée dans", DATA); return
    with open(HERE / "resultats_participants.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    lines = [f"# Synthèse de l'étude d'instanciation ({len(rows)} participant(s))", "", "| Mesure | Résultat |", "| --- | --- |"]
    for label, key in [("Temps total (min)", "temps_total_min"), *[(f"Temps {e} (min)", f"temps_{e}_min") for e in ETAPES],
                       ("Vérifications", "verifications"), ("Vérifications avant le premier profil conforme", "verifications_avant_conformite"),
                       ("Minutes jusqu'au premier profil conforme", "minutes_jusqu_a_conformite"), ("Difficultés notées", "difficultes"),
                       ("Score SUS (0-100)", "sus"), ("Lignes du profil", "lignes_profil"), ("Lignes de l'ontologie", "lignes_ontologie"),
                       ("Lignes des correspondances", "lignes_correspondances"), ("Classes", "classes"), ("Relations", "relations"),
                       ("Dimensions de portée", "dimensions"), ("Règles contrôlées", "regles"), ("Règles d'accès", "regles_acces")]:
        lines.append(f"| {label} | {describe([r.get(key) for r in rows])} |")
    for i in range(1, 7):
        lines.append(f"| Item S{i} (1-5) | {describe([r.get(f'S{i}') for r in rows])} |")
    unchanged = [r["moteur_inchange"] for r in rows if r["moteur_inchange"] is not None]
    lines.append(f"| Moteur inchangé | {sum(unchanged)} sur {len(unchanged)} |")
    fam = Counter()
    for r in rows:
        fam.update(json.loads(r["problemes_par_famille"]))
    lines += ["", "Problèmes signalés par le vérificateur, par invariant : " + (", ".join(f"{k} ({v})" for k, v in fam.most_common()) or "aucun")]
    (HERE / "resultats_synthese.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
