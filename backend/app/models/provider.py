"""Model-provider adapter. Everything above this layer depends only on `Provider`.

Two capabilities, reported honestly:
- `has_llm`: can make structured judgments (query analysis, reranking, planning, compliance, conflicts, reuse).
- `semantic_embeddings`: vectors that encode meaning. The offline provider has neither: search is lexical only and
  every judgment raises `LLMUnavailable` unless a cached judgment exists (replay).
"""
from __future__ import annotations

import json
import math
import re
import threading
from typing import Protocol

EMBED_DIM = 768
CHARS_PER_TOKEN = 3.0  # conservative over-estimate used for request sizing and spend caps


class LLMUnavailable(RuntimeError):
    """Raised when a judgment is needed but no model is configured and no cached judgment exists."""


class QuotaExhausted(RuntimeError):
    """A hard (daily) quota was hit. `retry_after_s` is the API's own RetryInfo. Callers stop; nothing is retried."""

    def __init__(self, message: str, retry_after_s: float):
        super().__init__(message)
        self.retry_after_s = retry_after_s


class Provider(Protocol):
    name: str
    embed_model: str
    has_llm: bool
    semantic_embeddings: bool

    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]: ...
    def generate_json(self, system: str, user: str, schema: dict) -> dict: ...


class OfflineProvider:
    """No model configured. Nothing here pretends to be intelligence: there are no vectors (embedding raises),
    `semantic_embeddings` is False so search is lexical only, and every judgment raises `LLMUnavailable` unless a
    cached judgment exists (replay)."""
    name = "offline"
    embed_model = "none"
    has_llm = False
    semantic_embeddings = False

    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]:
        raise LLMUnavailable("no embedding model configured (set PROVIDER=gemini or vertex, and EMBED_PROVIDER)")

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
    QUOTA_RETRIES = 2  # short per-minute backoff only; no long waits, no outer retry loops
    MAX_QUOTA_WAIT_S = 90.0
    EMBED_REQUEST_CHARS = 30_000   # ~9k tokens
    EMBED_TOKENS_PER_MIN = 24_000  # under the free-tier 30k/min
    CHARS_PER_TOKEN = 3.0          # conservative for code
    EMBED_MIN_INTERVAL_S = 0.65  # ~92 requests/minute: under the free-tier cap of 100
    BACKOFF_S = 1.5

    def __init__(self, *, api_key: str = "", project: str = "", location: str = "us-central1",
                 gen_model: str = "gemini-3.5-flash", embed_model: str = "gemini-embedding-001",
                 fallback_models: tuple[str, ...] = (), backup_api_key: str = "", backup_for_index: bool = False):
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
        self.usage = {"calls": 0, "prompt_tokens": 0, "output_tokens": 0, "retries": 0, "fallbacks": 0,
                      "backup_calls": 0}
        # A second API key (another project = its own free-tier quota), used only when the primary cannot answer.
        # Index embeddings stay on the primary unless `backup_for_index` is set by the owner.
        self._backup = None
        self.backup_for_index = backup_for_index
        if backup_api_key and api_key and backup_api_key != api_key:
            self._backup = GeminiProvider(api_key=backup_api_key, gen_model=gen_model, embed_model=embed_model,
                                          fallback_models=fallback_models)

    def _via_backup(self, fn):
        before = dict(self._backup.usage)
        out = fn()
        for k in ("calls", "prompt_tokens", "output_tokens", "retries", "fallbacks"):
            self.usage[k] += self._backup.usage[k] - before[k]
        self.usage["backup_calls"] += 1
        return out

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
                if getattr(exc, "code", None) == 429 and (delay or 0) > self.MAX_QUOTA_WAIT_S:
                    raise QuotaExhausted(f"daily quota exhausted; API says retry in {delay:.0f}s", delay) from exc
                if getattr(exc, "code", None) != 429 or attempt >= self.RETRIES + self.QUOTA_RETRIES - 1:
                    raise
                # No RetryInfo = a per-minute throttle: back off progressively (45s, 90s, 120s...) until it clears.
                wait = (delay + 1.0) if delay else min(45.0 * (attempt - self.RETRIES + 1), 120.0)
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
        try:
            return self._embed_once(texts, query)
        except QuotaExhausted:
            if self._backup is not None and (query or self.backup_for_index):
                return self._via_backup(lambda: self._backup._embed_once(texts, query))
            raise

    def generate_json(self, system: str, user: str, schema: dict) -> dict:
        try:
            return self._generate_json_once(system, user, schema)
        except RuntimeError:
            if self._backup is None:
                raise
            out = self._via_backup(lambda: self._backup._generate_json_once(system, user, schema))
            self.last_model = self._backup.last_model
            return out

    def _embed_once(self, texts: list[str], query: bool = False) -> list[list[float]]:
        from google.genai import types

        import time
        from concurrent.futures import ThreadPoolExecutor

        cfg = types.EmbedContentConfig(output_dimensionality=EMBED_DIM,
                                       task_type="RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT")

        def one(batch: list[str]):
            return self._call(lambda: self._client.models.embed_content(
                model=self.embed_model, contents=batch, config=cfg)).embeddings

        out: list[list[float]] = []
        for batch in self._requests(texts):
            started = time.monotonic()
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
            # Free-tier embedding quota is also per-minute TOKENS: keep the sustained rate under it.
            est_tokens = sum(len(t) for t in batch) / self.CHARS_PER_TOKEN
            time.sleep(max(0.0, est_tokens / self.EMBED_TOKENS_PER_MIN * 60.0 - (time.monotonic() - started)))
        return out

    def _requests(self, texts: list[str]):
        """Split into requests of at most 50 texts and EMBED_REQUEST_CHARS characters: a single oversized request
        is rejected (429) however long we wait, so size is bounded up front instead of retried."""
        cur, size = [], 0
        for t in texts:
            if cur and (len(cur) >= 50 or size + len(t) > self.EMBED_REQUEST_CHARS):
                yield cur
                cur, size = [], 0
            cur.append(t)
            size += len(t)
        if cur:
            yield cur

    def _generate_json_once(self, system: str, user: str, schema: dict) -> dict:
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
                except (errors.APIError, httpx.HTTPError, QuotaExhausted) as exc:
                    last = exc
                    self._down_until[model] = time.monotonic() + min(max(getattr(exc, 'retry_after_s', None) or self._retry_delay(exc) or 0.0, self.COOLDOWN_S), 21600.0)
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


