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
import threading
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
    """Gemini via the Developer API (api key) or Vertex AI (ADC).

    Generation tries `gen_model`, then each of `fallback_models`, retrying transient failures (503/429/500) with
    backoff; a model that no longer exists (404) is skipped. `last_model` is whichever model actually answered, and
    `models` is the full chain so cached judgments from any of them are reusable."""
    has_llm = True
    semantic_embeddings = True
    RETRIES = 1
    REQUEST_TIMEOUT_MS = 45_000  # a request that hangs counts as a failure, not a stall
    COOLDOWN_S = 300.0  # a model that just failed is tried last for this long (circuit breaker)
    QUOTA_RETRIES = 5
    MAX_QUOTA_WAIT_S = 90.0
    EMBED_MIN_INTERVAL_S = 0.65  # ~92 requests/minute: under the free-tier cap of 100
    BACKOFF_S = 1.5

    def __init__(self, *, api_key: str = "", project: str = "", location: str = "us-central1",
                 gen_model: str = "gemini-3.5-flash", embed_model: str = "gemini-embedding-001",
                 fallback_models: tuple[str, ...] = ()):
        from google import genai  # lazy: only needed when a model is configured

        from google.genai import types

        http = types.HttpOptions(timeout=self.REQUEST_TIMEOUT_MS)
        if api_key:
            self._client, self.name = genai.Client(api_key=api_key, http_options=http), "gemini-api"
        else:
            self._client, self.name = genai.Client(vertexai=True, project=project, location=location,
                                                   http_options=http), "vertex-gemini"
        self._gen_model, self.embed_model = gen_model, embed_model
        self.models = [gen_model, *[m for m in fallback_models if m and m != gen_model]]
        self.last_model = gen_model
        self._pace_lock, self._next_slot = threading.Lock(), 0.0
        self._down_until: dict[str, float] = {}
        self.usage = {"calls": 0, "prompt_tokens": 0, "output_tokens": 0, "retries": 0, "fallbacks": 0}

    @staticmethod
    def _retry_delay(exc) -> float | None:
        """Seconds the API asked us to wait (google.rpc.RetryInfo, e.g. '58s'), if present."""
        import re

        m = re.search(r"'retryDelay': '([\d.]+)s'", str(exc))
        return float(m.group(1)) if m else None

    def _call(self, fn):
        """Retry transient failures: 5xx with short backoff, 429 (free-tier quota) after the delay the API names."""
        import time

        from google.genai import errors

        for attempt in range(self.RETRIES + self.QUOTA_RETRIES):
            try:
                return fn()
            except errors.ServerError:
                if attempt >= self.RETRIES:
                    raise
                wait = self.BACKOFF_S * (attempt + 1)
            except errors.ClientError as exc:
                delay = self._retry_delay(exc)
                if getattr(exc, "code", None) != 429 or attempt >= self.RETRIES + self.QUOTA_RETRIES - 1 \
                        or (delay or 0) > self.MAX_QUOTA_WAIT_S:
                    raise  # a per-day quota (retry in hours) is not worth waiting for: let the caller change model
                wait = (delay or 30.0) + 1.0
            self.usage["retries"] += 1
            time.sleep(wait)
        return fn()

    def _pace(self) -> None:
        """Global spacing between per-text embedding requests so the free-tier requests/minute cap is not hit."""
        import time

        with self._pace_lock:
            wait = self._next_slot - time.monotonic()
            self._next_slot = max(self._next_slot, time.monotonic()) + self.EMBED_MIN_INTERVAL_S
        if wait > 0:
            time.sleep(wait)

    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]:
        from google.genai import types

        from concurrent.futures import ThreadPoolExecutor

        cfg = types.EmbedContentConfig(output_dimensionality=EMBED_DIM,
                                       task_type="RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT")

        def one(batch: list[str]):
            return self._call(lambda: self._client.models.embed_content(
                model=self.embed_model, contents=batch, config=cfg)).embeddings

        out: list[list[float]] = []
        for i in range(0, len(texts), 50):
            batch = texts[i:i + 50]
            got = one(batch)
            if len(got) != len(batch):
                # Some embedding models (gemini-embedding-2) fold a batch into ONE vector; embed each text alone so
                # vectors stay aligned with their chunks instead of silently shifting.
                def alone(t: str):
                    self._pace()
                    return one([t])[0]

                with ThreadPoolExecutor(8) as ex:
                    got = list(ex.map(alone, batch))
            out.extend(_unit(e.values) for e in got)
        return out

    def generate_json(self, system: str, user: str, schema: dict) -> dict:
        from google.genai import errors, types

        cfg = types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                                          response_schema=schema, temperature=0.0)
        import time

        import httpx

        last: Exception | None = None
        now = time.monotonic()
        order = sorted(self.models, key=lambda m: self._down_until.get(m, 0.0) > now)  # healthy first, stable
        for n, model in enumerate(order):
            for _ in range(2):  # one retry: structured output occasionally fails to parse
                try:
                    r = self._call(lambda: self._client.models.generate_content(model=model, contents=user, config=cfg))
                    out = json.loads(r.text)
                except (json.JSONDecodeError, ValueError, TypeError) as exc:
                    last = exc
                    continue
                except (errors.APIError, httpx.HTTPError) as exc:
                    last = exc
                    self._down_until[model] = time.monotonic() + min(max(self._retry_delay(exc) or 0.0, self.COOLDOWN_S), 21600.0)
                    break  # unavailable / retired / hung: next model in the chain
                u = getattr(r, "usage_metadata", None)
                self.usage["calls"] += 1
                self.usage["prompt_tokens"] += getattr(u, "prompt_token_count", 0) or 0
                self.usage["output_tokens"] += getattr(u, "candidates_token_count", 0) or 0
                self.usage["fallbacks"] += 1 if model != self._gen_model else 0
                self.last_model = model
                self._down_until.pop(model, None)
                return out
        raise RuntimeError(f"no model produced a valid answer: {type(last).__name__}: {str(last)[:200]}")


def _unit(v) -> list[float]:
    """Reduced-dimension Gemini embeddings are not unit length; normalise so cosine distance is well behaved."""
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def make_provider(settings) -> Provider:
    if settings.provider in ("gemini", "vertex"):
        return GeminiProvider(api_key=settings.gemini_api_key if settings.provider == "gemini" else "",
                              project=settings.gcp_project, location=settings.gcp_location,
                              gen_model=settings.gen_model, embed_model=settings.embed_model,
                              fallback_models=tuple(m for m in settings.gen_fallback_models.split(',') if m.strip()))
    return OfflineProvider()
