"""Ask: citations are mandatory; unsupported statements disappear; follow-ups work without evidence invention."""
from pathlib import Path

import pytest

from app.ask.ask import ask
from app.ingestion.fixtures import ingest
from app.knowledge.build_graph import build
from app.models.provider import OfflineProvider
from tests.fake_model import ideal_provider

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "northwind"


@pytest.fixture()
def org(conn):
    org_id, _ = ingest(conn, FIX)
    build(conn, org_id, ideal_provider(choose=lambda p: ["payments-api"]))
    return org_id


def test_statements_without_a_valid_citation_are_dropped(conn, org):
    def responder(p):
        ev = {e["id"]: e for e in p["evidence"]}
        comment = next(e for e in p["evidence"] if e["type"] == "github_comment" and e["author"] == "priya.raman"
                       and e["date"] == "2026-06-08")                                   # who/when travel with the evidence
        assert "pagination" in comment["text"].lower()
        return {"sufficient": True, "follow_ups": ["Which endpoints still use offset?"], "answer": [
            {"text": "Use cursors, not offset pagination (priya.raman, 2026-06-08).", "cites": [comment["id"]]},
            {"text": "An invented claim.", "cites": ["record:999999"]},
            {"text": "An uncited claim.", "cites": []}]}
    out = ask(conn, org, ideal_provider(choose=lambda p: [], ask=responder), "offset pagination on list endpoints")
    assert out["status"] == "answered" and len(out["answer"]) == 1
    assert out["citations"][0]["author"] == "priya.raman" and out["citations"][0]["url"]
    assert out["follow_ups"] == ["Which endpoints still use offset?"]


def test_no_valid_statements_means_insufficient_not_a_guess(conn, org):
    out = ask(conn, org, ideal_provider(ask=lambda p: {"sufficient": True, "follow_ups": [], "answer": [
        {"text": "Something confident.", "cites": ["nope"]}]}), "offset pagination on list endpoints")
    assert out["status"] == "insufficient" and out["answer"] == [] and out["citations"] == []


def test_ask_without_a_model_says_so(conn, org):
    out = ask(conn, org, OfflineProvider(), "offset pagination on list endpoints")
    assert out["status"] == "llm_required"
