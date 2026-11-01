"""evaluation/surete.py — volet 2 (suite) : précision et rappel du filtre de sûreté.

Les phrases de surete_phrases.py sont partagées au hasard (graine fixe) en un ensemble de mise au
point et un ensemble de test, chacun avec la moitié des positifs et des négatifs. Le filtre est
évalué avec les motifs du profil (version initiale), puis, si un fichier de motifs affinés est fourni,
avec ces motifs : l'affinage n'utilise que l'ensemble de mise au point, la comparaison porte sur
l'ensemble de test.

Usage (depuis brain/) : python -m evaluation.surete [motifs_affines.json]
Sortie : evaluation/resultats/surete.json
"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.profile import load_profile  # noqa: E402
from evaluation.surete_phrases import NEGATIFS, POSITIFS  # noqa: E402

OUT = Path(__file__).resolve().parent / "resultats"


def split(items, seed):
    rng = random.Random(seed)
    items = list(items); rng.shuffle(items)
    h = len(items) // 2
    return items[:h], items[h:]


def evaluate(patterns, positives, negatives):
    def hit(s):
        return any(p.search(s) for p in patterns)
    tp = sum(hit(s) for s in positives); fn = len(positives) - tp
    fp = sum(hit(s) for s in negatives); tn = len(negatives) - fp
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {"positifs": len(positives), "negatifs": len(negatives), "vrais_positifs": tp, "faux_negatifs": fn,
            "faux_positifs": fp, "precision": round(precision, 3), "rappel": round(recall, 3),
            "f1": round(2 * precision * recall / (precision + recall), 3) if precision + recall else 0.0,
            "manques": [s for s in positives if not hit(s)], "fausses_alertes": [s for s in negatives if hit(s)]}


def compile_motifs(contraintes):
    return [re.compile(m, re.IGNORECASE) for c in contraintes for m in c["motifs"]]


def main():
    OUT.mkdir(exist_ok=True)
    pos_dev, pos_test = split(POSITIFS, 11)
    neg_dev, neg_test = split(NEGATIFS, 12)
    # Motifs d'origine du profil, figés dans un fichier pour que l'évaluation reste reproductible.
    initial = compile_motifs(json.loads((Path(__file__).resolve().parent / "motifs_initiaux.json").read_text(encoding="utf-8")))
    result = {"taille": {"positifs": len(POSITIFS), "negatifs": len(NEGATIFS)},
              "initial": {"mise_au_point": evaluate(initial, pos_dev, neg_dev), "test": evaluate(initial, pos_test, neg_test)}}
    if len(sys.argv) > 1:
        refined = compile_motifs(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
        result["affine"] = {"mise_au_point": evaluate(refined, pos_dev, neg_dev), "test": evaluate(refined, pos_test, neg_test)}
    (OUT / "surete.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for k in ("initial", "affine"):
        if k in result:
            for part in ("mise_au_point", "test"):
                r = result[k][part]
                print(f"{k:8} {part:14} P={r['precision']:.3f} R={r['rappel']:.3f} F1={r['f1']:.3f}  (VP {r['vrais_positifs']}, FN {r['faux_negatifs']}, FP {r['faux_positifs']})")


if __name__ == "__main__":
    main()
