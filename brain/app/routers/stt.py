"""app/routers/stt.py — reconnaissance vocale (volet oral).

L'interface enregistre la question au micro et l'envoie ici ; le texte reconnu
revient à l'interface, qui le soumet ensuite à /api/chat comme une question tapée.
Le dossier de réponse, le filtre de sûreté et les signaux ne changent donc pas.

Deux moteurs, choisis par STT_MOTEUR dans brain/.env :
- whisper (par défaut) : faster-whisper transcrit l'audio en mémoire, sur la machine ;
  l'audio n'est ni transmis à un service externe ni écrit sur disque. Le modèle est
  chargé au premier appel, puis gardé en mémoire.
- elevenlabs : l'audio est envoyé au service Scribe d'ElevenLabs. Plus précis et plus
  rapide sur une machine sans GPU, mais la voix de l'usager quitte la machine (et le
  service la conserve, sauf contrat entreprise « zéro conservation »). En cas d'échec
  (réseau, clé, quota), la transcription se rabat sur Whisper.

Dans les deux cas, le vocabulaire du profil actif (noms propres de l'ontologie, termes
déclarés) est fourni comme termes à privilégier : voir vocabulaire_oral.py.
"""
import io
import logging
import re
import threading
import time

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from .. import vocabulaire_oral
from ..config import (ELEVENLABS_API_KEY, ELEVENLABS_STT_MODEL, ELEVENLABS_URL, STT_MOTEUR,
                      WHISPER_COMPUTE_TYPE, WHISPER_DEVICE, WHISPER_MODEL)
from ..internal_auth import require_internal

router = APIRouter(dependencies=[Depends(require_internal)])
log = logging.getLogger(__name__)

LANGUES = {"fr", "en"}
MAX_SIZE = 10 * 1024 * 1024  # 10 Mo, soit plusieurs minutes de parole compressée

# ---- Whisper (local) ---------------------------------------------------------------
_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            log.info("Chargement du modèle Whisper « %s » (%s, %s)…", WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE)
            _model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE)
        return _model


def _whisper(audio: bytes, lang: str) -> dict:
    # Le filtre de détection de la voix (VAD) retire les silences, mais il peut aussi écarter
    # une voix captée faiblement (micro intégré, visiteur éloigné) : sans résultat, on retranscrit sans lui.
    hotwords = vocabulaire_oral.hotwords()
    for vad in (True, False):
        segments, info = _get_model().transcribe(io.BytesIO(audio), language=lang, beam_size=5, vad_filter=vad,
                                                 hotwords=hotwords)
        text = " ".join(s.text.strip() for s in segments).strip()
        if text:
            break
    return {"text": text, "lang": info.language, "duree": round(info.duration, 1), "moteur": f"whisper-{WHISPER_MODEL}"}


# ElevenLabs Scribe (en ligne) --------------------------------------------------
# Codes ISO 639-3, ceux qu'emploie la documentation d'ElevenLabs.
CODES_ELEVENLABS = {"fr": "fra", "en": "eng"}
# Contraintes de l'API sur les termes : 50 caractères, 5 mots, sans < > { } [ ] \
_INTERDITS = re.compile(r"[<>{}\[\]\\]")


class ElevenLabsIndisponible(Exception):
    pass


def _keyterms() -> list[str]:
    return [t for t in vocabulaire_oral.termes()
            if len(t) <= 50 and len(t.split()) <= 5 and not _INTERDITS.search(t)]


def _elevenlabs(audio: bytes, lang: str, mime: str) -> dict:
    if not ELEVENLABS_API_KEY:
        raise ElevenLabsIndisponible("ELEVENLABS_API_KEY manquante dans brain/.env")
    data = {"model_id": ELEVENLABS_STT_MODEL, "language_code": CODES_ELEVENLABS[lang], "tag_audio_events": "false"}
    termes = _keyterms()
    if termes:
        data["keyterms"] = termes   # liste : envoyée comme un champ « keyterms » répété
    try:
        r = httpx.post(f"{ELEVENLABS_URL}/v1/speech-to-text", headers={"xi-api-key": ELEVENLABS_API_KEY},
                       data=data, files={"file": ("question.webm", audio, (mime or "audio/webm").split(";")[0])}, timeout=60)
    except httpx.HTTPError as exc:
        raise ElevenLabsIndisponible(f"service injoignable ({exc.__class__.__name__})") from exc
    if r.status_code != 200:
        raise ElevenLabsIndisponible(f"HTTP {r.status_code} : {r.text[:300]}")
    body = r.json()
    return {"text": (body.get("text") or "").strip(), "lang": lang,
            "duree": round(body.get("audio_duration_secs") or 0, 1), "moteur": ELEVENLABS_STT_MODEL}


# ---- Route --------------------------------------------------------------------------
def _transcribe(audio: bytes, lang: str, mime: str) -> dict:
    debut = time.perf_counter()
    result = None
    if STT_MOTEUR == "elevenlabs":
        try:
            result = _elevenlabs(audio, lang, mime)
        except ElevenLabsIndisponible as exc:
            log.warning("ElevenLabs indisponible, repli sur Whisper : %s", exc)
    if result is None:
        result = _whisper(audio, lang)
    result["temps"] = round(time.perf_counter() - debut, 1)
    log.info("Transcription %s en %.1f s : %s", result["moteur"], result["temps"], result["text"])
    return result


@router.post("/stt")
async def speech_to_text(file: UploadFile = File(...), lang: str = Form(default="fr")):
    if lang not in LANGUES:
        raise HTTPException(400, f"Langue non prise en charge ({lang}). Langues acceptées : {', '.join(sorted(LANGUES))}")
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "Enregistrement vide.")
    if len(audio) > MAX_SIZE:
        raise HTTPException(400, "Enregistrement trop long (limite : 10 Mo).")
    try:
        return await run_in_threadpool(_transcribe, audio, lang, file.content_type)
    except Exception as exc:
        log.exception("Échec de la transcription")
        raise HTTPException(500, f"La transcription a échoué : {exc}") from exc
