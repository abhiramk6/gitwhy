# LORE Intelligence

Evidence-backed feature planning on an organizational knowledge graph. Synthetic demo organization
("Northwind Labs", 5 repos, 42 tickets, 55 PRs, 8 ADR files) — no real people or customer data.

Ask "how do I build X?" and get: affected services (including ones the request never names), governing
decisions (never superseded ones), risks (ownership, migrations, stale references), reuse candidates, and an
ordered task plan — every claim labelled **verified / inferred / proposed** and linked to its evidence.

## Run locally
```bash
set -a; source ~/.config/lore/db.env; set +a      # DATABASE_URL (Postgres 16 + pgvector)
cd backend && .venv/bin/python -m app.seed         # migrate + ingest + graph + embeddings (idempotent)
.venv/bin/uvicorn app.main:app --port 8000         # UI + API + MCP at http://127.0.0.1:8000
cd ../frontend && npm ci && npm run build          # (UI is served from frontend/dist)
```
Tests: `cd backend && .venv/bin/python -m pytest -q` · Fixture check: `python3 scripts/validate_synthetic_org.py`
· Eval: `python3 scripts/evaluate.py` · Browser flows: `node frontend/e2e/flows.mjs <out-dir>` (needs playwright-core).

## Layout
`backend/app/{ingestion,knowledge,graph,retrieval,planning,models,api,mcp}` · `frontend/` (React+Vite) ·
`migrations/` · `fixtures/northwind/` · `scripts/` · `eval/` · `deploy/` · `ops/` · `docs/`

## Safety model
Writes (`/api/plans`, `/api/memory/*`, curation, `/mcp`) require `X-Demo-Token` (or Bearer). With no token
configured they are accepted only when `ENVIRONMENT=local`. Secrets live in `~/.config/lore` and Secret Manager.
LLM output is accepted only if every evidence id exists in the plan's evidence registry.

See `docs/PLAN.md`, `docs/decisions.md`, `docs/demo-script.md`, `docs/eval-report.md`, `docs/operations.md`.

## Model provider
`PROVIDER=offline` (default) runs with no model: lexical search only; planning, conflict/compliance/reuse judgments
return `llm_required` / are skipped. Set `PROVIDER=gemini` with `GEMINI_API_KEY` (Gemini Developer API), or
`PROVIDER=vertex` with `GCP_PROJECT` (application default credentials). Judgments are cached in `llm_judgments`
and replayed without a model. See `docs/heuristics-audit.md`.

Embeddings can come from a different provider than generation: `EMBED_PROVIDER=voyage` + `VOYAGE_API_KEY` (model
`voyage-4-large`, 1024-dim; free-account limits 3 RPM / ~10K TPM are paced, never retried). Each embedding model is its
own corpus slice: vectors from different models are never mixed, and reports name the model. `ops/embed_voyage.sh` runs
one pass.
