"""evaluation/agreger.py — agrégation des lots du volet 2 (un fichier par profil et par graine)."""
import json
from collections import Counter
from pathlib import Path

R = Path(__file__).resolve().parent / "resultats"
synthese = {}
for profil in ("ndab", "afripharm"):
    lots = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(R.glob(f"proprietes_{profil}_*.json"))]
    ops = Counter()
    for l in lots:
        ops.update(l["operations"])
    synthese[profil] = {"lots": len(lots), "graines": [l["graine"] for l in lots],
                        "operations_tirees": sum(l["sequences"] * l["operations_par_sequence"] for l in lots),
                        "duree_s": round(sum(l["duree_s"] for l in lots), 1), "compteurs": dict(ops),
                        "violations": sum(l["nombre_violations"] for l in lots)}
(R / "proprietes_synthese.json").write_text(json.dumps(synthese, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(synthese, ensure_ascii=False, indent=2))
