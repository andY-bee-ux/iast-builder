"""Tests du profil « afripharm » : même moteur, autre domaine.

Le répertoire de données est vide au départ : le moteur doit y installer lui-même
l'ontologie initiale du profil. Le LLM et les embeddings sont simulés, comme pour
les tests du profil Ndab."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

BRAIN_DIR = Path(__file__).resolve().parents[2]
_tmp = Path(tempfile.mkdtemp(prefix="iab-afripharm-"))
os.environ["YOBAKOKO_DATA_DIR"] = str(_tmp / "data")
os.environ["YOBAKOKO_UPLOAD_DIR"] = str(_tmp / "uploads")
os.environ["ANTHROPIC_API_KEY"] = "test"
os.environ["INTERNAL_SECRET"] = ""
os.environ["YOBAKOKO_PROFILE"] = "afripharm"
sys.path.insert(0, str(BRAIN_DIR))
sys.path.insert(0, str(BRAIN_DIR / "tests"))

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
