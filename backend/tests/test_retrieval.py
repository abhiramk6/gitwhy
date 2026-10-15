from pathlib import Path

import pytest

from app.ingestion.fixtures import ingest
from app.knowledge.build_graph import build
from app.models.provider import EMBED_DIM, OfflineProvider
from app.retrieval.chunk import chunk_spans
from app.retrieval.embed import embed_org
from app.retrieval.search import search, search_with_meta
from tests.fake_model import ideal_provider, rerank

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "northwind"


@pytest.fixture()
def org(conn):
    org_id, _ = ingest(conn, FIX)
    build(conn, org_id)  # no provider: structural facts only
    return org_id


def test_chunks_tile_the_entire_text():
    text = ("para one line\n" * 40 + "\n\n") * 6 + "x" * 5000
    spans = chunk_spans(text, target=500)
    assert spans[0][0] == 0 and spans[-1][1] == len(text)
    assert all(a[1] == b[0] for a, b in zip(spans, spans[1:]))  # contiguous, nothing dropped
    assert len(spans) > 5


def test_every_chunk_is_embedded_and_cached(conn, org):
    P = ideal_provider(semantic=True)
    first = embed_org(conn, org, P)
    assert first["embedded"] == first["candidates"] > 0
    again = embed_org(conn, org, P)
    assert again["embedded"] == 0 and again["cached"] == first["candidates"]
    multi = conn.execute("SELECT count(*) n FROM embeddings WHERE chunk_index > 0").fetchone()["n"]
    longest = conn.execute("SELECT max(length(body)) m FROM source_records").fetchone()["m"]
    assert (multi > 0) == (longest > 1800)
    n = conn.execute("SELECT count(*) n FROM embeddings e JOIN source_records s ON s.id=e.owner_id "
                     "WHERE e.owner_table='source_records' AND s.source_type='github_commit'").fetchone()["n"]
    assert n == 0


def test_offline_provider_embeds_nothing_and_says_so(conn, org):
    r = embed_org(conn, org, OfflineProvider())
    assert r["embedded"] == 0 and "no semantic embeddings" in r["skipped"]
    assert len(OfflineProvider().embed(["a"])[0]) == EMBED_DIM


def test_offline_search_is_lexical_and_exact_ids_win(conn, org):
    hits, meta = search_with_meta(conn, org, OfflineProvider(), "what is blocking PAY-142?")
    assert meta["mode"] == "lexical" and meta["semantic"] is False
    assert hits[0].source_id == "PAY-142"
    assert all(set(h.signals) <= {"identifier", "keyword"} for h in hits)


def test_model_rerank_drops_irrelevant_and_orders_by_grade(conn, org):
    def graded(p):
        out = rerank(p)
        for i, r in enumerate(out["ranked"]):
            r["relevance"] = 0 if i == 0 else (3 if i == 1 else 1)
        out["ranked"].append({"id": "record:999999", "relevance": 3, "reason": "not a candidate"})
        return out

    P = ideal_provider(rerank=graded)
    hits, meta = search_with_meta(conn, org, P, "outbound http timeouts retries", k=5)
    assert meta["mode"] == "llm+rerank" and meta["dropped_irrelevant"] == 1
    assert hits[0].relevance == 3 and all(h.relevance != 0 for h in hits)
    assert all(h.ref != "record:999999" for h in hits)


def test_superseded_decision_is_flagged_not_hidden(conn, org):
    hits = search(conn, org, OfflineProvider(), "ledger payments communicate synchronous HTTP ADR-002", k=10)
    adr2 = [h for h in hits if h.source_type == "adr" and "ADR-002" in h.source_id]
    assert adr2 and adr2[0].status == "superseded"


def test_snippet_is_the_matching_passage(conn, org):
    h = search(conn, org, OfflineProvider(), "idempotency store dedupe", k=5)
    assert h and all(len(x.snippet) > 0 for x in h)
