"""Model-provider adapter. Everything above this layer depends only on `Provider`.

Two capabilities, reported honestly:
- `has_llm`: can make structured judgments (query analysis, reranking, planning, compliance, conflicts, reuse).
- `semantic_embeddings`: vectors that encode meaning. The offline provider has neither: search is lexical only and
  every judgment raises `LLMUnavailable` unless a cached judgment exists (replay).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Protocol

EMBED_DIM = 768
_TOKEN = re.compile(r"[a-z0-9_+\-]+")


class LLMUnavailable(RuntimeError):
    """Raised when a judgment is needed but no model is configured and no cached judgment exists."""


class Provider(Protocol):
    name: str
    embed_model: str
    has_llm: bool
    semantic_embeddings: bool

    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]: ...
    def generate_json(self, system: str, user: str, schema: dict) -> dict: ...


class OfflineProvider:
    """No model. `embed` is a deterministic lexical n-gram hash kept only so the vector plumbing is testable;
    `semantic_embeddings` is False, so search never uses it as a relevance signal."""
    name = "offline"
    embed_model = "offline-hash-768"
    has_llm = False
    semantic_embeddings = False

    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    @staticmethod
    def _vec(text: str) -> list[float]:
        toks = _TOKEN.findall(text.lower())
        v = [0.0] * EMBED_DIM
        for f in toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]:
            h = int.from_bytes(hashlib.sha1(f.encode()).digest()[:8], "big")
            v[h % EMBED_DIM] += 1.0 if (h >> 63) & 1 else -1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def generate_json(self, system: str, user: str, schema: dict) -> dict:
        raise LLMUnavailable("no LLM configured (set PROVIDER=gemini with GEMINI_API_KEY, or PROVIDER=vertex)")


class GeminiProvider:
    """Gemini via the Developer API (api key) or Vertex AI (ADC). Not exercised until credentials exist."""
    has_llm = True
    semantic_embeddings = True

    def __init__(self, *, api_key: str = "", project: str = "", location: str = "us-central1",
                 gen_model: str = "gemini-2.5-flash", embed_model: str = "text-embedding-005"):
        from google import genai  # lazy: only needed when a model is configured

        if api_key:
            self._client, self.name = genai.Client(api_key=api_key), "gemini-api"
        else:
            self._client, self.name = genai.Client(vertexai=True, project=project, location=location), "vertex-gemini"
        self._gen_model, self.embed_model = gen_model, embed_model

    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]:
        from google.genai import types

        task = "RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT"
        out: list[list[float]] = []
        for i in range(0, len(texts), 50):
            r = self._client.models.embed_content(
                model=self.embed_model, contents=texts[i:i + 50],
                config=types.EmbedContentConfig(output_dimensionality=EMBED_DIM, task_type=task))
            out.extend(e.values for e in r.embeddings)
        return out

    def generate_json(self, system: str, user: str, schema: dict) -> dict:
        from google.genai import types

        cfg = types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                                          response_schema=schema, temperature=0.0)
        last: Exception | None = None
        for _ in range(2):  # one retry: structured output occasionally fails to parse
            try:
                r = self._client.models.generate_content(model=self._gen_model, contents=user, config=cfg)
                return json.loads(r.text)
            except (json.JSONDecodeError, ValueError) as exc:
                last = exc
        raise RuntimeError(f"model did not return valid JSON: {last}")


def make_provider(settings) -> Provider:
    if settings.provider in ("gemini", "vertex"):
        return GeminiProvider(api_key=settings.gemini_api_key if settings.provider == "gemini" else "",
                              project=settings.gcp_project, location=settings.gcp_location,
                              gen_model=settings.gen_model, embed_model=settings.embed_model)
    return OfflineProvider()
