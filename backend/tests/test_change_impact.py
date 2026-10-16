"""Change impact: structure from the graph, judgment guarded by evidence ids and literal quotes."""
from pathlib import Path

import pytest

from app.impact.change_impact import change_impact
from app.ingestion.fixtures import ingest
from app.knowledge.build_graph import build
from app.models.provider import OfflineProvider
from tests.fake_model import ideal_provider

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "northwind"


def provider(responder, seed="ledger-core"):
    return ideal_provider(choose=lambda p: [seed], change_impact=responder)


@pytest.fixture()
def org(conn):
    org_id, _ = ingest(conn, FIX)
    build(conn, org_id, ideal_provider(choose=lambda p: ["ledger-core"]))
    return org_id


def test_callers_come_from_the_graph_and_judgments_are_guarded(conn, org):
    def responder(p):
        callers = [s for s in p["services"] if s["role"] == "caller"]
        assert callers, "ledger-core has callers in the fixture graph"
        c = callers[0]
        rule = next(d for d in p["decisions"] if d["status"] == "active")
        sup = next((d for d in p["decisions"] if d["status"] == "superseded"), None)
        out = {"headline": "Callers may break.", "key": "Callers may break", "insufficient_evidence": False,
               "affected": [{"service": c["service"], "what_could_break": "Check the request format.", "evidence": c["evidence"]},
                            {"service": "made-up-svc", "what_could_break": "x", "evidence": c["evidence"]},
                            {"service": "ledger-core", "what_could_break": "the changed service itself", "evidence": c["evidence"]}],
               "rules": [{"evidence_id": rule["id"], "why_it_matters": "Applies.", "quote": rule["text"].split("\n")[0]},
                         {"evidence_id": rule["id"], "why_it_matters": "Invented.", "quote": "never mentioned anywhere"},
                         {"evidence_id": "fact:999999", "why_it_matters": "Unknown.", "quote": "x"}],
               "risks": [{"type": "risk", "summary": "No evidence.", "evidence": ["fact:999999"]}],
               "checks": [{"check": "Run the callers' contract tests.", "evidence": c["evidence"]}]}
        if sup:
            out["rules"].append({"evidence_id": sup["id"], "why_it_matters": "Old.", "quote": sup["text"].split("\n")[0]})
        return out

    r = change_impact(conn, org, provider(responder), "What could break if I change ledger-core?")
    assert r["status"] == "draft" and r["changed"][0]["service"] == "ledger-core"
    assert [a["service"] for a in r["affected"]] and all(a["evidence"] and a["label"] == "verified" for a in r["affected"])
    assert any(a["what_could_break"] for a in r["affected"]) and all("made-up" not in a["service"] for a in r["affected"])
    assert len(r["rules"]) == 1 and r["rules"][0]["quote"] and r["rules"][0]["label"] in ("verified", "inferred")
    assert r["risks"] == [] and len(r["checks"]) == 1
    why = " ".join(r["dropped"])
    assert "not a dependent" in why and "quote not found" in why and "not a decision or reviewer" in why and "superseded" in why
    assert {n["kind"] for n in r["map"]["nodes"]} >= {"changed", "caller"} and r["map"]["links"]
    assert all(i in r["evidence"] for a in r["affected"] for i in a["evidence"])


def test_every_caller_is_listed_even_if_the_model_says_nothing(conn, org):
    r = change_impact(conn, org, provider(lambda p: {"headline": "", "key": "", "insufficient_evidence": False, "affected": [],
                                                      "rules": [], "risks": [], "checks": []}), "What breaks if ledger-core changes?")
    assert r["affected"] and all(a["what_could_break"] is None for a in r["affected"])


def test_without_a_model_nothing_is_invented(conn, org):
    assert change_impact(conn, org, OfflineProvider(), "What breaks if ledger-core changes?")["status"] == "llm_required"
