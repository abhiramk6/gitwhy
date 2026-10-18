"""The Vertex embedder: batched text-embedding-005 by default, one-text-per-request gemini-embedding-001, 768-d unit vectors."""
import math
import types

import pytest

from app.config import Settings
from app.models import provider as P


class _FakeModels:
    def __init__(self):
        self.calls = []

    def embed_content(self, model, contents, config):
        self.calls.append((model, list(contents), config.task_type, config.output_dimensionality))
        return types.SimpleNamespace(embeddings=[
            types.SimpleNamespace(values=[float(len(t))] + [0.5] * (P.EMBED_DIM - 1)) for t in contents])


class _FakeClient:
    last = None

    def __init__(self, **kw):
        self.kw, self.models = kw, _FakeModels()
        _FakeClient.last = self


@pytest.fixture()
def fake_vertex(monkeypatch):
    import google.genai as genai
    monkeypatch.setattr(genai, "Client", _FakeClient)
    monkeypatch.setattr(P.VertexEmbedder, "EMBED_MIN_INTERVAL_S", 0.0)


def _provider(**kw):
    return P.make_provider(Settings(provider="offline", embed_provider="vertex", gcp_project="proj",
                                    gcp_location="us-central1", **kw))


def _unit(v):
    return abs(math.sqrt(sum(x * x for x in v)) - 1.0) < 1e-9


def test_default_model_is_batched_and_keeps_order(fake_vertex):
    prov = _provider()
    assert prov.embed_model == "text-embedding-005"
    assert _FakeClient.last.kw["vertexai"] is True and _FakeClient.last.kw["project"] == "proj"
    texts = ["a" * n for n in (3, 9, 5, 7)]
    out = prov.embed(texts)
    assert len(out) == 4 and all(len(v) == P.EMBED_DIM and _unit(v) for v in out)
    calls = _FakeClient.last.models.calls
    assert len(calls) == 1 and calls[0][1] == texts and calls[0][2] == "RETRIEVAL_DOCUMENT"   # one request, in order
    assert out[0][0] < out[1][0]   # vectors line up with their texts (first component grows with length, then is normalised)


def test_large_input_is_split_by_request_size_not_dropped(fake_vertex):
    prov = _provider()
    texts = ["x" * 20_000 for _ in range(7)]            # 140k chars -> several requests of <= 48k chars
    out = prov.embed(texts)
    assert len(out) == 7
    calls = _FakeClient.last.models.calls
    assert len(calls) > 1 and all(sum(len(t) for t in c[1]) <= P.VertexEmbedder.EMBED_REQUEST_CHARS + 20_000 for c in calls)
    assert sum(len(c[1]) for c in calls) == 7


def test_gemini_embedding_model_sends_one_text_per_request(fake_vertex):
    prov = _provider(vertex_embed_model="gemini-embedding-001")
    out = prov.embed(["alpha", "beta beta", "gamma"])
    assert len(out) == 3 and all(_unit(v) for v in out)
    calls = _FakeClient.last.models.calls
    assert sorted(c[1][0] for c in calls) == ["alpha", "beta beta", "gamma"] and all(len(c[1]) == 1 for c in calls)


def test_queries_use_the_query_task_type(fake_vertex):
    prov = _provider()
    prov.embed(["why cursor pagination"], query=True)
    assert _FakeClient.last.models.calls[-1][2] == "RETRIEVAL_QUERY"
