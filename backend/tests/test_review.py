"""PR review drafts: evidence guard, superseded decisions, quotes, no external posting."""
import inspect
from pathlib import Path

import pytest

from app.ingestion.fixtures import ingest
from app.knowledge.build_graph import build
from app.models.provider import OfflineProvider
from app.review import reviewer
from app.review.reviewer import draft_review, render
from tests.fake_model import ideal_provider

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "northwind"


def provider(responder):
    return ideal_provider(choose=lambda p: ["customer-portal"], pr_review=responder)


@pytest.fixture()
def org(conn):
    P = ideal_provider(choose=lambda p: ["customer-portal"])
    org_id, _ = ingest(conn, FIX)
    build(conn, org_id, P)
    return org_id


def adr(packet, name, status="active"):
    return next(d for d in packet["decisions"] if d["adr"] == name and d["status"] == status)


def test_guard_keeps_supported_comments_and_discards_the_rest(conn, org):
    def responder(p):
        d4 = adr(p, "ADR-004")
        sup = next((d for d in p["decisions"] if d["status"] == "superseded"), None)
        out = [
            {"type": "decision_violation", "file": p["pull_request"]["files"][0], "evidence": [d4["id"]],
             "comment": "Outbound HTTP must go through the platform client.", "trigger": "requests",
             "quote": "Every outbound HTTP call must use `platform_libs.http_client.request`"},
            {"type": "decision_violation", "file": "", "evidence": [d4["id"]],
             "comment": "Invented rule.", "quote": "All calls must be signed with HMAC"},          # quote not in ADR
            {"type": "other", "file": "", "evidence": ["fact:999999"], "comment": "Made up.", "quote": ""},  # unknown id
            {"type": "ownership_risk", "file": "not/in/pr.py", "evidence": [p["ownership"][0]["id"]] if p["ownership"] else [d4["id"]],
             "comment": "Concentrated ownership.", "quote": ""},                                   # file not in PR -> nulled
        ]
        if sup:
            out.append({"type": "decision_violation", "file": "", "evidence": [sup["id"]],
                        "comment": "Violates a superseded decision.", "quote": sup["text"][:40]})
        return {"comments": out, "nothing_to_say": False}

    review = draft_review(conn, org, provider(responder), "customer-portal", 57)
    assert review["status"] == "draft"
    kinds = [(c["type"], c["file"]) for c in review["comments"]]
    assert ("decision_violation", review["comments"][0]["file"]) in kinds and review["comments"][0]["file"]
    assert all(c["evidence"] for c in review["comments"])                    # nothing without evidence survives
    assert not any("Invented" in c["comment"] or "Made up" in c["comment"] for c in review["comments"])
    assert any(c["file"] is None for c in review["comments"] if c["type"] == "ownership_risk")  # unknown file nulled
    reasons = " ".join(d["reason"] for d in review["dropped"])
    assert "quote not found" in reasons and "no valid evidence" in reasons
    assert not any(d["reason"].startswith("violation of a superseded") for d in review["dropped"]) or "superseded" in reasons
    assert review["comments"][0]["label"] in ("verified", "inferred")
    md = render(review)
    assert md.startswith("# DRAFT review") and "NOT POSTED" in md


def test_silence_when_nothing_is_supported(conn, org):
    review = draft_review(conn, org, provider(lambda p: {"comments": [], "nothing_to_say": True}), "notify-svc", 41)
    assert review["comments"] == [] and review["nothing_to_say"] is True
    assert "Nothing to say" in render(review)


def test_without_a_model_nothing_is_invented(conn, org):
    review = draft_review(conn, org, OfflineProvider(), "customer-portal", 57)
    assert review["status"] == "llm_required" and review["comments"] == []


def test_module_cannot_post_anywhere():
    src = inspect.getsource(reviewer)
    for banned in ("import requests", "urllib", "httpx", "http.client", "subprocess", "socket", "smtplib", "gh api"):
        assert banned not in src, banned


def test_dependency_impact_must_cite_a_consumer_of_the_changed_service(conn, org):
    def responder(p):
        down = next(d for d in p["dependency_impact"] if d["relation"] == "changed_service_depends_on")
        return {"comments": [{"type": "dependency_impact", "file": "", "quote": "x", "evidence": down["evidence"],
                              "comment": "Affects payments-api."}], "nothing_to_say": False}

    review = draft_review(conn, org, provider(responder), "customer-portal", 57)
    assert review["comments"] == []
    assert any("consumer" in d["reason"] for d in review["dropped"])


