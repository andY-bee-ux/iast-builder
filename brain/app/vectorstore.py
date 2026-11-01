"""app/vectorstore.py — base vectorielle du corpus validé (documents et contributions approuvés).

Les assertions validées (phases 2 et 3) ne passent pas par ici : elles sont
structurées et vivent dans la base SQLite et le graphe d'enrichissements.

The swappable "long-term knowledge" layer.

Chosen for local-first deployment: Chroma persists to a folder on disk, no
server process, no account, no cost. If the corpus ever outgrows a single
machine, swap this module for a Pinecone-backed one — the rest of the app
only calls add_chunks() / query() and doesn't know which store is behind them.

Embeddings come from fastembed running a small multilingual ONNX model
locally (no external API, no per-call cost). The model is downloaded once
(~120MB) on first use and then cached — that first download needs a normal
internet connection; after that, embedding works fully offline.
"""
from __future__ import annotations
import chromadb
from fastembed import TextEmbedding

from .config import CHROMA_DIR, EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP

_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
# embedding_function=None: we always supply our own vectors (via fastembed
# below), so Chroma never tries to download its own default model.
_collection = _client.get_or_create_collection(name="yobakoko_knowledge", embedding_function=None)

_model: TextEmbedding | None = None


class EmbeddingUnavailable(Exception):
    pass


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        try:
            _model = TextEmbedding(model_name=EMBEDDING_MODEL)
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingUnavailable(
                f"Impossible de charger le modèle d'embeddings ({EMBEDDING_MODEL}). "
                "Le premier lancement nécessite une connexion internet pour le télécharger depuis "
                f"Hugging Face (~120 Mo, mis en cache ensuite). Détail : {exc}"
            ) from exc
    return _model


def embed(texts: list[str]) -> list[list[float]]:
    return [v.tolist() for v in _get_model().embed(texts)]


def try_embed(texts: list[str]) -> list[list[float]] | None:
    """Comme embed(), mais renvoie None si le modèle est indisponible (hors ligne,
    premier lancement sans connexion). Utilisé là où un repli est prévu, par
    exemple le regroupement des questions d'investigation (phase 1)."""
    try:
        return embed(texts)
    except EmbeddingUnavailable:
        return None


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def add_document(doc_id: int, filename: str, text: str) -> int:
    """Chunks, embeds, and stores an APPROVED document. Returns chunk count.
    Callers must only invoke this after admin approval — see routers/admin.py."""
    chunks = chunk_text(text)
    if not chunks:
        return 0
    vectors = embed(chunks)
    ids = [f"doc{doc_id}_chunk{i}" for i in range(len(chunks))]
    metadatas = [{"source_type": "document", "doc_id": doc_id, "filename": filename, "chunk_index": i} for i in range(len(chunks))]
    _collection.add(ids=ids, embeddings=vectors, documents=chunks, metadatas=metadatas)
    return len(chunks)


def add_contribution(contrib_id: int, content: str, contrib_type: str) -> None:
    """Stores a single APPROVED contribution as one chunk."""
    vector = embed([content])[0]
    _collection.add(
        ids=[f"contrib{contrib_id}"],
        embeddings=[vector],
        documents=[content],
        metadatas=[{"source_type": "contribution", "contrib_id": contrib_id, "contrib_type": contrib_type}],
    )


def remove_document(doc_id: int) -> None:
    _collection.delete(where={"doc_id": doc_id})


def remove_contribution(contrib_id: int) -> None:
    _collection.delete(ids=[f"contrib{contrib_id}"])


def count() -> int:
    return _collection.count()


def query(text: str, top_k: int) -> list[dict]:
    if _collection.count() == 0:
        return []
    vector = embed([text])[0]
    res = _collection.query(query_embeddings=[vector], n_results=min(top_k, _collection.count()))
    out = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        out.append({"text": doc, "metadata": meta, "distance": dist})
    return out
