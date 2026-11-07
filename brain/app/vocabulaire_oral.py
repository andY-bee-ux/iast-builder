"""app/vocabulaire_oral.py — vocabulaire du domaine pour la reconnaissance vocale.

Whisper ne connaît pas les noms propres d'un domaine (« Ndab », « Mekat », « Bangangté ») et les
remplace par des mots qui sonnent pareil. faster-whisper accepte une liste de termes à privilégier
(paramètre hotwords) : on la construit ici à partir du profil actif, sans liste à tenir à la main.

Sources, par ordre de priorité :
1. le vocabulaire déclaré par le profil (profile.json, clé voix.vocabulaire), pour les termes que
   l'extraction ne trouve pas seule (expressions en minuscules comme « ngon là' ») ;
2. le nom de l'agent ;
3. les noms propres trouvés dans le profil et son ontologie : mots écrits avec une majuscule
   ailleurs qu'en début de phrase, et jamais en minuscule (« Effet » / « effet » est écarté).
   Ils sont classés par le nombre de sections où ils apparaissent, puis par fréquence : un terme
   central (« Ndab », « Bangangté ») passe avant un nom qui ne figure que dans un répertoire.

La liste est courte (MAX_TERMES) : Whisper la reçoit comme une invite de quelques centaines de jetons
au plus, et une liste trop longue finit par orienter la transcription vers des mots non prononcés.
"""
import json
import logging
import re
from collections import Counter
from functools import lru_cache

from . import profile as profile_mod

log = logging.getLogger(__name__)

MAX_TERMES = 30
# Clés techniques de l'ontologie (identifiants, types, chemins) : leurs valeurs ne sont pas du texte.
CLES_IGNOREES = {"id", "parent", "domaine", "portee", "type", "classe", "fichier", "espace_de_noms", "code", "cle"}
MOT = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", re.UNICODE)
DEBUT_DE_PHRASE = re.compile(r"(?:^|[.!?:;«\"(\n]\s*)$")
CAMEL_CASE = re.compile(r"[a-zà-ÿ][A-ZÀ-Þ]")   # identifiants (NdabDeMekat) : pas des mots prononcés
# Mots-clés des règles et des balises du prompt, écrits en capitales.
MOTS_CLES = {"SI", "ALORS", "SINON", "ET", "OU", "NON", "IF", "THEN", "AND", "OR", "NOT", "SIGNAL", "EMOTION"}


def _chaines(x):
    if isinstance(x, dict):
        for k, v in x.items():
            if k not in CLES_IGNOREES:
                yield from _chaines(v)
    elif isinstance(x, list):
        for v in x:
            yield from _chaines(v)
    elif isinstance(x, str) and not x.startswith(("http://", "https://")):
        yield x


def _sections(doc: dict, prefixe: str):
    """(section, texte) pour chaque chaîne d'un document, la section étant sa clé de premier niveau."""
    for cle, valeur in doc.items():
        if cle not in CLES_IGNOREES:
            for s in _chaines(valeur):
                yield f"{prefixe}:{cle}", s


def noms_propres(textes) -> list[str]:
    """textes : couples (section, texte)."""
    frequence, sections, minuscule = Counter(), {}, set()
    for section, s in textes:
        for m in MOT.finditer(s):
            w = m.group()
            if len(w) < 3 or CAMEL_CASE.search(w) or w in MOTS_CLES:
                continue
            if not w[0].isupper():
                minuscule.add(w.lower())
            elif not DEBUT_DE_PHRASE.search(s[:m.start()]):
                frequence[w] += 1
                sections.setdefault(w, set()).add(section)
    candidats = [w for w in frequence if w.lower() not in minuscule]
    return sorted(candidats, key=lambda w: (-len(sections[w]), -frequence[w], w))


def construire(p) -> list[str]:
    raw = p.raw
    textes = list(_sections(raw, "profil"))
    try:
        if p.ontology_file.suffix == ".json":
            textes += list(_sections(json.loads(p.ontology_file.read_text(encoding="utf-8")), "ontologie"))
    except (KeyError, OSError, ValueError):
        log.warning("Ontologie illisible pour le vocabulaire oral du profil %s", p.id)
    declares = raw.get("voix", {}).get("vocabulaire", [])
    noms = [raw.get("agent", {}).get("nom", "")]
    termes, vus = [], set()
    for t in [*declares, *noms, *noms_propres(textes)]:
        t = t.strip()
        if t and t.lower() not in vus:
            vus.add(t.lower())
            termes.append(t)
    return termes[:MAX_TERMES]


@lru_cache(maxsize=1)
def termes() -> tuple[str, ...]:
    """Termes du profil actif (vide si le profil ne peut être lu)."""
    try:
        liste = construire(profile_mod.active())
    except Exception:
        log.exception("Vocabulaire oral indisponible : transcription sans termes privilégiés")
        return ()
    log.info("Vocabulaire oral (%d termes) : %s", len(liste), ", ".join(liste))
    return tuple(liste)


def hotwords() -> str | None:
    """Forme attendue par faster-whisper : une seule chaîne (None si aucun terme)."""
    return ", ".join(termes()) or None
