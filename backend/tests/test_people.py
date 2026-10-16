"""Knowledge map: computed numbers, and a handover brief whose every item must cite packet evidence."""
from pathlib import Path

import pytest

from app.ingestion.fixtures import ingest
from app.knowledge.build_graph import build
from app.models.provider import OfflineProvider
from app.people.people import handover, profile, roster
from tests.fake_model import ideal_provider

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "northwind"


@pytest.fixture()
def org(conn):
    org_id, _ = ingest(conn, FIX)
    build(conn, org_id, ideal_provider(choose=lambda p: []))
    return org_id


def test_roster_and_profile_are_computed_not_judged(conn, org):
    r = {x["login"]: x for x in roster(conn, org)}
    assert r["dana.okafor"]["commits"] == 36 and r["priya.raman"]["guidance"] == 0   # guidance comes from the model task
    p = profile(conn, org, "dana.okafor")
    top = p["areas"][0]
    assert top["share"] == 1.0 and top["id"] in p["evidence"] and p["evidence"][top["id"]]["evidence_type"] == "structural"
    assert profile(conn, org, "nobody") is None


def test_handover_items_need_cites_that_exist_in_the_packet(conn, org):
    def responder(pk):
        a = pk["areas"][0]["id"]
        mk = lambda t, c: {"text": t, "cites": c}
        return {"summary": "s", "only_they_know": [mk("Real, cited.", [a]), mk("Invented id.", ["area:nope"]),
                                                   mk("No cite.", [])],
                "standards_they_set": [], "open_work": [], "people_to_ask": [], "risks": [], "first_week": []}
    out = handover(conn, org, ideal_provider(handover=responder), "dana.okafor")
    assert out["status"] == "ok" and [i["text"] for i in out["only_they_know"]] == ["Real, cited."]
    assert [c["id"] for c in out["citations"]] == [out["only_they_know"][0]["cites"][0]]


def test_handover_without_a_model_still_returns_the_computed_profile(conn, org):
    out = handover(conn, org, OfflineProvider(), "dana.okafor")
    assert out["status"] == "llm_required" and out["profile"]["areas"]


def test_departure_facts_are_counts_with_their_limits_stated(conn, org):
    p = profile(conn, org, "dana.okafor")
    comp = {c["repo"]: c for c in p["components"]}
    assert comp["ledger-core"]["files"] >= 1 and comp["ledger-core"]["their_touches"] <= comp["ledger-core"]["all_touches"]
    top = p["areas"][0]
    assert isinstance(top["docs_mentioning"], int) and "documents/decisions mentioning the file" in p["evidence"][top["id"]]["label"]
    others = [o for a in p["areas"] for o in a["others"]]
    assert all("still_active" in o for o in others)


def test_poorly_documented_items_follow_the_same_cite_rule(conn, org):
    def responder(pk):
        a = pk["areas"][0]
        assert "documents_mentioning_file" in a and pk["components"]
        return {"summary": "s", "only_they_know": [], "poorly_documented": [{"text": "No document found.", "cites": [a["id"]], "key": "No document"},
                                                                          {"text": "Invented.", "cites": ["area:x"], "key": ""}],
                "standards_they_set": [], "open_work": [], "people_to_ask": [], "risks": [], "first_week": []}
    out = handover(conn, org, ideal_provider(handover=responder), "dana.okafor")
    assert [i["text"] for i in out["poorly_documented"]] == ["No document found."]
