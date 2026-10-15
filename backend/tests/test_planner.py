from pathlib import Path

import pytest

from app.ingestion.fixtures import ingest
from app.knowledge.build_graph import build
from app.models.provider import OfflineProvider
from app.planning.planner import create_plan, unsupported_claims
from app.retrieval.embed import embed_org

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "northwind"
P = OfflineProvider()
REQ = "Add support for partial refunds on captured payments (PAY-142)"


@pytest.fixture()
def org(conn):
    org_id, _ = ingest(conn, FIX)
    build(conn, org_id)
    embed_org(conn, org_id, P)
    return org_id


def test_partial_refund_plan_matches_known_answers(conn, org):
    plan = create_plan(conn, org, P, REQ)
    comps = {c["service"]: c["role"] for c in plan["affected_components"]}
    # the request "looks like" payments-api only; impact analysis must surface the rest
    assert comps["payments-api"] == "primary"
    assert {"ledger-core", "notify-svc", "customer-portal"} <= set(comps)
    assert comps["customer-portal"] == "upstream-consumer"

    adrs = {d["adr"] for d in plan["decisions"]}
    assert {"ADR-007", "ADR-004", "ADR-003"} <= adrs and "ADR-002" not in adrs  # superseded is not guidance

    kinds = [(r["type"], r["label"]) for r in plan["risks"]]
    assert ("stale_reference", "verified") in kinds          # payments/ledger_client.py still cites ADR-002
    assert any(r["type"] == "risk" and "LED-88" in r["summary"] for r in plan["risks"])
    assert any(r["type"] == "ownership" and "dana.okafor" in r["summary"] for r in plan["risks"])

    assert any("IdempotencyStore" in r["summary"] for r in plan["reuse_candidates"])


def test_tasks_are_ordered_and_blocker_comes_first(conn, org):
    plan = create_plan(conn, org, P, REQ)
    tasks = {t["id"]: t for t in plan["tasks"]}
    first = plan["tasks"][0]
    assert "LED-88" in first["title"] and first["depends_on"] == []
    impl = [t for t in plan["tasks"] if t["service"]]
    assert all(first["id"] in t["depends_on"] for t in impl)
    for t in plan["tasks"]:  # dependency references resolve and are acyclic by construction (ids ascend)
        assert all(d in tasks and int(d[1:]) < int(t["id"][1:]) for d in t["depends_on"])
    svc_order = [t["service"] for t in impl]
    assert svc_order.index("payments-api") < svc_order.index("customer-portal")


def test_every_claim_is_labeled_and_supported(conn, org):
    plan = create_plan(conn, org, P, REQ)
    assert unsupported_claims(plan) == []
    for section in ("affected_components", "decisions", "risks", "reuse_candidates"):
        for item in plan[section]:
            assert item["label"] in ("verified", "inferred") and item["evidence"]
    # inferred knowledge must never be labeled verified
    for eid, e in plan["evidence"].items():
        if e["evidence_type"] == "inferred":
            for section in ("risks", "reuse_candidates", "decisions"):
                for item in plan[section]:
                    if eid in item["evidence"]:
                        assert item["label"] == "inferred"
    assert all(t["label"] == "proposed" for t in plan["tasks"])


def test_plan_is_persisted_and_unlinked_request_asks_questions(conn, org):
    create_plan(conn, org, P, REQ)
    assert conn.execute("SELECT count(*) n FROM feature_plans").fetchone()["n"] == 1
    plan = create_plan(conn, org, P, "zzzz qqqq xxxx", persist=False)
    assert plan["status"] == "insufficient_evidence" and plan["open_questions"]


def test_model_output_with_unsupported_claims_is_discarded(conn, org):
    class Bad(OfflineProvider):
        def generate_json(self, prompt, payload):
            payload = {**payload, "decisions": payload["decisions"] + [
                {"adr": "ADR-999", "summary": "invented", "label": "verified", "evidence": ["fact:99999"]}]}
            return payload

    plan = create_plan(conn, org, Bad(), REQ, persist=False)
    assert all(d["adr"] != "ADR-999" for d in plan["decisions"])
