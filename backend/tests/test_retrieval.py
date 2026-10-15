from pathlib import Path

import pytest

from app.ingestion.fixtures import ingest
from app.knowledge.build_graph import build
from app.models.provider import EMBED_DIM, OfflineProvider
from app.retrieval.embed import embed_org
from app.retrieval.search import search

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "northwind"
P = OfflineProvider()


@pytest.fixture()
def org(conn):
    org_id, _ = ingest(conn, FIX)
    build(conn, org_id)
    embed_org(conn, org_id, P)
    return org_id


def test_embeddings_cached_and_commits_not_embedded(conn, org):
    again = embed_org(conn, org, P)
    assert again["embedded"] == 0 and again["cached"] == again["candidates"] > 0
    n = conn.execute("SELECT count(*) n FROM embeddings e JOIN source_records s ON s.id=e.owner_id "
                     "WHERE e.owner_table='source_records' AND s.source_type='github_commit'").fetchone()["n"]
    assert n == 0


def test_offline_embedding_shape_and_determinism():
    a, b = P.embed(["partial refunds"])[0], P.embed(["partial refunds"])[0]
    assert len(a) == EMBED_DIM and a == b


def test_exact_identifier_ranks_first(conn, org):
    hits = search(conn, org, P, "what is blocking PAY-142?")
    assert hits[0].source_id == "PAY-142"


def test_semantic_queries_find_the_right_evidence(conn, org):
    h = search(conn, org, P, "outbound http timeouts retries standard", k=5)
    assert any("ADR-004" in x.source_id or "ADR-004" in x.title for x in h)
    h = search(conn, org, P, "who knows how reconciliation works and is anyone inactive", k=6)
    assert any(x.kind == "fact" and "dana.okafor" in x.snippet for x in h)


def test_fusion_uses_multiple_signals(conn, org):
    h = search(conn, org, P, "idempotency duplicate notifications dedupe", k=5)
    assert any(len(x.signals) >= 2 for x in h)
    assert all(x.status != "rejected" for x in h if x.kind == "fact")
