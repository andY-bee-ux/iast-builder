"""app/profile.py — profil de domaine : tout ce qui, dans le moteur, dépend du savoir traité.

Le moteur IAST-Builder ne mentionne aucun domaine. Chaque savoir est décrit par un profil,
fichier déclaratif profiles/<id>/profile.json, qui instancie les points de
variation du métamodèle (metamodele/iast-builder-metamodele.ttl) :

    agent          identité de l'agent, consignes propres au domaine, exemple de signal
    ontologie      fichier de l'ontologie initiale, espace de noms, collecte d'origine
    portee         dimensions de portée et leurs libellés
    regles         règles contrôlées : conditions qui placent une assertion en tension
    acces          niveaux d'accès, niveau par défaut, niveau de diffusion de l'agent,
                   règles qui attribuent un niveau d'office
    surete         niveau de risque, contraintes de sûreté (motifs interdits), consigne
    variantes      classe dont les formes varient et relation de variante ;
                   relation de désignation pour la détection des polysémies
    glossaire      langue du glossaire (nom et code ISO 639-3)
    restitution    exemples de reformulation propres au domaine
    contributions  types de contributions proposés aux usagers
    interface      textes de la page de conversation, suggestions, outils propres
    autorite       instance de validation

Le profil actif est désigné par la variable d'environnement YOBAKOKO_PROFILE
(défaut : ndab). Il est vérifié contre les invariants du métamodèle avant tout
chargement (app/profile_check.py).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .text_utils import normalize_form

BRAIN_DIR = Path(__file__).resolve().parent.parent
PROFILES_DIR = Path(os.getenv("YOBAKOKO_PROFILES_DIR", BRAIN_DIR / "profiles"))


@dataclass
class Condition:
    """Condition déclarative sur une assertion. Tous les critères renseignés doivent être satisfaits.

    predicat : liste de prédicats admis ; objet : liste d'objets admis ; sujet : liste de sujets
    admis ; classe_sujet : liste de classes ; portee : {dimension: [valeurs]} (comparaison sur
    formes normalisées ; une assertion satisfait le critère si sa portée prend l'une des valeurs)."""
    predicat: list[str] = field(default_factory=list)
    objet: list[str] = field(default_factory=list)
    sujet: list[str] = field(default_factory=list)
    classe_sujet: list[str] = field(default_factory=list)
    portee: dict[str, list[str]] = field(default_factory=dict)

    @staticmethod
    def from_dict(d: dict) -> "Condition":
        return Condition(d.get("predicat", []), d.get("objet", []), d.get("sujet", []),
                         d.get("classe_sujet", []), d.get("portee", {}))

    def matches(self, a: dict) -> bool:
        def norm_set(values) -> set[str]:
            vals = values if isinstance(values, list) else [values]
            return {normalize_form(str(v)) for v in vals if v not in (None, "")}

        if self.predicat and a.get("predicate") not in self.predicat:
            return False
        if self.objet and normalize_form(a.get("object", "")) not in norm_set(self.objet):
            return False
        if self.sujet and normalize_form(a.get("subject", "")) not in norm_set(self.sujet):
            return False
        if self.classe_sujet and a.get("subject_class") not in self.classe_sujet:
            return False
        scope = a.get("scope") or {}
        for dim, wanted in self.portee.items():
            if not (norm_set(scope.get(dim)) & norm_set(wanted)):
                return False
        return True


@dataclass
class Profile:
    id: str
    raw: dict
    directory: Path

    # --- accès simples ---------------------------------------------------------
    @property
    def agent(self) -> dict:
        return self.raw.get("agent", {})

    @property
    def scope_labels(self) -> dict[str, str]:
        return {d["cle"]: d.get("libelle", d["cle"]) for d in self.raw.get("portee", [])}

    @property
    def access_levels(self) -> list[str]:
        return [n["id"] for n in sorted(self.raw.get("acces", {}).get("niveaux", []), key=lambda n: n.get("rang", 0))]

    def access_rank(self, level: str) -> int:
        for n in self.raw.get("acces", {}).get("niveaux", []):
            if n["id"] == level:
                return n.get("rang", 0)
        return 0

    @property
    def default_access(self) -> str:
        return self.raw.get("acces", {}).get("niveau_par_defaut", "public")

    @property
    def agent_access(self) -> str:
        return self.raw.get("acces", {}).get("niveau_diffusion_agent", "public")

    def allowed_levels_for_agent(self) -> list[str]:
        limit = self.access_rank(self.agent_access)
        return [lvl for lvl in self.access_levels if self.access_rank(lvl) <= limit]

    @property
    def variant(self) -> dict:
        return self.raw.get("variantes", {})

    @property
    def glossary(self) -> dict:
        return self.raw.get("glossaire", {})

    @property
    def interface(self) -> dict:
        return self.raw.get("interface", {})

    @property
    def contribution_types(self) -> list[str]:
        return [t["id"] for t in self.raw.get("contributions", {}).get("types", [])] or ["autre"]

    @property
    def ontology_file(self) -> Path:
        return self.directory / self.raw["ontologie"]["fichier"]

    @property
    def namespace(self) -> str:
        return self.raw["ontologie"].get("espace_de_noms", f"http://iast.uqam.ca/{self.id}#")

    @property
    def mappings_dir(self) -> Path:
        return self.directory / "correspondances"

    # --- règles ----------------------------------------------------------------
    def controlled_rules(self) -> list[tuple[dict, Condition]]:
        return [(r, Condition.from_dict(r["si"])) for r in self.raw.get("regles", [])]

    def access_rules(self) -> list[tuple[dict, Condition]]:
        return [(r, Condition.from_dict(r["si"])) for r in self.raw.get("acces", {}).get("regles", [])]

    def access_for(self, a: dict) -> str:
        """Niveau d'accès attribué d'office : le plus restrictif des règles satisfaites."""
        level = self.default_access
        for rule, cond in self.access_rules():
            if cond.matches(a) and self.access_rank(rule["niveau"]) > self.access_rank(level):
                level = rule["niveau"]
        return level

    # --- sûreté ----------------------------------------------------------------
    @property
    def safety(self) -> dict:
        return self.raw.get("surete", {})

    def safety_patterns(self) -> list[tuple[str, re.Pattern]]:
        out = []
        for c in self.safety.get("contraintes", []):
            for m in c.get("motifs", []):
                out.append((c["id"], re.compile(m, re.IGNORECASE)))
        return out


def load_profile(profile_id: str | None = None) -> Profile:
    pid = profile_id or os.getenv("YOBAKOKO_PROFILE", "ndab")
    directory = PROFILES_DIR / pid
    path = directory / "profile.json"
    if not path.exists():
        raise FileNotFoundError(f"Profil de domaine introuvable : {path}")
    return Profile(pid, json.loads(path.read_text(encoding="utf-8")), directory)


@lru_cache(maxsize=1)
def active() -> Profile:
    """Profil actif, chargé une fois par processus."""
    return load_profile()
