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


def test_paid_mode_stops_at_the_dollar_cap_and_ledger_persists(conn):
    from app.retrieval.embed import embed_org, est_spend_tokens
    org = _seed_tiers(conn)
    prov = Recording()
    # price chosen so each ~10-char chunk costs ~$0.01 (4 tokens est. at $2,500/M); cap $0.03 stops before the 4th batch item
    res = embed_org(conn, org, prov, max_usd=0.03, price_per_mtok=2500.0)
    assert "spend cap" in res["stopped"] and res["pending"] > 0
    assert est_spend_tokens(conn, prov.embed_model) * 2500.0 / 1e6 <= 0.03          # never exceeds the cap
    n = prov.n
    res2 = embed_org(conn, org, prov, max_usd=0.03, price_per_mtok=2500.0)          # cap is cumulative across passes
    assert prov.n == n and "spend cap" in res2["stopped"]


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


def test_backup_key_is_used_for_queries_but_not_for_index_unless_allowed():
    from app.models.provider import GeminiProvider, QuotaExhausted

    class Fake:
        def __init__(self, fail):
            self.fail, self.calls, self.usage = fail, 0, {"calls": 0, "prompt_tokens": 0, "output_tokens": 0,
                                                          "retries": 0, "fallbacks": 0}
            self.last_model = "m"

        def _embed_once(self, texts, query=False):
            self.calls += 1
            if self.fail:
                raise QuotaExhausted("cap", 100)
            return [[1.0] + [0.0] * 767 for _ in texts]

        def _generate_json_once(self, s, u, sch):
            self.calls += 1
            if self.fail:
                raise RuntimeError("no model produced a valid answer")
            return {"ok": True}

    g = GeminiProvider.__new__(GeminiProvider)
    g.usage = {"calls": 0, "prompt_tokens": 0, "output_tokens": 0, "retries": 0, "fallbacks": 0, "backup_calls": 0}
    g.last_model, g.backup_for_index = "m", False
    primary, backup = Fake(True), Fake(False)
    g._embed_once, g._generate_json_once, g._backup = primary._embed_once, primary._generate_json_once, backup
    assert g.embed(["q"], query=True) and backup.calls == 1             # query embedding falls back
    with pytest.raises(QuotaExhausted):
        g.embed(["chunk"], query=False)                                  # index embedding does NOT, by default
    assert backup.calls == 1
    g.backup_for_index = True
    assert g.embed(["chunk"], query=False) and backup.calls == 2        # only when the owner allows it
    assert g.generate_json("s", "u", {}) == {"ok": True} and g.usage["backup_calls"] == 3


def _voyage(handler, **kw):
    import httpx
    from app.models.voyage import VoyageEmbedder
    return VoyageEmbedder("k", client=httpx.Client(transport=httpx.MockTransport(handler)), **kw)


def test_voyage_orders_sizes_and_counts_tokens():
    import json
    import httpx
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        assert req.headers["authorization"] == "Bearer k" and body["output_dimension"] == 1024
        data = [{"index": i, "embedding": [float(len(t))] + [0.0] * 1023} for i, t in enumerate(body["input"])][::-1]  # shuffled
        return httpx.Response(200, json={"data": data, "usage": {"total_tokens": 7}})

    emb = _voyage(handler, request_tokens=10)             # 30 chars ~ 11 est. tokens each => one text per request
    out = emb.embed(["a" * 30, "b" * 3, "c" * 30], query=True)
    assert [v[0] for v in out] == [30.0, 3.0, 30.0] and len(seen) == 3 and seen[0]["input_type"] == "query"
    assert emb.total_tokens == 21 and emb.calls == 3


def test_voyage_429_stops_and_wrong_dimension_fails():
    import httpx
    import pytest
    from app.models.provider import QuotaExhausted

    emb = _voyage(lambda r: httpx.Response(429, headers={"retry-after": "42"}, text="slow down"))
    with pytest.raises(QuotaExhausted) as e:
        emb.embed(["x"])
    assert e.value.retry_after_s == 42 and emb.calls == 1          # one attempt, no retry
    bad = _voyage(lambda r: httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1]}], "usage": {}}))
    with pytest.raises(RuntimeError):
        bad.embed(["x"])


def test_review_guidance_keeps_only_quoted_candidates_and_scopes(conn):
    from app.knowledge.judgments import review_guidance
    org = org_id(conn)
    comments = [{"id": "r#1/review_comment-1", "repo": "r", "pr": "r#1", "author": "a", "date": "2026-01-01", "path": None,
                 "text": "Please don't use offset pagination here. It skipped rows under concurrent writes."},
                {"id": "r#1/pr_comment-2", "repo": "r", "pr": "r#1", "author": "b", "date": "2026-01-02", "path": None,
                 "text": "LGTM, thanks!"}]
    good = {"id": comments[0]["id"], "topic": "pagination", "guidance": "Use cursors, not offsets.", "scope": "org",
            "reason": "rows skipped", "quote": "don't use offset pagination here"}
    prov = ScriptedProvider({"review_guidance": lambda p: {"guidance": [
        good,
        {**good, "quote": "this sentence was invented"},                      # not literally in the comment
        {**good, "id": "r#9/ghost-9"},                                         # not a candidate
        {**good, "scope": "galaxy"}]}})
    out = review_guidance(conn, org, prov, comments, batch=8)
    assert [g["id"] for g in out] == [comments[0]["id"]] and out[0]["comment"]["author"] == "a"
