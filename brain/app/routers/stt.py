"""app/routers/stt.py — reconnaissance vocale locale (volet oral).

L'interface enregistre la question au micro et l'envoie ici ; le texte reconnu
revient à l'interface, qui le soumet ensuite à /api/chat comme une question tapée.
Le dossier de réponse, le filtre de sûreté et les signaux ne changent donc pas.

L'audio est transcrit en mémoire par faster-whisper (modèle Whisper exécuté sur la
machine) : il n'est ni transmis à un service externe ni écrit sur disque. Le modèle
est chargé au premier appel, puis gardé en mémoire.
"""
import io
import logging
import threading

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from ..config import WHISPER_COMPUTE_TYPE, WHISPER_DEVICE, WHISPER_MODEL
from ..internal_auth import require_internal

router = APIRouter(dependencies=[Depends(require_internal)])
log = logging.getLogger(__name__)

LANGUES = {"fr", "en"}
MAX_SIZE = 10 * 1024 * 1024  # 10 Mo, soit plusieurs minutes de parole compressée

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


def _transcribe(audio: bytes, lang: str) -> dict:
    # Le filtre de détection de la voix (VAD) retire les silences, mais il peut aussi écarter
    # une voix captée faiblement (micro intégré, visiteur éloigné) : sans résultat, on retranscrit sans lui.
    for vad in (True, False):
        segments, info = _get_model().transcribe(io.BytesIO(audio), language=lang, beam_size=5, vad_filter=vad)
        text = " ".join(s.text.strip() for s in segments).strip()
        if text:
            break
    return {"text": text, "lang": info.language, "duree": round(info.duration, 1)}


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
        return await run_in_threadpool(_transcribe, audio, lang)
    except Exception as exc:
        log.exception("Échec de la transcription")
        raise HTTPException(500, f"La transcription a échoué : {exc}") from exc
