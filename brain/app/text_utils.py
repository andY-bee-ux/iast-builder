"""app/text_utils.py — outils textuels partagés, sans dépendance externe.

- normalize_form : forme canonique d'un nom pour comparer des graphies
  (« Gooun Tchoouh » et « GoounTchoouh » donnent la même clé) ;
- similarity     : ressemblance entre deux formes normalisées (0 à 1) ;
- tokens/jaccard : repli lexical pour regrouper des questions quand le modèle
  d'embeddings n'est pas disponible ;
- anonymize      : retire des extraits de conversation ce qui pourrait identifier
  une personne (courriels, numéros, pseudonymes) avant transmission aux experts.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

_STOPWORDS = {
    "le", "la", "les", "de", "des", "du", "un", "une", "et", "ou", "a", "à", "au", "aux", "en", "dans", "pour", "par",
    "sur", "que", "qui", "quoi", "est", "sont", "ce", "cet", "cette", "ces", "il", "elle", "on", "je", "tu", "nous",
    "vous", "ils", "elles", "se", "sa", "son", "ses", "leur", "leurs", "ne", "pas", "plus", "d", "l", "s", "y",
}


def strip_accents(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def normalize_form(s: str) -> str:
    """Minuscules, sans accents ni espaces ni ponctuation, lettres redoublées réduites."""
    s = strip_accents(s).lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return re.sub(r"(.)\1+", r"\1", s)


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize_form(a), normalize_form(b)).ratio()


def tokens(s: str) -> set[str]:
    words = re.findall(r"[a-z0-9']+", strip_accents(s).lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def jaccard(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?:\+?\d[\d .-]{7,}\d)")
_HANDLE = re.compile(r"@\w{2,}")


def anonymize(text: str, max_len: int = 400) -> str:
    text = _EMAIL.sub("[courriel]", text)
    text = _PHONE.sub("[numéro]", text)
    text = _HANDLE.sub("[pseudonyme]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = sum(x * x for x in a) ** 0.5
    db = sum(y * y for y in b) ** 0.5
    return num / (da * db) if da and db else 0.0


def split_sentences(text: str) -> list[str]:
    """Découpe un texte en phrases en conservant la ponctuation finale."""
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    return [p for p in parts if p.strip()]
