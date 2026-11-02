"""Configuration des tests : répertoire de données temporaire, LLM et embeddings simulés.

Les tests n'appellent ni l'API Anthropic ni Hugging Face :
- anthropic_client.messages est remplacé par FakeLLM, qui renvoie des réponses
  programmées selon le contenu du prompt ;
- vectorstore.embed est remplacé par un plongement déterministe (hachage des mots),
  suffisant pour tester le regroupement des questions et la recherche documentaire.
"""
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

BRAIN_DIR = Path(__file__).resolve().parents[2]
_tmp = Path(tempfile.mkdtemp(prefix="yobakoko-test-"))
os.environ["YOBAKOKO_DATA_DIR"] = str(_tmp / "data")
os.environ["YOBAKOKO_UPLOAD_DIR"] = str(_tmp / "uploads")
os.environ["ANTHROPIC_API_KEY"] = "test"
os.environ["INTERNAL_SECRET"] = ""
os.environ["YOBAKOKO_PROFILE"] = "ndab"
(_tmp / "data").mkdir(parents=True)
# Ontologie initiale fournie avec le profil : les tests ne dépendent d'aucune donnée locale.
shutil.copy(BRAIN_DIR / "profiles" / "ndab" / "ontologie_initiale.json", _tmp / "data" / "ontology.json")
sys.path.insert(0, str(BRAIN_DIR))


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from doublures import FakeLLM, fake_embed  # noqa: E402


@pytest.fixture(scope="session")
def llm():
    return FakeLLM()


@pytest.fixture(scope="session")
def client(llm):
    from fastapi.testclient import TestClient

    from app import anthropic_client, vectorstore
    from app.main import app

    vectorstore.embed = fake_embed
    anthropic_client.messages = llm
    with TestClient(app) as c:
        yield c
