from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn, settings_dep
from app.config import Settings
from app.ingestion.fixtures import ingest
from app.knowledge.build_graph import build
from app.main import app
from app.models.provider import OfflineProvider
from app.retrieval.embed import embed_org

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "northwind"
TOKEN = {"X-Demo-Token": "t0ken"}
REQ = "Add support for partial refunds on captured payments (PAY-142)"


@pytest.fixture()
def client(conn):
    org_id, _ = ingest(conn, FIX)
    build(conn, org_id)
    embed_org(conn, org_id, OfflineProvider())
    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[settings_dep] = lambda: Settings(demo_token="t0ken", environment="test", org_slug="northwind")
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_overview_has_repos_and_alerts(client):
    j = client.get("/api/overview").json()
    assert {r["name"] for r in j["repositories"]} == {"ledger-core", "payments-api", "notify-svc", "customer-portal", "platform-libs"}
    kinds = {a["fact_type"] for a in j["alerts"]}
    assert {"ownership", "risk", "override", "conflict", "reuse"} <= kinds
    assert j["organization"]["is_synthetic"] is True


def test_graph_contains_known_dependency_with_evidence(client):
    g = client.get("/api/graph").json()
    names = {n["id"]: n["name"] for n in g["nodes"]}
    deps = {(names[e["src"]], names[e["dst"]]) for e in g["edges"] if e["rel"] == "depends_on"}
    assert ("payments-api", "ledger-core") in deps and ("customer-portal", "payments-api") in deps
    assert all(e["label"] in ("verified", "inferred") for e in g["edges"])


def test_entity_detail_and_404(client):
    g = client.get("/api/graph").json()
    pid = next(n["id"] for n in g["nodes"] if n["name"] == "payments-api")
    d = client.get(f"/api/entities/{pid}").json()
    assert any(o["other"] == "ledger-core" for o in d["outbound"])
    assert client.get("/api/entities/999999").status_code == 404


def test_writes_require_token(client):
    assert client.post("/api/plans", json={"request": REQ}).status_code == 401
    assert client.post("/api/plans", json={"request": REQ}, headers={"X-Demo-Token": "wrong"}).status_code == 401
    assert client.post("/api/memory/remember", json={"text": "x y z", "author": "a"}).status_code == 401


def test_plan_create_fetch_and_approve(client):
    p = client.post("/api/plans", json={"request": REQ}, headers=TOKEN).json()
    comps = {c["service"] for c in p["affected_components"]}
    assert {"payments-api", "ledger-core", "notify-svc", "customer-portal"} <= comps
    assert p["unsupported_claims"] == [] and p["plan_status"] == "draft"
    assert client.get(f"/api/plans/{p['id']}").json()["request"] == REQ
    assert client.post(f"/api/plans/{p['id']}/status", json={"status": "approved"}, headers=TOKEN).json()["status"] == "approved"
    assert client.get("/api/plans").json()[0]["status"] == "approved"


def test_remember_is_idempotent_and_candidate(client):
    body = {"text": "Prefer outbox events for new ledger integrations", "author": "ines.kowalski", "scope": "org"}
    a = client.post("/api/memory/remember", json=body, headers=TOKEN).json()
    b = client.post("/api/memory/remember", json=body, headers=TOKEN).json()
    assert a["created"] and not b["created"] and a["status"] == "candidate"


def test_override_records_rule_reason_and_approver(client):
    r = client.post("/api/memory/override", headers=TOKEN, json={
        "rule": "ADR-004", "reason": "provider needs 30s timeout", "author": "tom.becker", "approver": "ines.kowalski",
        "temporary": True, "repo": "customer-portal"}).json()
    assert r["created"] and r["status"] == "active"
    facts = client.get("/api/knowledge", params={"fact_type": "override"}).json()
    assert any("ADR-004" in f["summary"] and "ines.kowalski" in f["summary"] for f in facts)
    bad = client.post("/api/memory/override", headers=TOKEN, json={"rule": "not-an-adr", "reason": "xxxxx", "author": "a"})
    assert bad.status_code == 422


def test_knowledge_filters_and_curation(client):
    sup = client.get("/api/knowledge", params={"status": "superseded"}).json()
    assert [f["object_value"] for f in sup] == ["ADR-002"]
    cand = client.get("/api/knowledge", params={"status": "candidate", "fact_type": "reuse"}).json()
    assert cand and client.post(f"/api/knowledge/{cand[0]['id']}/status", json={"status": "rejected"}, headers=TOKEN).status_code == 200


def test_search_returns_signals(client):
    hits = client.get("/api/search", params={"q": "PAY-142 partial refunds"}).json()
    assert hits and hits[0]["signals"]


def _rpc(client, method, params=None, id_=1):
    return client.post("/mcp", headers=TOKEN, json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}})


def test_mcp_requires_token(client):
    assert client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401


def test_mcp_handshake_list_and_call(client):
    init = _rpc(client, "initialize").json()["result"]
    assert init["capabilities"] == {"tools": {}} and init["serverInfo"]["name"] == "lore-intelligence"
    assert client.post("/mcp", headers=TOKEN, json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    tools = {t["name"] for t in _rpc(client, "tools/list").json()["result"]["tools"]}
    assert tools == {"search_context", "get_repo_overview", "get_dependencies", "get_decisions",
                     "analyze_feature_impact", "create_feature_plan", "record_memory_candidate"}
    import json
    out = _rpc(client, "tools/call", {"name": "get_dependencies", "arguments": {"services": ["customer-portal"], "depth": 3}}).json()
    payload = json.loads(out["result"]["content"][0]["text"])
    assert {"payments-api", "ledger-core"} <= {d["service"] for d in payload["dependencies"]}
    plan = json.loads(_rpc(client, "tools/call", {"name": "create_feature_plan", "arguments": {"request": REQ}}).json()
                      ["result"]["content"][0]["text"])
    assert plan["tasks"] and plan["evidence"]


def test_mcp_errors(client):
    assert _rpc(client, "tools/call", {"name": "nope", "arguments": {}}).json()["error"]["code"] == -32602
    assert "missing arguments" in _rpc(client, "tools/call", {"name": "search_context", "arguments": {}}).json()["error"]["message"]
    assert _rpc(client, "bogus/method").json()["error"]["code"] == -32601
