"""evaluation/etude/carnet.py — carnet d'étude pour l'évaluation d'instanciation (volet 3).

Petit serveur local, sans dépendance au-delà de la bibliothèque standard, qui accompagne le
participant pendant la tâche et enregistre les données de l'étude dans
evaluation/etude/donnees/<participant>.jsonl, un événement par ligne :

  session_debut / session_fin   identifiant, profil du participant, empreinte du code du moteur ;
  etape_debut / etape_fin       horodatage de chaque étape de la tâche ;
  pause / reprise               interruptions, déduites des temps ;
  verification                  chaque passage du vérificateur : conformité, nombre et texte des problèmes ;
  difficulte                    difficulté notée par le participant, rattachée à l'étape en cours ;
  questionnaire                 réponses au questionnaire final (SUS et items propres à l'étude) ;
  mesures_finales               taille du profil et de l'ontologie produits, intégrité du moteur.

Usage (depuis brain/) : .venv/bin/python -m evaluation.etude.carnet [port]      puis http://localhost:3900
Aucune donnée ne quitte le poste. Les identifiants de participants sont des codes (P01, P02...).
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[2]
ROOT = BRAIN.parent
DATA = Path(__file__).resolve().parent / "donnees"
DATA.mkdir(exist_ok=True)

ETAPES = [
    ("E1", "Prise en main"), ("E2", "Ontologie initiale"), ("E3", "Profil"), ("E4", "Règles"),
    ("E5", "Correspondance"), ("E6", "Vérification et démarrage"), ("E7", "Import"),
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def engine_fingerprint() -> dict:
    """Empreinte du code du moteur : un changement entre le début et la fin signale une modification du code."""
    files = sorted(list((BRAIN / "app").rglob("*.py")) + list((ROOT / "gateway" / "src").rglob("*.ts"))
                   + list((ROOT / "gateway" / "public" / "js").glob("*.js")))
    h = hashlib.sha256()
    lines = 0
    for f in files:
        data = f.read_bytes()
        h.update(f.relative_to(ROOT).as_posix().encode()); h.update(data)
        lines += data.count(b"\n")
    return {"sha256": h.hexdigest(), "fichiers": len(files), "lignes": lines}


def profile_metrics(pid: str) -> dict:
    d = BRAIN / "profiles" / pid
    out: dict = {"profil": pid, "existe": (d / "profile.json").exists()}
    if not out["existe"]:
        return out
    out["lignes_profil"] = (d / "profile.json").read_text(encoding="utf-8").count("\n") + 1
    try:
        prof = json.loads((d / "profile.json").read_text(encoding="utf-8"))
        onto_file = d / prof.get("ontologie", {}).get("fichier", "ontologie_initiale.json")
        onto = json.loads(onto_file.read_text(encoding="utf-8"))
        out.update(classes=len(onto.get("classes", [])), relations=len(onto.get("proprietes_objet", [])),
                   attributs=len(onto.get("proprietes_donnees", [])), dimensions=len(prof.get("portee", [])),
                   regles=len(prof.get("regles", [])), regles_acces=len(prof.get("acces", {}).get("regles", [])),
                   niveaux=len(prof.get("acces", {}).get("niveaux", [])),
                   lignes_ontologie=onto_file.read_text(encoding="utf-8").count("\n") + 1)
    except Exception as exc:   # profil incomplet : on enregistre ce qui est lisible
        out["erreur"] = str(exc)
    maps = list((d / "correspondances").glob("*.json")) if (d / "correspondances").exists() else []
    out["correspondances"] = len(maps)
    out["lignes_correspondances"] = sum(m.read_text(encoding="utf-8").count("\n") + 1 for m in maps)
    return out


def record(participant: str, event: dict) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", participant or ""):
        raise ValueError("Identifiant de participant invalide (lettres, chiffres, tirets ; ex. P01).")
    event = {"horodatage": now(), "t": round(time.time(), 1), **event}
    with open(DATA / f"{participant}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def run_check(pid: str) -> dict:
    if not re.fullmatch(r"[a-z0-9_-]{1,40}", pid or ""):
        return {"conforme": False, "problemes": ["Identifiant de profil invalide."], "sortie": ""}
    py = BRAIN / ".venv" / "bin" / "python"
    started = time.time()
    proc = subprocess.run([str(py if py.exists() else sys.executable), "-m", "app.profile_check", pid],
                          cwd=BRAIN, capture_output=True, text=True, timeout=120)
    out = (proc.stdout + proc.stderr).strip()
    problems = [l.strip()[2:] for l in out.splitlines() if l.strip().startswith("- ")]
    if proc.returncode != 0 and not problems:
        problems = [out.splitlines()[-1] if out else "Erreur inconnue"]
    return {"conforme": proc.returncode == 0, "problemes": problems, "sortie": out[-4000:], "duree_s": round(time.time() - started, 1)}


PAGE = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Carnet d'étude IAST-Builder</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:880px;margin:24px auto;padding:0 16px;color:#1d2433;background:#fafaf7}
 h1{font-size:22px;margin-bottom:4px} h2{font-size:17px;margin-top:28px;border-bottom:1px solid #ddd;padding-bottom:4px}
 .muted{color:#667;font-size:13px} .card{background:#fff;border:1px solid #e3e3dc;border-radius:8px;padding:12px 14px;margin:10px 0}
 .row{display:flex;align-items:center;gap:10px;justify-content:space-between} button{padding:6px 12px;border:1px solid #9a7b3f;background:#fff;border-radius:6px;cursor:pointer}
 button.primary{background:#9a7b3f;color:#fff} button:disabled{opacity:.4;cursor:default} input[type=text],textarea,select{width:100%;padding:6px;border:1px solid #ccc;border-radius:6px;font:inherit}
 .ok{color:#17713a} .ko{color:#a3261b} pre{white-space:pre-wrap;background:#f3f3ee;padding:8px;border-radius:6px;font-size:12.5px}
 .likert{display:flex;gap:14px;margin:4px 0 10px} .hidden{display:none} .state{font-variant-numeric:tabular-nums;font-size:13px;color:#445}
</style></head><body>
<h1>Carnet d'étude : instanciation d'IAST-Builder</h1>
<p class="muted">Vos temps, vos vérifications et vos remarques sont enregistrés sur ce poste uniquement, sous votre code de participant.</p>

<div id="start" class="card">
 <label>Code de participant (fourni par l'équipe, par ex. P01)<input type="text" id="pid"></label>
 <p><label>Formation principale <select id="formation"><option>Informatique</option><option>Sciences de l'information</option><option>Sciences humaines et sociales</option><option>Autre</option></select></label></p>
 <p><label>Expérience des ontologies <select id="exp"><option>Aucune</option><option>Moins d'un an</option><option>Un à trois ans</option><option>Plus de trois ans</option></select></label></p>
 <p><label>Familiarité avec le format JSON <select id="json"><option>Aucune</option><option>Faible</option><option>Bonne</option><option>Très bonne</option></select></label></p>
 <p><label><input type="checkbox" id="consent"> J'ai lu le formulaire d'information et de consentement et j'accepte de participer.</label></p>
 <button class="primary" onclick="startSession()">Commencer la session</button>
</div>

<div id="main" class="hidden">
 <h2>Étapes</h2>
 <div id="steps"></div>

 <h2>Vérifier mon profil</h2>
 <div class="card">
  <div class="row"><input type="text" id="profil" value="toponymie" style="max-width:220px"><button class="primary" onclick="verify()">Vérifier mon profil</button></div>
  <div id="verif" class="muted">Aucune vérification pour l'instant.</div>
 </div>

 <h2>Noter une difficulté</h2>
 <div class="card">
  <textarea id="diff" rows="3" placeholder="Ce qui vous bloque ou vous surprend, même brièvement"></textarea>
  <p><button onclick="difficulty()">Enregistrer la difficulté</button> <span id="diffok" class="muted"></span></p>
 </div>

 <h2>Questionnaire final</h2>
 <div class="card" id="questionnaire"></div>
 <p><button class="primary" onclick="finish()">Envoyer le questionnaire et terminer la session</button> <span id="endmsg" class="muted"></span></p>
</div>

<script>
const ETAPES = __ETAPES__;
const SUS = ["Je pense que j'aimerais utiliser cet outil fréquemment.","J'ai trouvé cet outil inutilement complexe.",
 "J'ai trouvé cet outil facile à utiliser.","Je pense que j'aurais besoin de l'aide d'une personne technique pour pouvoir utiliser cet outil.",
 "J'ai trouvé que les différentes fonctions de cet outil étaient bien intégrées.","J'ai trouvé qu'il y avait trop d'incohérences dans cet outil.",
 "J'imagine que la plupart des gens apprendraient très rapidement à utiliser cet outil.","J'ai trouvé cet outil très contraignant à utiliser.",
 "Je me suis senti·e très en confiance en utilisant cet outil.","J'ai dû apprendre beaucoup de choses avant de pouvoir utiliser cet outil."];
const SPEC = ["Les messages du vérificateur m'ont permis de corriger mon profil sans aide.","Les deux profils existants m'ont servi de modèles utiles.",
 "J'ai compris ce qu'est une dimension de portée et comment la choisir.","J'ai compris comment traduire une règle du domaine en règle contrôlée.",
 "Je me sentirais capable d'instancier seul·e un autre domaine.","Les contraintes imposées par l'outil me semblent justifiées pour un savoir traditionnel."];
const OPEN = ["Qu'est-ce qui a été le plus difficile ?","Que manque-t-il à la documentation ?","Autres remarques"];
let pid = null, current = null, startedAt = {}, total = {};

async function post(url, body){ const r = await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}); return r.json(); }
function fmt(s){ s=Math.round(s); return Math.floor(s/60)+" min "+String(s%60).padStart(2,"0")+" s"; }

async function startSession(){
  const id = document.getElementById("pid").value.trim();
  if(!/^[A-Za-z0-9_-]{1,20}$/.test(id)){ alert("Code de participant invalide."); return; }
  if(!document.getElementById("consent").checked){ alert("Le consentement est nécessaire pour participer."); return; }
  const r = await post("/api/session",{participant:id, formation:document.getElementById("formation").value,
    experience_ontologies:document.getElementById("exp").value, familiarite_json:document.getElementById("json").value});
  if(r.erreur){ alert(r.erreur); return; }
  pid = id; document.getElementById("start").classList.add("hidden"); document.getElementById("main").classList.remove("hidden"); render(); renderQ();
}
function render(){
  document.getElementById("steps").innerHTML = ETAPES.map(([id,lab]) => `<div class="card row"><div><strong>${id}. ${lab}</strong>
    <div class="state" id="st-${id}">${current===id?"en cours":""} ${total[id]?("· "+fmt(total[id])):""}</div></div>
    <div><button onclick="begin('${id}')" ${current?"disabled":""}>Commencer</button>
    <button onclick="pause('${id}')" ${current!==id?"disabled":""}>Pause</button>
    <button class="primary" onclick="end('${id}')" ${current!==id?"disabled":""}>Terminer</button></div></div>`).join("");
}
async function begin(id){ await post("/api/evenement",{participant:pid,type:"etape_debut",etape:id}); current=id; startedAt[id]=Date.now(); render(); }
async function pause(id){ await post("/api/evenement",{participant:pid,type:"pause",etape:id}); total[id]=(total[id]||0)+(Date.now()-startedAt[id])/1000; current=null; render(); }
async function end(id){ await post("/api/evenement",{participant:pid,type:"etape_fin",etape:id}); total[id]=(total[id]||0)+(Date.now()-startedAt[id])/1000; current=null; render(); }
async function verify(){
  const p = document.getElementById("profil").value.trim(); document.getElementById("verif").textContent = "Vérification en cours…";
  const r = await post("/api/verifier",{participant:pid, profil:p, etape:current});
  document.getElementById("verif").innerHTML = r.conforme ? '<span class="ok">Profil conforme au métamodèle.</span>'
    : '<span class="ko">'+r.problemes.length+' problème(s) :</span><pre>'+r.problemes.map(x=>"• "+x).join("\n")+'</pre>';
}
async function difficulty(){
  const t = document.getElementById("diff").value.trim(); if(!t) return;
  await post("/api/evenement",{participant:pid,type:"difficulte",etape:current,texte:t});
  document.getElementById("diff").value=""; document.getElementById("diffok").textContent="Enregistrée.";
  setTimeout(()=>document.getElementById("diffok").textContent="",2000);
}
function likert(name,label){ return `<div>${label}</div><div class="likert">${[1,2,3,4,5].map(v=>`<label><input type="radio" name="${name}" value="${v}"> ${v}</label>`).join("")}</div>`; }
function renderQ(){
  document.getElementById("questionnaire").innerHTML = '<p class="muted">De 1 (pas du tout d\'accord) à 5 (tout à fait d\'accord).</p>'
   + SUS.map((q,i)=>likert("sus"+(i+1),(i+1)+". "+q)).join("") + "<hr>"
   + SPEC.map((q,i)=>likert("spec"+(i+1),"S"+(i+1)+". "+q)).join("") + "<hr>"
   + OPEN.map((q,i)=>`<label>${q}<textarea id="open${i+1}" rows="3"></textarea></label>`).join("<br>");
}
async function finish(){
  if(current){ alert("Terminez d'abord l'étape en cours."); return; }
  const val = n => { const e=document.querySelector(`input[name=${n}]:checked`); return e?Number(e.value):null; };
  const rep = {sus:SUS.map((_,i)=>val("sus"+(i+1))), specifiques:SPEC.map((_,i)=>val("spec"+(i+1))),
               ouvertes:OPEN.map((_,i)=>document.getElementById("open"+(i+1)).value.trim())};
  if(rep.sus.includes(null)){ if(!confirm("Certaines questions SUS sont sans réponse. Terminer quand même ?")) return; }
  const r = await post("/api/fin",{participant:pid, reponses:rep, profil:document.getElementById("profil").value.trim()});
  document.getElementById("endmsg").textContent = r.erreur ? r.erreur : "Session terminée. Merci de votre participation.";
}
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.replace("__ETAPES__", json.dumps(ETAPES, ensure_ascii=False)).encode(), "text/html; charset=utf-8")
        else:
            self._send(404, b"{}")

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            pid = body.get("participant", "")
            if self.path == "/api/session":
                record(pid, {"type": "session_debut", "formation": body.get("formation"),
                             "experience_ontologies": body.get("experience_ontologies"),
                             "familiarite_json": body.get("familiarite_json"), "moteur": engine_fingerprint()})
                out = {"ok": True}
            elif self.path == "/api/evenement":
                if body.get("type") not in {"etape_debut", "etape_fin", "pause", "difficulte"}:
                    raise ValueError("Type d'événement inconnu.")
                record(pid, {k: body.get(k) for k in ("type", "etape", "texte") if body.get(k) is not None})
                out = {"ok": True}
            elif self.path == "/api/verifier":
                res = run_check(body.get("profil", ""))
                record(pid, {"type": "verification", "etape": body.get("etape"), "profil": body.get("profil"),
                             "conforme": res["conforme"], "nombre_problemes": len(res["problemes"]),
                             "problemes": res["problemes"], "duree_s": res.get("duree_s")})
                out = res
            elif self.path == "/api/fin":
                record(pid, {"type": "questionnaire", **body.get("reponses", {})})
                record(pid, {"type": "mesures_finales", "moteur": engine_fingerprint(),
                             "profil": profile_metrics(body.get("profil") or "toponymie")})
                record(pid, {"type": "session_fin"})
                out = {"ok": True}
            else:
                self._send(404, b"{}"); return
            self._send(200, json.dumps(out, ensure_ascii=False).encode())
        except Exception as exc:
            self._send(400, json.dumps({"erreur": str(exc)}, ensure_ascii=False).encode())


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3900
    print(f"Carnet d'étude : http://localhost:{port}   (données : {DATA})   Arrêt : Ctrl+C")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
