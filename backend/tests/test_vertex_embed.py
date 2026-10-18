"""The Vertex embedder: one text per request, 768-d unit vectors, selected by EMBED_PROVIDER=vertex."""
import math
import sys
import types

from app.config import Settings
from app.models import provider as P


class _FakeModels:
    def __init__(self):
        self.calls = []

    def embed_content(self, model, contents, config):
        self.calls.append((model, list(contents), config.task_type, config.output_dimensionality))
        v = [float(len(contents[0]))] + [0.5] * (P.EMBED_DIM - 1)
        return types.SimpleNamespace(embeddings=[types.SimpleNamespace(values=v)])


class _FakeClient:
    last = None

    def __init__(self, **kw):
        self.kw, self.models = kw, _FakeModels()
        _FakeClient.last = self


def test_vertex_embedder_sends_one_text_per_request_and_returns_unit_vectors(monkeypatch):
    import google.genai as genai
    monkeypatch.setattr(genai, "Client", _FakeClient)
    s = Settings(provider="offline", embed_provider="vertex", gcp_project="proj", gcp_location="us-central1")
    prov = P.make_provider(s)
    assert prov.embed_model == "gemini-embedding-001"
    assert _FakeClient.last.kw["vertexai"] is True and _FakeClient.last.kw["project"] == "proj"

    out = prov.embed(["alpha", "beta beta", "gamma"], query=False)
    assert len(out) == 3 and all(len(v) == P.EMBED_DIM for v in out)
    assert all(abs(math.sqrt(sum(x * x for x in v)) - 1.0) < 1e-9 for v in out)
    calls = _FakeClient.last.models.calls
    assert sorted(c[1][0] for c in calls) == ["alpha", "beta beta", "gamma"]   # one text per request
    assert {c[2] for c in calls} == {"RETRIEVAL_DOCUMENT"} and {c[3] for c in calls} == {P.EMBED_DIM}

    prov.embed(["why cursor pagination"], query=True)
    assert _FakeClient.last.models.calls[-1][2] == "RETRIEVAL_QUERY"
