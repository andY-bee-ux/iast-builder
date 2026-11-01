"""app/crowdsourcing.py — réglages de la collecte communautaire.

Trois modes de collecte, réglables séparément :

    temoignages  recueil des témoignages en conversation : faits nouveaux et contradictions affirmés
                 par un usager, transmis aux experts avec un extrait anonymisé de l'échange ;
    formulaire   contributions volontaires par le formulaire de l'interface (texte ou document) ;
    lacunes      signalement aux experts des lacunes et ambiguïtés détectées par l'agent, sans rien
                 retenir du savoir de l'usager.

Le profil de domaine déclare la valeur par défaut de chaque mode (clé « collecte ») ; un expert peut
la modifier depuis le panneau d'administration. Chaque changement est inscrit au journal avec son
auteur et son motif. Aucun réglage ne touche au circuit de validation : ce qui est recueilli reste
soumis à la décision des experts.
"""
from __future__ import annotations

from . import db, journal
from .profile import active as active_profile

MODES = ("temoignages", "formulaire", "lacunes")
LABELS = {
    "temoignages": "Recueil des témoignages en conversation",
    "formulaire": "Formulaire de contribution",
    "lacunes": "Signalement des lacunes et ambiguïtés",
}
# Types de signaux relevant de chaque mode.
SIGNAL_MODE = {"nouveaute": "temoignages", "contradiction": "temoignages", "lacune": "lacunes", "ambiguite": "lacunes"}


def defaults() -> dict[str, bool]:
    declared = active_profile().raw.get("collecte", {})
    return {m: bool(declared.get(m, True)) for m in MODES}


def state() -> dict[str, bool]:
    """Réglage en vigueur : valeur fixée par un expert, à défaut valeur déclarée par le profil."""
    current = defaults()
    for row in db.fetch_all("SELECT key, value FROM settings WHERE key LIKE 'collecte.%'"):
        mode = row["key"].split(".", 1)[1]
        if mode in current:
            current[mode] = row["value"] == "1"
    return current


def is_active(mode: str) -> bool:
    return state().get(mode, True)


def signal_transmitted(signal_type: str) -> bool:
    return is_active(SIGNAL_MODE.get(signal_type, "lacunes"))


def set_mode(mode: str, active: bool, expert: str, motif: str | None = None) -> dict[str, bool]:
    if mode not in MODES:
        raise ValueError(f"Mode de collecte inconnu : {mode}")
    if not expert or not expert.strip():
        raise ValueError("Le nom de l'expert est requis pour modifier un réglage de collecte.")
    previous = is_active(mode)
    db.execute(
        "INSERT INTO settings (key, value, updated_at, updated_by) VALUES (?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at, updated_by = excluded.updated_by",
        (f"collecte.{mode}", "1" if active else "0", db.now_iso(), expert.strip()),
    )
    journal.append("reglage_collecte", "collecte", None, f"expert:{expert.strip()}",
                   {"mode": mode, "libelle": LABELS[mode], "avant": previous, "apres": active, "motif": motif})
    return state()
