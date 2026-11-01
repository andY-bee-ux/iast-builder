"""app/paraphrase.py — paraphrases en français, générées sans modèle de langage.

Principe de la conception : ce que l'expert lit est exactement ce qui sera
appliqué. Les paraphrases sont donc produites par des gabarits déterministes à
partir de la forme formelle (assertion ou opération sur l'ontologie), jamais
par le LLM. Deux formes identiques donnent toujours la même phrase.
"""
from __future__ import annotations

from .ontology_loader import INSTANCE_OF, Vocabulary
from .profile import active as active_profile

# Libellés des dimensions de portée : déclarés par le profil (clé « portee »). À défaut, la clé est affichée.
SCOPE_LABELS: dict[str, str] = {}


def scope_text(scope: dict | None) -> str:
    if not scope:
        return ""
    labels = {**SCOPE_LABELS, **active_profile().scope_labels}
    parts = []
    for k, v in scope.items():
        if v in (None, "", []):
            continue
        val = ", ".join(v) if isinstance(v, list) else str(v)
        parts.append(f"{labels.get(k, k)} {val}")
    return f" (portée : {' ; '.join(parts)})" if parts else ""


def assertion_text(a: dict, vocab: Vocabulary, with_scope: bool = True) -> str:
    """Ex. : « Gooun Taaleeum Baatchoou » est de type « NdabNgonLa » (portée : chefferie Bangangté)."""
    pred = a.get("predicate", "")
    obj = a.get("object", "")
    if pred == INSTANCE_OF:
        core = f"« {a['subject']} » est un(e) {vocab.class_label(obj)}"
    elif a.get("object_is_literal"):
        core = f"« {a['subject']} » — {vocab.predicate_label(pred)} : {obj}"
    else:
        core = f"« {a['subject']} » {vocab.predicate_label(pred)} « {vocab.class_label(obj) if obj in vocab.classes else obj} »"
    return core + (scope_text(a.get("scope")) if with_scope else "")
