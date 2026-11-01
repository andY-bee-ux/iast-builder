"""Passage du vérificateur sur le profil de l'instanciation de référence, consigné dans un journal."""
import json, subprocess, sys, time
from pathlib import Path
BRAIN = Path(__file__).resolve().parents[1]
out = subprocess.run([sys.executable, "-m", "app.profile_check", "toponymie"], cwd=BRAIN, capture_output=True, text=True)
text = (out.stdout + out.stderr).strip()
problems = [l.strip()[2:] for l in text.splitlines() if l.strip().startswith("- ")]
entry = {"t": round(time.time(), 1), "conforme": out.returncode == 0, "problemes": problems or ([] if out.returncode == 0 else [text.splitlines()[-1]])}
with open(BRAIN / "evaluation" / "resultats" / "instanciation_reference_verifications.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
print(json.dumps(entry, ensure_ascii=False, indent=1))
