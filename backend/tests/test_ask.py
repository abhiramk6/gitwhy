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
    assert sorted(d["text"] for d in out["dropped"]) == ["An invented claim.", "An uncited claim."]   # visible on request


def test_no_valid_statements_means_insufficient_not_a_guess(conn, org):
    out = ask(conn, org, ideal_provider(ask=lambda p: {"sufficient": True, "follow_ups": [], "answer": [
        {"text": "Something confident.", "cites": ["nope"]}]}), "offset pagination on list endpoints")
    assert out["status"] == "insufficient" and out["answer"] == [] and out["citations"] == []


def test_ask_without_a_model_says_so(conn, org):
    out = ask(conn, org, OfflineProvider(), "offset pagination on list endpoints")
    assert out["status"] == "llm_required"


def test_headline_key_and_proof_must_be_real_words(conn, org):
    def responder(p):
        c = next(e for e in p["evidence"] if e["type"] == "github_comment" and e["author"] == "priya.raman" and e["date"] == "2026-06-08")
        words = " ".join(c["text"].split()[:6])
        return {"sufficient": True, "follow_ups": [],
                "headline": {"text": "Use cursors, not offset paging.", "cites": [c["id"]], "key": "not offset paging",
                             "proof": words},
                "answer": [{"text": "Priya set this in June.", "cites": [c["id"]], "key": "invented phrase", "proof": "words nobody wrote"}]}
    out = ask(conn, org, ideal_provider(ask=responder), "offset pagination on list endpoints")
    assert out["headline"]["key"] == "not offset paging" and out["headline"]["proof"]
    assert out["answer"][0]["key"] == "" and out["answer"][0]["proof"] == ""          # highlight / proof not in the text: dropped
    assert [p["quote"] for p in out["proof"]] == [out["headline"]["proof"]]
