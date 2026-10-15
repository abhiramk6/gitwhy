# LORE Intelligence — Cleaned Plan (v2)

Evidence-backed feature planning on top of an organizational knowledge graph.
Built on GCP (Cloud Run + Cloud SQL/pgvector + Vertex AI Gemini). Demo data is a synthetic org.

**One-line pitch:** ask "how do I build X?" and get a plan that finds the real dependencies,
the governing decision, the risk and the prior implementation a generic assistant would miss —
with every claim linked to evidence and labeled verified / inferred / proposed.

---

## 1. Decisions (locked unless you object)

| # | Decision | Choice | Why |
|---|----------|--------|-----|
| D1 | LORE reuse | **Concepts only; no code copy.** Audit repo for license + what actually works, record in `docs/decisions.md` | Archived, TypeScript, tied to one model vendor; our stack is Python + Gemini |
| D2 | Backend | Python / FastAPI **modular monolith**; MCP server is a route in the same service | One deployable, fastest to ship |
| D3 | Model | Gemini via Vertex AI behind a thin `models/` adapter; embeddings via Vertex | Required by GCP target |
| D4 | Database | Cloud SQL Postgres + pgvector; graph = `entities` + `edges` tables, bounded recursive CTE traversal | No graph DB until measured need |
| D5 | Runtime | Cloud Run service (API+MCP), Cloud Run service (frontend), Cloud Run Job (ingest) | No GKE |
| D6 | Demo data | **Synthetic org fixtures are primary**; live GitHub/Jira connectors are secondary, fixture fallback always on | Demo must be deterministic |
| D7 | Frontend | React + Vite, 4 core screens (see §4) | Cut from 6 screens |
| D8 | Auth | Single shared demo login (app-level), no Identity Platform | Not needed for demo |

## 2. Cut from the original plan

Removed or deferred to keep 72h realistic:

- **Pub/Sub, BigQuery, GKE, Identity Platform, IAP, Neo4j** — not in scope.
- **Cloud Trace / Error Reporting** — Cloud Logging only.
- **Separate Integrations/Onboarding screen** — folded into a status panel on the Overview.
- **Multi-agent framing** — one orchestrator, deterministic retrieval/graph, Gemini only for extraction + synthesis.
- **GitHub/Jira webhooks, 30-min Cloud Scheduler** — one scheduled incremental-sync job is enough.
- **tree-sitter for many languages** — Python (+ maybe TypeScript) only, `ast`-based first.
- **Cost estimates / hour-by-hour 6-phase table** — replaced by §5.

## 3. Minimal GCP footprint (budget-conscious, $300 free-trial credit)

| Service | Use | Cost note |
|---------|-----|-----------|
| Cloud Run (3 workloads, min instances 0, max 2) | API/MCP, frontend, ingest job | ~free at demo traffic |
| Cloud SQL Postgres (smallest shared-core, 10 GB, single zone, no HA) | system of record + pgvector | **Largest recurring cost — stop/delete when idle** |
| Vertex AI (Gemini Flash + embeddings) | extraction, planning, embeddings | Token-budget every call; cache embeddings |
| Secret Manager, Artifact Registry, Cloud Build, Cloud Logging, Cloud Scheduler | plumbing | pennies |
| Cloud Storage (1 bucket) | fixtures + snapshots | pennies |

**Budget guardrails**
- Free-trial accounts are **not billed** past the credit unless you click "Upgrade" — do *not* upgrade.
- Budget alerts at 25 / 50 / 75 / 90% of $300 (alerts notify, they don't cap — hence the watcher below).
- Hourly cost/health watcher posts to Telegram; at 80% of credit, all non-essential resources are stopped.
- Per-workflow Gemini token caps; embeddings computed once per content hash.

## 4. Product scope

**Screens:** (1) Overview + ingestion status · (2) Graph explorer with evidence panel ·
(3) Feature Planner (the hero) · (4) Knowledge Inspector (facts, provenance, conflicts, `/remember`, `/override`).
Change-intelligence signals (single-owner, dormant-owner, override-without-record) appear as alert cards on the Overview.

**Knowledge admission rule:** raw evidence is always kept; only validated, sourced, durable facts become `active`.
Every fact carries: org, subject/predicate/object, source (type+id+url), observed_at, valid_from/until,
confidence, evidence_type (`structural|explicit|inferred`), status (`candidate|active|superseded|rejected`).
LLM inference is never shown as verified.

**Retrieval:** Postgres FTS + pgvector + metadata filters + bounded graph expansion, fused with reciprocal-rank fusion.

**MCP tools (7, down from 12):** `search_context`, `get_repo_overview`, `get_dependencies`,
`get_decisions`, `analyze_feature_impact`, `create_feature_plan`, `record_memory_candidate`.

## 5. Build order (checkpointed, each ends with a passing test or working demo flow)

| Stage | Output | Exit gate |
|-------|--------|-----------|
| 0. Foundation | Repo, schema + migrations, FastAPI skeleton, local Postgres+pgvector, decisions log | `/health` + migration test pass locally |
| 1. Synthetic org | 5 small repos, ~40 Jira tickets, ~60 PRs, 6 ADRs, 8 seeded scenarios; deterministic validator | Validator green; counts match manifest |
| 2. Ingestion | Idempotent fixture ingest + cursors; GitHub/Jira adapters behind same interface | Re-run adds 0 rows |
| 3. Structure + graph | AST parse → symbols/imports/endpoints; entity/edge/fact tables; impact traversal | Known 3-hop path returned with evidence per edge |
| 4. Retrieval + planner | Hybrid search, context budget, Gemini structured plan output, eval set | Seeded feature surfaces correct services, ADR, risk |
| 5. Dashboard + MCP | 4 screens on real APIs; MCP route | Full demo clickable; MCP client calls planner |
| 6. GCP deploy | Cloud SQL, Cloud Run x2, Job, Scheduler, secrets | Clean redeploy passes smoke test |
| 7. Hardening | Fallback/demo mode, rehearsal script, docs | Demo repeatable twice in a row |

Cloud deploy (6) is intentionally late: Stages 0–5 run and are tested locally so cloud credit is not burned
while code is still changing. Stage 0 still validates Cloud SQL + pgvector early with a short-lived instance.

## 6. Seeded demo scenarios (all must be machine-verifiable)

1. Critical module, one dominant contributor.
2. Key owner inactive >90 days.
3. Conflicting conventions in two repos.
4. PR bypassing a standard (one with override record, one without).
5. Feature request touching several services via shared API.
6. Prior implementation that should be reused.
7. Superseded ADR still referenced by old code.
8. Migration/dependency risk that changes the plan.

## 7. Acceptance criteria

No-duplicate re-ingest · every active fact has a source · known dependency path correct ·
relevant facts rank above distractors in the eval set · duplicates merged / stale superseded / conflicts surfaced ·
plan names seeded components, constraints, risks · claims labeled verified/inferred/proposed ·
no secrets in logs or client bundle · UI has loading/empty/error states · clean-redeploy demo works.

## 8. Operating protocol (human ↔ agent)

- **Telegram** is the single channel: blockers, approvals, hourly cost/health digest, milestone pings, limit warnings.
- Agent never takes irreversible/outward actions without approval: creating billable resources beyond the
  agreed list, pushing to public repos, inviting people, upgrading the GCP account.
- Account creation that needs phone/CAPTCHA/card is done **by the owner**; agent supplies the exact steps.
- Private repo only; secrets live in `~/.config/lore/` (mode 600) and Secret Manager — never in git.
- On usage-limit hit: agent writes `ops/STATE.md` (what's done, what's next), pings Telegram, waits, resumes.