class VertexEmbedder(GeminiProvider):
    """Embeddings from Vertex AI (paid from the project's credit, so no free-tier pacing or daily caps).

    text-embedding-005 (default) takes many texts per request. A new account's request quota is small (about ten a
    minute), so requests are batched up to the 20k-token limit and paced. gemini-embedding-001 takes ONE text per
    request, so its texts are sent alone."""
    PARALLEL = 2
    has_llm = False
    EMBED_MIN_INTERVAL_S = 7.0       # ~8 requests a minute, under the observed quota
    EMBED_REQUEST_CHARS = 30_000     # code runs near 2 chars/token, and a request may hold at most 20k tokens
    QUOTA_RETRIES = 6

    def _embed_batch(self, batch: list[str], cfg) -> list[list[float]]:
        """One request; if it is over the model's token limit (400), halve it and try again."""
        from google.genai import errors

        self._pace()
        try:
            got = self._call(lambda: self._client.models.embed_content(model=self.embed_model, contents=batch,
                                                                       config=cfg)).embeddings
        except errors.ClientError as exc:
            if getattr(exc, "code", None) == 400 and len(batch) > 1:
                mid = len(batch) // 2
                return self._embed_batch(batch[:mid], cfg) + self._embed_batch(batch[mid:], cfg)
            raise
        if len(got) != len(batch):
            raise RuntimeError(f"embedding count mismatch: sent {len(batch)}, got {len(got)}")
        return [_unit(e.values) for e in got]

    def _embed_once(self, texts: list[str], query: bool = False) -> list[list[float]]:
        from concurrent.futures import ThreadPoolExecutor

        from google.genai import types

        cfg = types.EmbedContentConfig(output_dimensionality=EMBED_DIM,
                                       task_type="RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT")
        if not self.embed_model.startswith("gemini-embedding"):
            out: list[list[float]] = []
            for batch in self._requests(texts):
                out.extend(self._embed_batch(batch, cfg))
            return out

        def one(text: str) -> list[float]:
            got = self._call(lambda: self._client.models.embed_content(model=self.embed_model, contents=[text],
                                                                       config=cfg)).embeddings
            return _unit(got[0].values)

        with ThreadPoolExecutor(self.PARALLEL) as ex:
            return list(ex.map(one, texts))


def _unit(v) -> list[float]:
    """Reduced-dimension Gemini embeddings are not unit length; normalise so cosine distance is well behaved."""
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class _ComposedProvider:
    """Generation from `llm`, embeddings from a separate embedder (e.g. Voyage). Everything else delegates to `llm`."""
    semantic_embeddings = True

    def __init__(self, llm, embedder):
        self._llm, self._embedder = llm, embedder
        self.embed_model = embedder.embed_model

    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]:
        return self._embedder.embed(texts, query=query)

    def __getattr__(self, name):
        return getattr(self._llm, name)


def make_provider(settings) -> Provider:
    llm = _make_llm(settings)
    if getattr(settings, "embed_provider", "gemini") == "voyage":
        from .voyage import VoyageEmbedder
        emb = VoyageEmbedder(settings.voyage_api_key, settings.voyage_model, settings.voyage_dim,
                             settings.voyage_tokens_per_min, settings.voyage_request_tokens,
                             settings.voyage_requests_per_min)
        return _ComposedProvider(llm, emb)
    if getattr(settings, "embed_provider", "gemini") == "vertex":
        emb = VertexEmbedder(project=settings.gcp_project, location=settings.gcp_location,
                             embed_model=settings.vertex_embed_model)
        return _ComposedProvider(llm, emb)
    return llm


def _make_llm(settings) -> Provider:
    if settings.provider in ("gemini", "vertex"):
        return GeminiProvider(api_key=settings.gemini_api_key if settings.provider == "gemini" else "",
                              project=settings.gcp_project, location=settings.gcp_location,
                              gen_model=settings.gen_model, embed_model=settings.embed_model,
                              fallback_models=tuple(m for m in settings.gen_fallback_models.split(',') if m.strip()),
                              backup_api_key=settings.gemini_api_key_backup if settings.provider == "gemini" else "",
                              backup_for_index=settings.embed_backup_for_index)
    return OfflineProvider()
