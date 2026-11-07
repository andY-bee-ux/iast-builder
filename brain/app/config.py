"""app/config.py — configuration centrale du service brain.

Toutes les valeurs proviennent de variables d'environnement (fichier brain/.env),
avec des valeurs par défaut raisonnables. Les constantes « d'ingénierie » (taille
des passages, seuils) sont regroupées ici pour être ajustées en un seul endroit.

Organisation des répertoires (sous brain/) :
    data/                       état du système (à sauvegarder)
        yobakoko.db             base SQLite : contributions, documents, journal,
                                questions d'investigation, assertions, versions
        ontology.json | .ttl    ontologie active (un seul fichier à la fois)
        ontology_backups/       copies horodatées avant chaque remplacement manuel
        ontology_versions/      instantané de chaque version publiée (phase 3)
        enrichments.ttl         graphe RDF des enrichissements validés (phase 3),
                                régénéré depuis la base, avec provenance PROV-O
        chroma/                 base vectorielle du corpus validé
    uploads/                    fichiers originaux soumis
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Le fichier brain/.env passe avant les variables du Terminal pour les secrets et les
# réglages du service (par exemple ANTHROPIC_API_KEY) : une ancienne clé définie dans le
# shell ne peut pas masquer celle du fichier. Les réglages de lancement YOBAKOKO_* (profil,
# répertoires de données) fixés par start.sh pour une instance donnée font exception :
# ils passent toujours avant le fichier, faute de quoi une ligne YOBAKOKO_PROFILE=ndab
# dans .env lancerait YobaKoko à la place de l'instance demandée.
_launch = {k: v for k, v in os.environ.items() if k.startswith("YOBAKOKO_")}
load_dotenv(override=True)
os.environ.update(_launch)

BASE_DIR = Path(__file__).resolve().parent.parent

# YOBAKOKO_DATA_DIR permet de pointer vers un autre répertoire de données
# (tests automatisés, instance de démonstration) sans toucher au code.
DATA_DIR = Path(os.getenv("YOBAKOKO_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = Path(os.getenv("YOBAKOKO_UPLOAD_DIR", BASE_DIR / "uploads"))
CHROMA_DIR = DATA_DIR / "chroma"
DB_PATH = DATA_DIR / "yobakoko.db"
ONTOLOGY_VERSIONS_DIR = DATA_DIR / "ontology_versions"
ENRICHMENTS_TTL = DATA_DIR / "enrichments.ttl"

for _d in (DATA_DIR, UPLOAD_DIR, CHROMA_DIR, ONTOLOGY_VERSIONS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Modèle de langage -------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
# Température basse : un agent documentaire doit répondre de façon stable à une même question.
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))

# --- Embeddings (locaux, via fastembed) -------------------------------------
# Petit modèle multilingue (français/anglais) exécuté localement en ONNX.
# Premier usage : téléchargement unique (~120 Mo) depuis Hugging Face.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

# --- Reconnaissance vocale (locale, via faster-whisper) ------------------------
# Volet oral : la question dictée est transcrite sur la machine, l'audio n'est ni envoyé
# à un service externe ni conservé. Premier usage : téléchargement unique du modèle
# (« small » : ~460 Mo ; « base » : ~140 Mo, plus rapide mais moins précis).
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
# Moteur de transcription : « whisper » (local, par défaut) ou « elevenlabs » (service en ligne
# Scribe, plus précis et plus rapide sur un portable, mais l'audio de l'usager quitte la machine).
# En cas d'échec d'ElevenLabs (réseau, clé, quota), la transcription se rabat sur Whisper.
STT_MOTEUR = os.getenv("STT_MOTEUR", "whisper").strip().lower()
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_STT_MODEL = os.getenv("ELEVENLABS_STT_MODEL", "scribe_v2")
# Serveur européen possible : https://api.eu.residency.elevenlabs.io
ELEVENLABS_URL = os.getenv("ELEVENLABS_URL", "https://api.elevenlabs.io").rstrip("/")

# --- Sécurité interne ----------------------------------------------------------
# Secret que la gateway présente à chaque appel (voir internal_auth.py).
INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "")

# --- Recherche documentaire (RAG) -------------------------------------------------
CHUNK_SIZE = 900
CHUNK_OVERLAP = 150
RETRIEVAL_TOP_K = 4

# --- Phase 1 : questions d'investigation -----------------------------------------
# Seuil de similarité (cosinus entre embeddings) au-delà duquel deux signaux
# sont regroupés dans la même question. Si le modèle d'embeddings est
# indisponible, un repli lexical (indice de Jaccard) est utilisé avec son propre seuil.
SIGNAL_SIMILARITY = float(os.getenv("SIGNAL_SIMILARITY", "0.85"))
SIGNAL_JACCARD = float(os.getenv("SIGNAL_JACCARD", "0.6"))

# --- Lissage des réponses (dossier de réponse et restitution) --------------------
# Mode strict : les phrases déclaratives sans renvoi à un fait du dossier sont
# retirées avant l'affichage. Désactivé par défaut : les anomalies sont alors
# seulement consignées au journal (événement "controle_fidelite").
RESTITUTION_STRICT = os.getenv("RESTITUTION_STRICT", "false").lower() == "true"

# Nombre maximal d'assertions validées injectées dans le dossier d'une réponse.
MAX_ENRICHMENTS_IN_PROMPT = int(os.getenv("MAX_ENRICHMENTS_IN_PROMPT", "40"))

# --- Phase 2 : extraction guidée par l'ontologie ---------------------------------
EXTRACTION_CHUNK_SIZE = int(os.getenv("EXTRACTION_CHUNK_SIZE", "2500"))
EXTRACTION_MAX_CHUNKS = int(os.getenv("EXTRACTION_MAX_CHUNKS", "40"))

# --- Phase 3 : détection des variantes (polymorphisme des formes) ----------------
VARIANT_SIMILARITY = float(os.getenv("VARIANT_SIMILARITY", "0.9"))
