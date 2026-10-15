"""Model-provider adapter. Everything above this layer depends only on `Provider`.

- OfflineProvider: deterministic, no network. Feature-hashed lexical embeddings + passthrough generation.
  Used for tests, CI and the guaranteed-repeatable demo mode.
- VertexProvider: Gemini + text embeddings on Vertex AI. NOT exercised until a GCP project is configured;
  model names come from settings and must be confirmed against the console before the demo.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Protocol

EMBED_DIM = 768
_TOKEN = re.compile(r"[a-z0-9_+\-]+")


class Provider(Protocol):
    name: str
    embed_model: str
    # Vector-only matches (no keyword/identifier evidence) must clear this cosine similarity.
    # Offline hashing cannot separate nonsense from real queries below ~0.5, so it is deliberately strict;
    # the Vertex value is a placeholder to be calibrated against the eval set once credentials exist.
    min_similarity: float

    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def generate_json(self, prompt: str, payload: dict) -> dict: ...


class OfflineProvider:
    name = "offline-deterministic"
    embed_model = "offline-hash-768"
    min_similarity = 0.5

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    @staticmethod
    def _vec(text: str) -> list[float]:
        toks = _TOKEN.findall(text.lower())
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]  # unigrams + bigrams
        v = [0.0] * EMBED_DIM
        for f in feats:
            h = int.from_bytes(hashlib.sha1(f.encode()).digest()[:8], "big")
            v[h % EMBED_DIM] += 1.0 if (h >> 63) & 1 else -1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def generate_json(self, prompt: str, payload: dict) -> dict:
        return payload  # deterministic: the evidence-built plan is already complete


class VertexProvider:
    name = "vertex-gemini"
    min_similarity = 0.6  # UNCALIBRATED placeholder

    def __init__(self, project: str, location: str, gen_model: str, embed_model: str):
        from google import genai  # lazy: dependency only needed in cloud mode

        self._client = genai.Client(vertexai=True, project=project, location=location)
        self._gen_model, self.embed_model = gen_model, embed_model

    def embed(self, texts: list[str]) -> list[list[float]]:
        from google.genai import types

        out: list[list[float]] = []
        for i in range(0, len(texts), 50):
            r = self._client.models.embed_content(
                model=self.embed_model, contents=texts[i:i + 50],
                config=types.EmbedContentConfig(output_dimensionality=EMBED_DIM))
            out.extend(e.values for e in r.embeddings)
        return out

    def generate_json(self, prompt: str, payload: dict) -> dict:
        from google.genai import types

        r = self._client.models.generate_content(
            model=self._gen_model,
            contents=f"{prompt}\n\nEVIDENCE_PACKET_JSON:\n{json.dumps(payload)}",
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2,
                                               max_output_tokens=4096))
        return json.loads(r.text)
