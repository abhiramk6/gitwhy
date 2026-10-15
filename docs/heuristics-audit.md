# Heuristics audit (2026-10-15)

## Status after the LLM-layer change

| Item | Result |
|---|---|
| A1-A9 planner judgments (service choice, API-path regex, hard-coded library, decision/risk relevance, ownership cap, task and test templates, stale references) | Removed. `planning/planner.py` now selects services, judges relevance and writes tasks/tests/questions through model tasks (`intelligence/tasks.py`); structural traversal and candidate gathering stay deterministic; every claim is guarded against the evidence registry; trust labels are derived from the cited evidence, never from the model. |
| A10-A13 conflicts, standard bypass, reuse, risk labels | Removed. `knowledge/judgments.py` asks the model; findings must quote text that literally exists in the source or they are discarded. Open blockers are now a structural fact (open ticket with a `blocks` link). |
| A14-A15 query handling and scoring | Removed (stop words, IDF filter, code-token regex, boosts, similarity floors). Replaced by model query analysis + rerank. Left: reciprocal-rank fusion with equal weights; exact lookup of tokens that are verbatim ticket keys / decision ids (pinned first). |
| A16 offline provider | Honest now: `has_llm=False`, `semantic_embeddings=False`. Search is lexical only, nothing is embedded, every judgment raises `LLMUnavailable` unless a cached judgment exists (replay). |
| A17 remember/override | Remember keyed by full-text hash (no 200-char key); override rule is free text. |
| C embed prefix `[:2000]`, snippet `[:240]`, planner `[:12]/[:8]/[:6]`, ownership cap 4, override `[:140]` | Removed: every chunk of every record is embedded; snippets are the matching chunk/fragment; the planner packs evidence by a configurable prompt budget and reports what was left out; ownership facts are all passed to the model to judge. |
| C importer limits | Issue/PR bodies are no longer truncated; every dropped file is counted by reason in `manifest.json` (`dropped`), and the API-driven limits (100 issues/PRs, 300 commits, 15 changelog versions) are recorded in `limits`. |

Remaining limits that are budgets, not relevance rules (all in `config.py`): `rerank_pool`, `evidence_budget_chars`,
`judge_batch_size`, chunk size 1800 chars, commits are not embedded.

**Not verifiable yet:** none of the model tasks has run against a real model (no provider credentials). They are
covered by guard/wiring tests with a scripted model only. Quality must be measured with `scripts/evaluate.py`
and `scripts/oss_probe.py` once `PROVIDER=gemini|vertex` is configured.

---

Everything below is rule-based logic that either *looks* like intelligence (judging relevance, intent, conflicts,
violations) or silently throws information away (truncation, caps). Line numbers refer to the audited commit.
Verdict: **LLM** = replace with a model-based judgment constrained by an evidence guard;
**KEEP** = deterministic extraction/standard algorithm, not pretending to be intelligence;
**FIX** = dumb limit, replace with a principled approach.

## A. Pseudo-intelligence

