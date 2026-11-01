"""app/instance.py — lien entre un répertoire de données et le profil qu'il sert.

Un répertoire de données (base, journal, ontologie active, versions, documents) appartient à un seul
profil de domaine. Au premier démarrage, le moteur y inscrit ce profil (fichier instance.json). Aux
démarrages suivants, il refuse de servir un autre profil avec ce répertoire : sans cette garde, une
erreur de configuration peut installer l'ontologie d'un domaine dans le répertoire d'un autre, et
toutes les connaissances importées ensuite y seraient jugées hors ontologie.

Pour un répertoire créé avant l'introduction de cette marque, le moteur compare les classes de
l'ontologie qu'il contient à celles de l'ontologie initiale du profil : une ontologie qui ne partage
pas au moins la moitié des classes du profil est réputée appartenir à un autre domaine.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import db
from .profile import Profile

MARKER = "instance.json"
MIN_OVERLAP = 0.5


class InstanceMismatch(RuntimeError):
    pass


def _profile_classes(profile: Profile) -> set[str]:
    f = profile.ontology_file
    if f.suffix != ".json" or not f.exists():
        return set()
    return {c["id"] for c in json.loads(f.read_text(encoding="utf-8")).get("classes", [])}


def check_or_bind(profile: Profile, data_dir: Path, active_classes: set[str] | None) -> str:
    """Vérifie que data_dir appartient à profile, ou l'y rattache. Renvoie « rattache », « verifie »
    ou « marque_ajoutee ». Lève InstanceMismatch si le répertoire appartient à un autre profil."""
    marker = data_dir / MARKER
    if marker.exists():
        owner = json.loads(marker.read_text(encoding="utf-8")).get("profil")
        if owner != profile.id:
            raise InstanceMismatch(
                f"Le répertoire de données {data_dir} appartient au profil « {owner} » ; il ne peut pas servir "
                f"le profil « {profile.id} ». Lancez chaque profil avec son propre répertoire (start.sh le fait "
                f"automatiquement), ou supprimez ce répertoire s'il ne contient que des essais.")
        return "verifie"
    status = "rattache"
    if active_classes:
        expected = _profile_classes(profile)
        if expected:
            overlap = len(expected & active_classes) / len(expected)
            if overlap < MIN_OVERLAP:
                raise InstanceMismatch(
                    f"Le répertoire de données {data_dir} contient une ontologie qui ne correspond pas au profil "
                    f"« {profile.id} » ({overlap:.0%} de ses classes seulement). Il a sans doute été créé pour un autre "
                    f"profil. Supprimez-le s'il ne contient que des essais : il sera recréé au prochain démarrage.")
        status = "marque_ajoutee"
    marker.write_text(json.dumps({"profil": profile.id, "moteur": "IAST-Builder", "cree_le": db.now_iso()},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    return status
