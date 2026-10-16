"""Voyage AI embeddings (hosted, REST). Used for embeddings only; text generation stays with the configured LLM provider.

No retry loops: a 429 / quota answer raises QuotaExhausted (the caller stops and records it); other errors raise
RuntimeError. Requests are sized by an estimated token budget and paced to `tokens_per_min` when one is set, so the
rate limit is respected up front instead of being hit and retried.
"""
from __future__ import annotations

import time

import httpx

from .provider import CHARS_PER_TOKEN, QuotaExhausted

URL = "https://api.voyageai.com/v1/embeddings"


class VoyageEmbedder:
    def __init__(self, api_key: str, model: str = "voyage-4-large", dim: int = 1024, tokens_per_min: int = 0,
                 request_tokens: int = 20000, timeout_s: float = 60.0, client: httpx.Client | None = None):
        self.api_key, self.embed_model, self.dim = api_key, model, dim
        self.tokens_per_min, self.request_tokens = tokens_per_min, request_tokens
        self.client = client or httpx.Client(timeout=timeout_s)
        self.total_tokens = 0       # as billed/counted by the API (usage.total_tokens)
        self.calls = 0
        self._window: list[tuple[float, int]] = []

    def _pace(self, tokens: int) -> None:
        if not self.tokens_per_min:
            return
        now = time.monotonic()
        self._window = [(t, n) for t, n in self._window if now - t < 60]
        while self._window and sum(n for _, n in self._window) + tokens > self.tokens_per_min:
            wait = 60 - (time.monotonic() - self._window[0][0]) + 0.5
            time.sleep(max(wait, 0.5))
            now = time.monotonic()
            self._window = [(t, n) for t, n in self._window if now - t < 60]
        self._window.append((time.monotonic(), tokens))

    def _requests(self, texts: list[str]) -> list[list[int]]:
        groups, cur, used = [], [], 0
        for i, t in enumerate(texts):
            est = int(len(t) / CHARS_PER_TOKEN) + 1
            if cur and used + est > self.request_tokens:
                groups.append(cur)
                cur, used = [], 0
            cur.append(i)
            used += est
        if cur:
            groups.append(cur)
        return groups

    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]:
        out: list[list[float] | None] = [None] * len(texts)
        for idx in self._requests(texts):
            self._pace(sum(int(len(texts[i]) / CHARS_PER_TOKEN) + 1 for i in idx))
            body = {"input": [texts[i] for i in idx], "model": self.embed_model, "output_dimension": self.dim,
                    "input_type": "query" if query else "document"}
            r = self.client.post(URL, json=body, headers={"Authorization": f"Bearer {self.api_key}"})
            self.calls += 1
            if r.status_code == 429:
                retry = float(r.headers.get("retry-after") or 60)
                raise QuotaExhausted(f"Voyage rate/quota limit (429): {r.text[:160]}", retry)
            if r.status_code >= 400:
                raise RuntimeError(f"Voyage embeddings HTTP {r.status_code}: {r.text[:200]}")
            data = r.json()
            rows = sorted(data["data"], key=lambda d: d["index"])
            if len(rows) != len(idx) or any(len(d["embedding"]) != self.dim for d in rows):
                raise RuntimeError("Voyage returned an unexpected number of vectors or dimension")
            self.total_tokens += int((data.get("usage") or {}).get("total_tokens", 0))
            for i, d in zip(idx, rows):
                out[i] = d["embedding"]
        return out  # type: ignore[return-value]
