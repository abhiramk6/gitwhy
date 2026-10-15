# Architecture Decision Log

Format: ID · date · status · decision · why. Reversals add a new entry; old entries are never deleted.

## D1 — LORE-OSS reuse: concepts only, no code copy  (2026-10-15, accepted)
Shallow audit of `re-cinq/lore-oss` (shallow clone, HEAD "Sync with upstream lore — 2026-04-06"):
- **License:** Apache-2.0 → code reuse is legally possible with attribution + NOTICE; not needed now.
- **Stack:** TypeScript MCP server (`mcp-server/src`), `pg`, `@modelcontextprotocol/sdk`, GCP exporters,
  Vertex AI used in `memory-search.ts`/`ingest.ts`/`db.ts`; A single hosted model vendor is used in `index.ts`,
  `facts.ts`, `context-assembly.ts`, `routes.ts` (fact extraction path is vendor-bound).
- **Tests:** vitest suites exist (`pipeline`, `context-assembly`, `vertex-ai`, …). **Not executed by us** —
  not verified to pass.
- **Not assumed:** that any spec under `specs/` is fully implemented.

| LORE component | Verdict | Notes |
|---|---|---|
| `memory-search.ts` (hybrid + graph-augmented) | Concept reuse | Re-implement in Python over our schema |
| `graph.ts` (live knowledge graph) | Concept reuse | Our edges carry evidence_type/status/validity |
| `context-assembly.ts` (budgeted context) | Concept reuse | Add per-task token budget + relevance threshold |
| `chunker.ts` | Possible code reference | Port only if needed; Apache-2.0 attribution |
| `pipeline.ts` / `tasks.ts` | Not reused | Cloud Run Jobs replace it |
| `repo-onboard.ts` | Concept reuse | Onboarding flow mirrored by ingest status panel |
| `index.ts` (MCP server) | Replaced | MCP implemented as a FastAPI route (D2) |
| Vendor-bound `facts.ts` extraction | Replaced | Gemini via provider adapter (D3) |

Revisit if time permits a TS sidecar; default is **no**: LORE is archived, we cannot rely on upstream fixes.

## D2 — Backend: Python/FastAPI modular monolith, MCP as a route  (2026-10-15, accepted)
One deployable. Split only on a measured operational need.

## D3 — Models: Gemini + embeddings via Vertex AI behind `app/models/` adapter  (2026-10-15, accepted)
Embedding dim fixed at **768** (`text-embedding-005`) in `embeddings.embedding vector(768)`.
Changing the model/dimension requires a new migration and re-embedding.

## D4 — Database: Postgres + pgvector; graph as entities/edges tables  (2026-10-15, accepted)
Bounded recursive-CTE traversal. No separate graph DB until measured need.
Local dev: Postgres 16 + pgvector 0.6.0. Cloud: Cloud SQL (version/extension support to be confirmed in Stage 6).
Migrations avoid superuser-only operations other than `CREATE EXTENSION IF NOT EXISTS`.

## D5 — Runtime: one Cloud Run service (API + MCP + built SPA) + one Cloud Run Job; no GKE  (2026-10-15, amended)
Amended: the FastAPI service serves the built React app, so there is no separate frontend service (less cost, one deploy).

## D6 — Demo data: synthetic org fixtures are primary; live connectors secondary  (2026-10-15, accepted)

## D7 — UI: 4 screens (Overview, Graph, Feature Planner, Knowledge Inspector)  (2026-10-15, accepted by owner)

## D8 — Auth: one shared demo login at app level; no Identity Platform/IAP  (2026-10-15, accepted)

## D9 — Budget: develop locally; deploy late; hard stop at 80% of $300 credit  (2026-10-15, accepted by owner)
Free-trial account must not be upgraded. Hourly cost watcher posts to Telegram. Billable creation needs owner approval.

## D10 — Control channel: Telegram group "Cb"; owner-user-id-only instructions  (2026-10-15, accepted by owner)
tmux session `lore` keeps the agent alive; `ops/telegram_bridge.sh` forwards owner messages. Bot token must be rotated
(old token exposed in an interactive session).
