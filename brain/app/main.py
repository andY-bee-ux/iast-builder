"""app/main.py — service brain de YobaKoko.

Ce processus n'est pas destiné à être exposé directement : la gateway Node est
son seul appelant prévu (voir internal_auth.py). En production, liez-le à
127.0.0.1 (voir la section Déploiement du document technique).

Au démarrage (lifespan) :
1. vérifie qu'une ontologie active existe (JSON ou OWL) ;
2. crée ou met à jour le schéma SQLite et migre les anciens registres JSON ;
3. enregistre l'ontologie active comme version 1 si aucune version n'existe ;
4. régénère le graphe des enrichissements validés.
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import shutil

from . import db, enrichments, instance, journal, ontology_evolution, ontology_loader, profile_check
from .config import DATA_DIR
from .profile import active as active_profile
from .routers import admin, chat, contribute, documents, knowledge, profile as profile_router, questions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
log = logging.getLogger("yobakoko")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Le profil de domaine doit être conforme au métamodèle IAST-Builder.
    profile = active_profile()
    issues = profile_check.check(profile.id)
    if issues:
        raise RuntimeError("Profil de domaine non conforme au métamodèle IAST-Builder : " + " ; ".join(issues))
    log.info("Profil de domaine actif : %s (%s)", profile.id, profile.raw.get("nom"))
    # 2. Le répertoire de données doit appartenir à ce profil. Au premier démarrage d'un domaine,
    #    l'ontologie initiale du profil devient l'ontologie active et le répertoire est rattaché au profil.
    try:
        ontology_loader.find_active_ontology_path()
        active_classes = set(ontology_loader.load_active().vocabulary.classes)
    except FileNotFoundError:
        dest = ontology_loader.JSON_PATH if profile.ontology_file.suffix == ".json" else ontology_loader.OWL_PATH
        shutil.copyfile(profile.ontology_file, dest)
        log.info("Ontologie initiale du profil copiée dans %s", dest)
        active_classes = None
    try:
        log.info("Répertoire de données %s : %s", DATA_DIR, instance.check_or_bind(profile, DATA_DIR, active_classes))
    except instance.InstanceMismatch as exc:
        raise RuntimeError(str(exc)) from exc
    db.init_db()
    ontology_evolution.ensure_initial_version()
    migrated = db.migrate_legacy_json()
    if any(migrated.values()):
        log.info("Registres JSON migrés vers SQLite : %s", migrated)
        journal.append("migration", "systeme", None, "systeme", migrated)
    enrichments.rebuild()
    yield


app = FastAPI(title="IAST-Builder Brain", version="4.0.0", lifespan=lifespan)

# CORS permissif acceptable : le service n'est joint que par la gateway.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

for r in (chat, contribute, documents, admin, questions, knowledge, profile_router):
    app.include_router(r.router, prefix="/api")


@app.get("/health")
async def health():
    try:
        fmt = ontology_loader.find_active_ontology_path().suffix
    except FileNotFoundError:
        fmt = None
    return {
        "ok": True,
        "hasApiKey": bool(os.getenv("ANTHROPIC_API_KEY")),
        "dataDir": str(DATA_DIR),
        "ontologyFormat": fmt,
        "ontologyVersion": journal.current_ontology_version(),
        "profile": active_profile().id,
    }
