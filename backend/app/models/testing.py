"""Test doubles for the model layer. These verify wiring and guards, never model quality."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Callable

from .provider import EMBED_DIM

Responder = Callable[[dict], dict]


class ScriptedProvider:
    """Answers generate_json from a per-task callable. `calls` records (task, payload) for assertions."""
    name = "scripted"
    embed_model = "scripted-embed"
    has_llm = True
    semantic_embeddings = False

    def __init__(self, responders: dict[str, Responder] | None = None, semantic: bool = False):
        self.responders = responders or {}
        self.calls: list[tuple[str, dict]] = []
        self.semantic_embeddings = semantic

    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]:
        out = []
        for t in texts:  # stable pseudo-vectors: identical text -> identical vector, no semantics
            seed = hashlib.sha256(t.encode()).digest()
            v = [(seed[i % 32] - 127.5) for i in range(EMBED_DIM)]
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out

    def generate_json(self, system: str, user: str, schema: dict) -> dict:
        task = system.split("]", 1)[0].removeprefix("[task:")
        payload = json.loads(user)
        self.calls.append((task, payload))
        if task not in self.responders:
            raise AssertionError(f"unscripted task {task}")
        return self.responders[task](payload)