def test_reuse_opportunity_needs_a_reuse_finding_and_dependency_impact_is_deduplicated(conn, org):
    def responder(p):
        reuse = p["reuse"][0] if p["reuse"] else None
        consumers = [d for d in p["dependency_impact"] if d["relation"] == "depends_on_changed_service"]
        out = [{"type": "reuse_opportunity", "file": "", "quote": "", "evidence": [p["decisions"][0]["id"]],
                "comment": "Reuse something (cites a decision, not a reuse finding)."}]
        if reuse:
            out.append({"type": "reuse_opportunity", "file": "", "quote": "", "evidence": [reuse["id"]],
                        "comment": "Use the existing IdempotencyStore instead of a new de-dupe store."})
        for d in consumers[:2]:
            out.append({"type": "dependency_impact", "file": "", "quote": "", "evidence": d["evidence"],
                        "comment": f"Check compatibility for {d['service']}."})
        return {"comments": out, "nothing_to_say": False}

    review = draft_review(conn, org, provider(responder), "notify-svc", 48)
    kinds = [c["type"] for c in review["comments"]]
    assert kinds.count("reuse_opportunity") == 1 and "IdempotencyStore" in review["comments"][0]["comment"]
    assert kinds.count("dependency_impact") <= 1
    assert any("does not cite a reuse finding" in d["reason"] for d in review["dropped"])


def test_past_guidance_needs_the_reviewers_exact_words(conn):
    quote = "Please don't add offset pagination"
    cid = "payments-api#6/review_comment-9001"

    def guidance(p):
        c = next(x for x in p["comments"] if x["id"] == cid)
        return {"guidance": [{"id": cid, "topic": "pagination", "guidance": "Use cursors.", "scope": "org",
                              "reason": "skipped rows", "quote": quote}]} if c else {"guidance": []}

    org_id, _ = ingest(conn, FIX)
    build(conn, org_id, ideal_provider(choose=lambda p: ["payments-api"], review_guidance=guidance))

    def responder(p):
        g = p["team_guidance"][0]
        assert g["said_by"] == "priya.raman" and g["date"] == "2026-06-08" and quote in g["exact_words"]
        base = {"type": "past_guidance", "file": "payments/api.py", "evidence": [g["id"]], "comment": "Use cursors.", "trigger": "offset paging"}
        return {"comments": [{**base, "quote": "Please DON'T add `offset pagination`"},       # formatting/case ignored
                             {**base, "comment": "Invented.", "quote": "never use page numbers anywhere"},
                             {**base, "comment": "No guidance cited.", "evidence": [p["decisions"][0]["id"]],
                              "quote": quote}], "nothing_to_say": False}
    out = draft_review(conn, org_id, provider(responder), "payments-api", 11)
    assert [c["type"] for c in out["comments"]] == ["past_guidance"] and out["comments"][0]["quote"]
    assert len(out["dropped"]) == 2


def test_line_level_only_where_the_stored_diff_shows_it(conn):
    quote = "Please don't add offset pagination"
    cid = "payments-api#6/review_comment-9001"

    def guidance(p):
        return {"guidance": [{"id": cid, "topic": "pagination", "guidance": "Use cursors.", "scope": "org",
                              "reason": "skipped rows", "quote": quote}]} if any(x["id"] == cid for x in p["comments"]) else {"guidance": []}

    org_id, _ = ingest(conn, FIX)
    build(conn, org_id, ideal_provider(choose=lambda p: ["payments-api"], review_guidance=guidance))

    def responder(p):
        g = p["team_guidance"][0]
        assert p["diff_available"] and "OFFSET" in p["diff"][0]["changes"]
        base = {"type": "past_guidance", "file": "payments/api.py", "evidence": [g["id"]], "quote": quote, "key": "offset",
                "why_conflict": "The thread asks for cursors; this change pages by offset.", "trigger": "offset paging"}
        return {"comments": [
            {**base, "comment": "A reviewer asked not to use offset paging.", "diff_quote": "LIMIT %s OFFSET %s"},
            {**base, "comment": "Offset paging again; see line 12.", "diff_quote": ""},                 # claims a line it cannot show
            {**base, "comment": "Different wording, same worry.", "diff_quote": "ORDER BY id DESC"},   # not in the diff -> file-level
            {**base, "comment": "Unrelated topic.", "diff_quote": "", "trigger": "kubernetes operator"},  # nothing in the PR matches
        ], "nothing_to_say": False}

    review = draft_review(conn, org_id, provider(responder), "payments-api", 11)
    good = review["comments"][0]
    assert good["in_pr"]["file"] == "payments/api.py" and good["in_pr"]["line"] == 48 and "OFFSET" in good["in_pr"]["text"]
    assert good["earlier"]["who"] == "priya.raman" and good["earlier"]["when"] == "2026-06-08" and good["earlier"]["quote"] and good["why"]
    assert any("does not show" in d["reason"] for d in review["dropped"])
    assert any("nothing in the PR" in d["reason"] for d in review["dropped"]) and len(review["comments"]) == 2
    assert good["trigger"]["where"] == "diff" and good["trigger"]["line"] == 48 or good["trigger"]["where"] == "description"
    assert [c["in_pr"] for c in review["comments"][1:]] == [None]


def test_diff_parsing():
    from app.review import diffs
    patch = "@@ -1,3 +10,4 @@ def f():\n ctx\n-old\n+new one\n+new two\n tail"
    assert diffs.added_lines(patch) == [(11, "new one"), (12, "new two")]
    assert diffs.locate({"a.py": patch}, "NEW  two") == ("a.py", 12, "new two")
    assert diffs.locate({"a.py": patch}, "old") is None and diffs.locate({"a.py": patch}, "ctx") is None
    assert diffs.claims_a_line("see line 42") and not diffs.claims_a_line("the outline of it")
