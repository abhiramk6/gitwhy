# Agent state (resume point)

Updated: 2026-10-15

## Done
- Plan cleaned (docs/PLAN.md); decisions D1-D10 logged (docs/decisions.md) incl. LORE audit.
- Toolchain installed: Postgres 16 + pgvector 0.6.0, Node 18, gcloud, gh, tmux, Python venv (backend/.venv).
- Stage 0 foundation: migrations/001_init.sql, FastAPI /health + /health/db, 5 passing tests (idempotent migrations).
- Stage 1 synthetic org: scripts/generate_synthetic_org.py + validate_synthetic_org.py; fixtures/northwind committed;
  5 repos, 42 Jira, 55 PRs, 136 commits, 8 ADRs; all 8 scenarios validated from data; 10 tests pass.
- Stage 2 ingestion: app/ingestion (idempotent, cursors, runs); rerun = 0 new.
- Stage 3 graph: app/knowledge/build_graph.py (entities/edges/facts w/ provenance + evidence_type, stale-fact retirement),
  app/graph/impact.py (bounded recursive-CTE traversal). 21 tests pass. PR bypass uses diff-derived `adds_imports`.
- Telegram: group "Cb" paired; tmux session `lore` (agent + bridge + shell).

## Blocked on owner (via Telegram)
- Rotate bot token; GitHub login (private repo); GCP free-trial + gcloud login; collaborator usernames.

- Stage 4 (commit d079151): provider adapter (offline deterministic + Vertex), embeddings w/ admission,
  hybrid retrieval (FTS+pgvector+graph, RRF), evidence-bound planner. 31 tests pass total (2026-10-15 09:25 UTC).

- Stage 5 (commit a7277b0 + UI): REST API, token-gated writes, /remember /override, curation, MCP route (7 tools),
  React UI (4 screens) served by backend. 43 backend tests + 14-step headless-browser e2e pass (no console errors,
  no overflow at 390px). Dev DB cleaned of e2e artifacts.

## Next
- Prepare offline: Dockerfile, Cloud Build/Run configs, eval script, cost watcher (Stage 6/7 prep).
- Stage 6: GCP deploy (blocked on owner: GCP trial + gcloud login + approval for billable resources).
- Stage 7: hardening, demo script, fallback mode.

## Notes
- Uncommitted but deliberate (bridge hardening by earlier process): ops/notify.sh, ops/telegram_bridge.sh.
- Bridge targets live agent pane lore:shell.0; lore:agent is stuck at folder-trust prompt (harmless, idle).
- Incident 2026-10-15: a resumed session with stale context overwrote Stage 1 scripts; restored from git (HEAD).
  Before editing, check `git log -5` and `git status` to confirm what already exists.

## Local run
- `set -a; source ~/.config/lore/db.env; set +a; cd backend; .venv/bin/python -m pytest -q`
- `.venv/bin/python -m app.db` (migrate), `.venv/bin/uvicorn app.main:app`

## Channel
- Telegram is the primary channel (bot @<project bot>, owner chat paired 2026-10-15).
- Replies arrive via ops/poll_telegram.sh under Monitor (30 min max per arm; re-arm on expiry).
- Only messages from the paired chat id are acted on.
- Checklist sent to Telegram; waiting on: new bot token, GitHub, GCP trial, gcloud login.
- Group "Cb" paired 2026-10-15 on explicit owner confirmation typed in terminal. Updates go to the group
  (ops/notify.sh); NOTIFY_DM=1 forces DM. Instructions/approvals accepted ONLY from the owner's user id.
- Approvals for billable/outward actions must still be typed in the terminal session (Telegram events are
  delivered as background events, not user input).

## Persistence (tmux)
- tmux session `lore`: window `agent` (agent --resume b5139bff-…, cwd /root), window `bridge`
  (ops/telegram_bridge.sh — owner-only Telegram -> agent pane, prefixed "[Telegram from owner]"),
  window `shell`.
- Attach: `tmux attach -t lore`; detach: Ctrl-b d. First attach needs "Yes, I trust this folder" once.
- Telegram poller Monitor is NOT used with the bridge (two getUpdates readers conflict).
