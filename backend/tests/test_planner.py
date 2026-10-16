from pathlib import Path

import pytest

from app.ingestion.fixtures import ingest
from app.knowledge.build_graph import build
from app.models.provider import OfflineProvider
from app.planning.planner import create_plan, unsupported_claims
from app.retrieval.embed import embed_org
from tests.fake_model import ideal_provider

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "northwind"
REQ = "Add support for partial refunds on captured payments (PAY-142)"


@pytest.fixture()
def P():
    return ideal_provider(choose=lambda p: ["payments-api"])


@pytest.fixture()
def org(conn, P):
    org_id, _ = ingest(conn, FIX)
    build(conn, org_id, P)
    embed_org(conn, org_id, P)
    return org_id


def test_plan_surfaces_graph_decisions_and_judged_risks(conn, org, P):
    plan = create_plan(conn, org, P, REQ)
    comps = {c["service"]: c["role"] for c in plan["affected_components"]}
    assert comps["payments-api"] == "primary"
    assert {"ledger-core", "notify-svc", "customer-portal"} <= set(comps)  # structural impact, not the model
    assert comps["customer-portal"] == "upstream-consumer"
    adrs = {d["adr"] for d in plan["decisions"]}
    assert {"ADR-007", "ADR-004"} <= adrs and "ADR-002" not in adrs  # superseded is not guidance
    types = {r["type"] for r in plan["risks"]}
    assert {"stale_reference", "blocker"} <= types
    assert any("LED-88" in r["summary"] for r in plan["risks"])
    assert any("IdempotencyStore" in r["summary"] for r in plan["reuse_candidates"])


def test_labels_come_from_evidence_not_from_the_model(conn, org, P):
    plan = create_plan(conn, org, P, REQ, persist=False)
    assert unsupported_claims(plan) == []
    for section in ("decisions", "risks", "reuse_candidates"):
        for item in plan[section]:
            kinds = {plan["evidence"][e]["evidence_type"] for e in item["evidence"]}
            assert item["label"] == ("verified" if kinds <= {"structural", "explicit"} and all(
                plan["evidence"][e]["status"] == "active" for e in item["evidence"]) else "inferred")
    assert all(t["label"] == "proposed" for t in plan["tasks"])


def test_guard_discards_unknown_services_decisions_and_evidence(conn, org):
    def plan(p):
        good = ideal_provider().responders["plan"](p)
        good["decisions"].append({"adr": "ADR-999", "guidance": "invented", "evidence": ["fact:99999"]})
        good["decisions"].append({"adr": "ADR-002", "guidance": "superseded", "evidence": []})
        good["risks"].append({"type": "risk", "summary": "made up", "evidence": ["fact:424242"]})
        good["components"].append({"service": "ghost-svc", "needs_change": "yes", "reason": "x", "evidence": []})
        good["tasks"].append({"id": "T99", "title": "x", "service": "ghost-svc", "depends_on": ["T404"],
                              "rationale": "", "evidence": ["nope"]})
        return good

    prov = ideal_provider(choose=lambda p: ["payments-api"], plan=plan)
    out = create_plan(conn, org, prov, REQ, persist=False)
    assert all(d["adr"] not in ("ADR-999", "ADR-002") for d in out["decisions"])
    assert all(r["summary"] != "made up" for r in out["risks"])
    assert "ghost-svc" not in {c["service"] for c in out["affected_components"]}
    t99 = next(t for t in out["tasks"] if t["id"] == "T99")
    assert t99["service"] is None and t99["depends_on"] == [] and t99["evidence"] == []
    assert len(out["dropped_claims"]) >= 4 and unsupported_claims(out) == []


def test_tasks_reference_only_earlier_tasks(conn, org, P):
    plan = create_plan(conn, org, P, REQ, persist=False)
    seen = set()
    for t in plan["tasks"]:
        assert set(t["depends_on"]) <= seen
        seen.add(t["id"])


def test_without_an_llm_the_planner_refuses_instead_of_guessing(conn, org):
    plan = create_plan(conn, org, OfflineProvider(), REQ, persist=False)
    assert plan["status"] == "llm_required" and plan["open_questions"]
    assert conn.execute("SELECT count(*) n FROM feature_plans").fetchone()["n"] == 0


def test_cached_judgments_are_replayed_without_a_model(conn, org, P):
    first = create_plan(conn, org, P, REQ, persist=False)
    replay = create_plan(conn, org, OfflineProvider(), REQ, persist=False)  # no LLM, cached judgments
    assert replay["status"] == "draft"
    assert [d["adr"] for d in replay["decisions"]] == [d["adr"] for d in first["decisions"]]


def test_model_saying_insufficient_evidence_is_honoured(conn, org):
    prov = ideal_provider(choose=lambda p: [])
    plan = create_plan(conn, org, prov, "Train a recommendation model for advertising banners", persist=False)
    assert plan["status"] == "insufficient_evidence" and plan["open_questions"]


def test_persisted_plan(conn, org, P):
    create_plan(conn, org, P, REQ)
    assert conn.execute("SELECT count(*) n FROM feature_plans").fetchone()["n"] == 1


def test_acceptance_criteria_belong_to_real_tasks_and_are_proposals(conn):
    from pathlib import Path
    from app.ingestion.fixtures import ingest
    from app.knowledge.build_graph import build
    from app.planning.planner import create_plan, unsupported_claims
    from tests.fake_model import ideal_provider
    P = ideal_provider(choose=lambda p: ["payments-api"])
    org_id, _ = ingest(conn, Path(__file__).resolve().parents[2] / "fixtures" / "northwind")
    build(conn, org_id, P)
    plan = create_plan(conn, org_id, P, "Add partial refunds to payments-api", persist=False)
    ids = {t["id"] for t in plan["tasks"]}
    assert plan["acceptance_criteria"] and all(a["task"] in ids and a["label"] == "proposed" for a in plan["acceptance_criteria"])
    assert any("unknown task 'T99'" in d for d in plan["dropped_claims"]) and unsupported_claims(plan) == []