| # | Where | What it does | Verdict |
|---|---|---|---|
| 1 | planning/planner.py `_primary_services` | Chooses "affected service" by hand-set points: strong hit 1.0 / weak 0.5 / API path +3 / ticket project +2 / repo name regex +3; `MIN_ANCHOR=3`, `top*0.6` cut-off | **LLM** |
| 2 | planner.py `PATH_RE = /v\d+/...` | Finds API paths in text with a Northwind-specific pattern | **LLM** |
| 3 | planner.py `"platform-libs"` | Hard-coded library name excluded from primary services | **LLM** (catalog-driven) |
| 4 | planner.py decision selection | A decision "applies" if its scope intersects affected services, or scope=="org" | **LLM** |
| 5 | planner.py risk relevance | `any(s in f["summary"] for s in services)` substring test; ticket match `k in request` | **LLM** |
| 6 | planner.py ownership ranking | Sort key + `OWNERSHIP_CAP=4` | **LLM** (relevance ranking) |
| 7 | planner.py tasks | Fixed templates: "Implement the feature core in X for: <request>", "Assess whether…", "Verify and adapt the consumer" | **LLM** |
| 8 | planner.py tests | "Contract and regression tests for X" for every service | **LLM** |
| 9 | planner.py stale reference | Regex `ADR-\d+` inside code body = "follows superseded decision" | **LLM** judges; regex only nominates candidates |
| 10 | knowledge/build_graph.py conflicts | Two ADRs conflict iff same `Topic:` string and different `Scope:` string | **LLM** pairwise judge |
| 11 | build_graph.py standard bypass | Hard-coded `{"requests","urllib3","httpx","aiohttp"}` + literal `"ADR-004"` + `Override: ADR-N reason=` regex | **LLM** (PR text/diff vs candidate ADRs) |
| 12 | build_graph.py reuse | Method-name Jaccard >= 0.8 and >= 3 methods | **LLM** verifies; embeddings nominate |
| 13 | build_graph.py risk tickets | `"risk" in labels` | **LLM** |
| 14 | retrieval/search.py query handling | Stop-word list, IDF 25% filter (>=500 records), `CODE_TOKEN` regex, AND-then-OR | **LLM** query analysis |
| 15 | search.py scoring | `SUPERSEDED_FACTOR=0.3`, RRF weights identifier 5 / keyword 1 / vector 1 / graph 0.5, similarity floor 0.5/0.6 | **LLM** rerank + relevance filter (RRF itself: KEEP) |
| 16 | models/provider.py OfflineProvider | Feature-hash "embeddings" (not semantic) and `generate_json` that returns its input | **LLM** — offline mode must be labelled lexical-only, never "semantic" |
| 17 | api/service.py remember/override | `rule` must match `^ADR-\d+$`; summary = first 200 chars | **FIX** |

## B. Keep (deterministic parsing / statistics, not judgments)
AST import + HTTP-call + route-decorator extraction; CODEOWNERS parsing; ADR header parsing; relative-import
resolution; recursive-CTE impact traversal; RRF fusion; evidence-type -> label policy; commit-share statistics
(`>=10 commits and >=90%` bus-factor figure, `>90 days` idle) — these are computed numbers, but the thresholds
are arbitrary and should be configuration, with significance judged by the model.

## C. Truncation / word-count / silent drops

| Where | Limit | Effect | Verdict |
|---|---|---|---|
| retrieval/embed.py | `body[:2000]` chars | Only the first ~2,000 chars of any document are embedded; the rest is invisible to vector search | **FIX**: chunk, embed every chunk |
| retrieval/search.py `_hydrate` | snippet `[:240]` | Snippet is the file's first 240 chars, not the matching passage | **FIX**: query-relevant passage |
| search.py | fact title `[:80]`, seeds `[:10]`, graph seeds `[:5]`, code-token `LIMIT 6`, `per_signal=25` | Arbitrary candidate caps | **FIX**: configurable, justified |
| planner.py | `hits[:12]`, `strong_hits[:8]`, `strong_hits[:12]`, related_work `[:6]`, evidence label `[:100]` | Plan sees only a prefix of retrieved evidence | **FIX**: evidence packet by relevance budget |
| build_graph.py | override reason `[:140]` | Truncated explanation | **FIX** |
| api/service.py | remember summary `text[:200]` | Truncated fact summary | **FIX** (model-written summary) |
| ingestion/fixtures.py `_title` | first line / heading | Title heuristics | KEEP (parsing) |
| embed.py admission | commits never embedded | Cost rule, not relevance | **FIX**: embed PR-linked commits |
| scripts/build_oss_fixture.py | issue body `[:3000]`, PR body `[:4000]`, last 300 commits, newest 100 issues/PRs, 15 changelog versions, files >150KB (py) / >60KB (docs) dropped, `tests/` `examples/` `docs/_*` skipped, section body <120 chars dropped, slug `[:48]` | Real data silently discarded | **FIX**: paginate, chunk big files, report what was dropped |
