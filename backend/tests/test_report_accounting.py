"""Run accounting: live calls vs cache replays vs unavailable judgments, and the PASS/FAIL/SKIPPED tally."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from _report import Tally  # noqa: E402
from app.intelligence.judge import meter, run_task  # noqa: E402
from app.models.provider import LLMUnavailable, OfflineProvider  # noqa: E402
from app.models.testing import ScriptedProvider  # noqa: E402

SCHEMA = {"type": "object"}


def org_id(conn):
    return conn.execute("INSERT INTO organizations (slug, name, is_synthetic) VALUES ('acct','acct',true) "
                        "RETURNING id").fetchone()["id"]


def test_meter_separates_live_replayed_and_unavailable(conn):
    meter.reset()
    org = org_id(conn)
    prov = ScriptedProvider({"t": lambda p: {"ok": True}})
    run_task(conn, org, prov, "t", "sys", {"x": 1}, SCHEMA)       # live
    run_task(conn, org, prov, "t", "sys", {"x": 1}, SCHEMA)       # replayed from cache
    assert (meter.live, meter.replayed, meter.unavailable) == (1, 1, 0)
    assert len(prov.calls) == 1 and meter.replay_models == {"scripted": 1}
    offline = OfflineProvider()
    run_task(conn, org, offline, "t", "sys", {"x": 1}, SCHEMA)    # offline replay is visible as a replay
    assert meter.replayed == 2
    with pytest.raises(LLMUnavailable):
        run_task(conn, org, offline, "t", "sys", {"x": 2}, SCHEMA)
    assert meter.unavailable == 1 and meter.by_task["t"] == {"live": 1, "replayed": 2, "unavailable": 1}


def test_tally_skipped_is_not_a_pass():
    t = Tally()
    t.add("PASS"); t.add("SKIPPED")
    assert t.exit_code == 1 and "SKIPPED 1" in t.line() and "not a pass" in t.line()
    ok = Tally()
    ok.add("PASS")
    assert ok.exit_code == 0
    bad = Tally()
    bad.add("FAIL")
    assert bad.exit_code == 1


def test_request_sizing_preserves_every_text_in_order():
    from app.models.provider import GeminiProvider

    g = GeminiProvider.__new__(GeminiProvider)
    texts = [f"{i}:" + "x" * (50 + (i * 997) % 9000) for i in range(300)] + ["y" * 40_000]  # one oversized text
    reqs = list(g._requests(texts))
    assert [t for r in reqs for t in r] == texts          # nothing dropped, merged or reordered
    assert all(len(r) <= 50 for r in reqs)
    assert all(sum(map(len, r)) <= g.EMBED_REQUEST_CHARS or len(r) == 1 for r in reqs)  # only a lone text may exceed


def test_reconcile_reports_missing_and_orphans(conn):
    from app.retrieval.embed import embed_org, reconcile
    from app.models.testing import ScriptedProvider

    org = conn.execute("INSERT INTO organizations (slug, name, is_synthetic) VALUES ('rec','rec',true) RETURNING id").fetchone()["id"]
    conn.execute("INSERT INTO source_records (organization_id, source_type, source_id, title, body, payload, content_hash) "
                 "VALUES (%s,'doc','a','A','alpha text','{}','h1'), (%s,'doc','b','B','','{}','h2')", (org, org))
    prov = ScriptedProvider(semantic=True)
    assert reconcile(conn, org, prov.embed_model)["missing"] != []
    embed_org(conn, org, prov)
    r = reconcile(conn, org, prov.embed_model)
    assert r["wanted"] == r["stored"] == 2 and not r["missing"] and not r["orphaned"]
    assert r["title_only_empty_body"] == 1               # the empty-body record is embedded title-only, and counted


def _seed_tiers(conn):
    org = conn.execute("INSERT INTO organizations (slug, name, is_synthetic) VALUES ('tiers','t',true) RETURNING id").fetchone()["id"]
    for st, sid, body in (("file", "f1", "code body"), ("doc", "d1", "doc body"), ("github_pr", "p1", "pr body"),
                          ("jira_issue", "i1", "issue body"), ("adr", "a1", "adr body")):
        conn.execute("INSERT INTO source_records (organization_id, source_type, source_id, title, body, payload, content_hash) "
                     "VALUES (%s,%s,%s,%s,%s,'{}',%s)", (org, st, sid, sid.upper(), body, sid))
    return org


class Recording(ScriptedProvider):
    def __init__(self, fail_after=None):
        super().__init__(semantic=True)
        self.order, self.fail_after, self.n = [], fail_after, 0

    def embed(self, texts, query=False):
        from app.models.provider import QuotaExhausted
        self.n += 1
        if self.fail_after is not None and self.n > self.fail_after:
            raise QuotaExhausted("daily cap", 3600)
        self.order += [t.split("\n")[0] for t in texts]
        return super().embed(texts, query)


def test_embed_order_is_tiered_and_budget_stops_cleanly(conn):
    from app.retrieval.embed import embed_org, tier_coverage, used_today
    org = _seed_tiers(conn)
    prov = Recording()
    res = embed_org(conn, org, prov, budget=3)
    assert prov.order == ["A1", "I1", "P1"]            # adr -> issue -> pr; docs and code wait
    assert res["embedded"] == 3 and res["pending"] == 2 and "budget" in res["stopped"]
    cov = {r["tier"]: (r["stored"], r["wanted"]) for r in tier_coverage(conn, org, prov.embed_model)}
    assert cov["adr"] == (1, 1) and cov["doc"] == (0, 1) and cov["file"] == (0, 1)
    assert used_today(conn, prov.embed_model) == 3
    res2 = embed_org(conn, org, prov)                    # unlimited second pass finishes the rest, in order
    assert prov.order[3:] == ["D1", "F1"] and res2["pending"] == 0 and res2["stopped"] is None


def test_hard_quota_is_recorded_and_not_retried(conn):
    from app.retrieval.embed import embed_org, exhausted_until
    org = _seed_tiers(conn)
    prov = Recording(fail_after=0)
    res = embed_org(conn, org, prov)
    assert res["embedded"] == 0 and "hard quota" in res["stopped"] and prov.n == 1   # one attempt, no retry
    assert exhausted_until(conn, prov.embed_model) is not None
    prov2 = Recording()
    res2 = embed_org(conn, org, prov2)                   # while exhausted the API is not even called
    assert prov2.n == 0 and "quota exhausted until" in res2["stopped"]


def test_search_degrades_to_lexical_when_query_embedding_quota_is_exhausted(conn):
    from app.models.provider import QuotaExhausted
    from app.retrieval.embed import embed_org
    from app.retrieval.search import search_with_meta

    org = _seed_tiers(conn)
    prov = Recording()
    embed_org(conn, org, prov)
    prov.responders = {
        "query_analysis": lambda p: {"intent": "x", "search_queries": [], "identifiers": [], "answer_sketch": "adr body"},
        "rerank": lambda p: {"ranked": [{"id": c["id"], "relevance": 2, "reason": "r"} for c in p["candidates"]]}}
    prov.fail_after, prov.n = 0, 0          # now every embed() call raises QuotaExhausted
    hits, meta = search_with_meta(conn, org, prov, "adr body")
    assert meta["semantic"] is False and "quota" in meta["vector_error"]
    assert [h.source_id for h in hits]       # lexical results still returned


def test_dev_scoring_buckets_decisions_risks_and_reuse():
    from _score import score_plan

    case = {"required_decisions": ["ADR-106"], "excluded_decisions": ["ADR-105", "ADR-103"],
            "allowed_subjects": [{"glob": "flask:src/flask/sessions.py", "why": "x"}],
            "excluded_subjects": [{"glob": "werkzeug:src/werkzeug/datastructures/*", "why": "noise"}],
            "allowed_reuse_components": [{"name": "itsdangerous", "why": "signer"}]}
    plan = {"decisions": [{"adr": "ADR-106"}, {"adr": "ADR-101"}, {"adr": "ADR-103"}],
            "evidence": {"file:flask:src/flask/sessions.py": {"label": "x", "source": None},
                         "fact:1": {"label": "A authored 9/10 commits to werkzeug/src/werkzeug/datastructures/headers.py",
                                    "source": None}},
            "risks": [{"summary": "sessions risk", "evidence": ["file:flask:src/flask/sessions.py"]},
                      {"summary": "noise", "evidence": ["fact:1"]},
                      {"summary": "no subject", "evidence": []}],
            "reuse_candidates": [{"summary": "use itsdangerous Signer"}, {"summary": "use click helpers"}]}
    r = score_plan(plan, case, {"flask", "werkzeug", "itsdangerous", "click"})
    assert r["decisions_missing"] == [] and r["decisions_excluded_present"] == ["ADR-103"]
    assert r["decisions_unlisted"] == ["ADR-101"]
    assert r["risks_ok"] == 1 and len(r["risks_excluded"]) == 1 and len(r["risks_unlisted"]) == 1
    assert r["reuse_ok"] == 1 and len(r["reuse_unlisted"]) == 1 and r["fail"] is True
