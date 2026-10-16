from pathlib import Path

import pytest

from app.archaeology.archaeology import profile, trail
from app.ingestion.fixtures import ingest

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "northwind"


def test_profile_extracts_comments_docstrings_and_function_style():
    src = '''"""mod doc"""
# first comment
def a_func(x: int, y) -> int:
    """Does a thing.

    more"""
    return x  # trailing note

async def BadName(z): pass
'''
    p = profile(src)
    assert [c["text"] for c in p["comments"]] == ["first comment", "trailing note"]
    s = p["style"]
    assert (s["functions"], s["args_total"], s["args_annotated"], s["returns_annotated"], s["with_docstring"]) == (2, 3, 1, 1, 1)
    assert (s["snake_case"], s["async"]) == (1, 1) and p["module_doc"] == "mod doc"
    assert profile("def broken(:")["functions"] == []             # unparsable => empty, never an exception


def test_trail_links_commits_prs_threads_and_tickets(conn):
    org, _ = ingest(conn, FIX)
    t = trail(conn, org, "notify-svc", "notify/dedupe.py")
    kinds = [e["kind"] for e in t["events"]]
    assert {"commit", "pull_request", "discussion", "ticket"} <= set(kinds)
    thread = [e for e in t["events"] if e["kind"] == "discussion" and e["ref"] == "notify-svc#48"]
    assert any("IdempotencyStore" in e["body"] for e in thread)       # the reviewer's question is in the trail
    assert trail(conn, org, "notify-svc", "no/such.py") is None


def test_explain_points_must_cite_trail_items_and_keys_must_be_in_text(conn):
    from app.archaeology.archaeology import explain
    from tests.fake_model import ideal_provider
    org, _ = ingest(conn, FIX)
    rid = next(e["id"] for e in trail(conn, org, "notify-svc", "notify/dedupe.py")["events"] if e["kind"] == "discussion")

    def responder(p):
        assert any(h["id"] == rid for h in p["history"])
        return {"headline": {"text": "A reviewer asked why a second store exists.", "cites": [rid], "key": "a second store"},
                "points": [{"text": "Uncited claim.", "cites": [], "key": ""},
                           {"text": "Made-up id.", "cites": ["record:0"], "key": ""},
                           {"text": "Real point.", "cites": [rid], "key": "not in text"}]}
    out = explain(conn, org, ideal_provider(trace_explain=responder), "notify-svc", "notify/dedupe.py")
    assert out["headline"]["key"] == "a second store"
    assert [p["text"] for p in out["points"]] == ["Real point."] and out["points"][0]["key"] == ""
