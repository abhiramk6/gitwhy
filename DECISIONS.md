# Decisions log

One line per non-trivial decision: what, and why. Newest first. Owner-pending items are listed once at the top and
repeated (not re-sent) in each hourly update until answered.

## Waiting on owner
_none blocking._ One-time ask at the next milestone (dev-only partial B): review of the OSS dev lists and
`excluded_subjects`, which are **agent-confirmed, not human-reviewed**.

## Log (UTC, server clock)
- 2026-10-15 19:55 — Dev scoring wired to eval/oss_dev_lists.json (required / excluded / unlisted-review; excluded_subjects on dev only). Lists are **agent-confirmed, not human-reviewed**, as delegated by the owner; reports say so; one review request at the next milestone. Held-out scoring is NOT wired (needs frozen prompts + complete embeddings).
- 2026-10-15 19:45 — PR review drafting added (backend/app/review): local files only (reviews/, gitignored), no network code, no post path (test-enforced); same evidence guard as the planner plus quote check for violations, superseded decisions never reported as violations, dependency-impact must cite a consumer edge. Developed and checked on Northwind dev PRs only; never against held-out cases.
- 2026-10-15 19:40 — Hourly status runs as its own tmux process (lore:hourly), independent of the agent session; does not survive a host reboot.
- 2026-10-15 19:38 — Search degrades to lexical when the query-embedding quota is exhausted, instead of failing.
- 2026-10-15 19:36 — Plan A accepted by owner: embed order ADR, facts, issues, PRs, docs, code; 900 index items/day, 100/day query reserve; one pass per quota day, no retry loops. Reason: free-tier cap is 1,000 items/day/model (counted per text).
- 2026-10-15 19:36 — Ledger counts only items the API accepted; failed requests are not confirmable as free, so a 100/day reserve is kept. If a pass hits the cap earlier than the ledger predicts: stop for the day, log here, report in the next update.
- 2026-10-15 19:36 — Schedule dates are stated with the server clock (Thu 2026-10-15 19:34 UTC) and as hours from now; the API's RetryInfo (16,527 s) places the next reset at about 00:05 UTC on 2026-10-16.
- 2026-10-15 19:30 — OSS demo corpus uses `gemini-embedding-001` only (owner decision); deployment default stays `gemini-embedding-2`. Reports state the model per corpus and that OSS results are not predictive of `-2` quality.
- 2026-10-15 19:25 — Stopped retrying the embedding job after a hard daily cap (owner rule: >1 day ETA means stop and ask).
- 2026-10-15 19:20 — Request sizing for embeddings (30k chars, 24k tokens/min): one oversized request is rejected deterministically, so size is bounded up front instead of retried.
- 2026-10-15 19:18 — Held-out OSS set frozen and committed (sha256 f69d0f14…) before any live OSS plan existed; one run per case; H6 manual review only.
- 2026-10-15 19:12 — Reports print counts per set, not percentages; skipped checks are not passes and make runs exit non-zero.
- 2026-10-15 19:05 — Allowlists use three buckets (required / excluded / unlisted-review); unlisted items are adjudicated on dev only. ADR-101 dropped from the markupsafe allowed list (applies to version changes of a Pallets package).
- 2026-10-15 18:30 — Planner prompt tightened in general terms (review every active decision, stale citations, reuse candidates) after 3 live misses; tuned on Northwind dev only, never on OSS held-out.
