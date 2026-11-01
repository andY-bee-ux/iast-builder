"""Doublures communes aux suites de tests : embeddings et LLM simulés.

Les tests n'appellent ni l'API Anthropic ni Hugging Face."""
import hashlib
import json
import re


def fake_embed(texts):
    out = []
    for t in texts:
        v = [0.0] * 64
        for w in re.findall(r"\w+", t.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
        out.append(v)
    return out


class FakeLLM:
    """Renvoie la prochaine réponse programmée ; `queue` est remplie par chaque test."""

    def __init__(self):
        self.queue: list[str] = []
        self.calls: list[dict] = []

    async def __call__(self, system, messages, max_tokens=1200):
        self.calls.append({"system": system, "messages": messages})
        if not self.queue:
            raise AssertionError("Aucune réponse programmée pour le LLM simulé.")
        item = self.queue.pop(0)
        return item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)


