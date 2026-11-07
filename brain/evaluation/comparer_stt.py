"""evaluation/comparer_stt.py — compare les deux moteurs de transcription sur les mêmes enregistrements.

Usage (depuis brain/, .venv activé) :
    python evaluation/comparer_stt.py enregistrement1.m4a enregistrement2.wav ...

Chaque fichier est transcrit par Whisper (modèle WHISPER_MODEL, local) puis par ElevenLabs Scribe
(ELEVENLABS_API_KEY requise), avec le vocabulaire du profil actif (YOBAKOKO_PROFILE, ndab par défaut).
Le premier appel à Whisper inclut le chargement du modèle : il est refait une fois à vide pour ne
pas fausser la mesure. Les enregistrements peuvent venir de l'Enregistreur vocal de Windows.
"""
import mimetypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.routers import stt  # noqa: E402

LANG = "fr"


def mesurer(nom, fonction):
    debut = time.perf_counter()
    try:
        texte = fonction()["text"]
    except Exception as exc:  # une erreur d'un moteur ne doit pas arrêter la comparaison
        texte = f"ERREUR : {exc}"
    print(f"  {nom:<12} {time.perf_counter() - debut:5.1f} s  {texte}")


def main(fichiers):
    if not fichiers:
        sys.exit(__doc__)
    print("Vocabulaire :", ", ".join(stt.vocabulaire_oral.termes()))
    stt._get_model()   # chargement du modèle Whisper, hors mesure
    for chemin in map(Path, fichiers):
        audio = chemin.read_bytes()
        mime = mimetypes.guess_type(chemin.name)[0] or "audio/webm"
        print(f"\n{chemin.name}")
        mesurer("whisper", lambda: stt._whisper(audio, LANG))
        mesurer("elevenlabs", lambda: stt._elevenlabs(audio, LANG, mime))


if __name__ == "__main__":
    main(sys.argv[1:])
