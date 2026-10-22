# Gitwhy

**Why your code is the way it is.** Gitwhy reads an organization's GitHub (code, commits, pull requests, review
discussion) and Jira (tickets and comments), builds a searchable memory and a knowledge graph from it, and answers
questions like *"what is our rule on cursor pagination, and who set it?"* with the exact words, the author, the date,
and a link to the original. **Every claim carries a citation, and a claim with no valid source is dropped before you see it.**

|  |  |
|---|---|
| Live (Google Cloud) | https://gitwhy-app-834360903376.us-central1.run.app |
| Live (VM fallback) | https://187-127-173-215.sslip.io |
| Test account | `demo@gitwhy.test` / `gitwhy-demo-2026` (read-only, sample data only) |
| Stack in one line | Python 3.12 + FastAPI · PostgreSQL 16 with pgvector · React 18 + Vite · Gemini / Vertex AI / Voyage AI · Cloud Run + Cloud SQL |

![An answer with its proof](docs/images/02-ask-answer.png)

## Contents
1. [The problem](#1-the-problem)
2. [What it does](#2-what-it-does)
3. [How it works, end to end](#3-how-it-works-end-to-end)
4. [The concepts, explained](#4-the-concepts-explained) — RAG · embeddings · vector search · full-text search · hybrid search and RRF · query analysis · reranking · knowledge graph · LLM judgments · guards · memory · identity
5. [Tech stack in detail](#5-tech-stack-in-detail)
6. [Data model](#6-data-model)
7. [Ingestion and onboarding](#7-ingestion-and-onboarding)
8. [API and MCP](#8-api-and-mcp)
9. [Security and privacy](#9-security-and-privacy)
10. [Deployment and CI/CD](#10-deployment-and-cicd)
11. [Run it locally](#11-run-it-locally)
12. [Testing and evaluation](#12-testing-and-evaluation)
13. [Honest limits](#13-honest-limits)
14. [Repository layout and contributing](#14-repository-layout-and-contributing)

---

## 1. The problem
The reasons behind code live in places nobody searches: a review thread from June, a ticket comment, a PR description,
a commit message. A reviewer says "never use offset pagination" in June; in September a new PR does exactly that and
nobody remembers the thread. When an engineer leaves, what only they knew leaves too. Chatbots over code can sound right
and be wrong, and a team cannot act on an answer with no source.

Gitwhy's answer is **retrieval you can audit**: a language model is used to *judge and write*, but only over evidence
the system itself retrieved, and everything it says is checked against that evidence by code, not by trust.

## 2. What it does

| Screen | What you get |
|---|---|
| **Ask** | A one-sentence bottom line, proof cards with the exact quote, who said it and when, and follow-up questions. Click a source to open the original thread, highlighted. |
| **Review a PR** | Draft review comments for a pull request that cite earlier decisions and reviewer guidance, down to the changed line when the diff shows it. Drafts stay local: nothing is posted to GitHub or Jira. |
| **Memory** | A standard someone set once in a thread, and whether later work *still holds*, was *contradicted*, or was *replaced*, as a short story with the evidence behind it. |
| **People** | A knowledge map computed from history, and a handover brief for a successor: areas only this person touched, open work, who to ask, first-week actions. |
| **Plan a feature** | A feature request turned into affected services, applicable decisions, risks and an ordered task list, each with sources. |
| **Change impact** | "If I change X, what else could break and which earlier decisions apply?" from graph dependencies. |
| **Trace a file** | Why a file looks the way it does: commits, PRs, discussion, tickets and decisions, in plain words. |
| **Sources / Results** | What was read and its limits; measured, rated and estimated figures kept apart. |

<table>
<tr><td><img src="docs/images/03-review-draft.png" alt="Pull request review"/></td><td><img src="docs/images/04-memory-story.png" alt="Memory"/></td></tr>
<tr><td><img src="docs/images/05-people-handover.png" alt="Handover brief"/></td><td><img src="docs/images/06b-plan-tasks.png" alt="Feature plan"/></td></tr>
</table>

## 3. How it works, end to end

```mermaid
flowchart LR
  subgraph Sources
    GH[GitHub: code, commits, PRs, diffs, review threads, issues]
    JI[Jira: tickets and comments]
  end
  GH --> SY[Sync: bounded, read-only, counted]
  JI --> SY
  SY --> SR[(source_records: raw evidence)]
  SR --> GB[Graph builder: Python AST + parsed metadata]
  GB --> KG[(entities + edges + facts: knowledge graph)]
  SR --> CH[Chunker] --> EM[Embedder] --> VX[(embeddings: pgvector)]
  SR --> FT[(Full-text index: tsvector + GIN)]
  Q[Question] --> QA[LLM: query analysis]
  QA --> HS[Hybrid search: identifiers + keywords + vectors]
  FT --> HS
  VX --> HS
  HS --> RR[LLM: rerank]
  RR --> GEN[LLM: write cited statements]
  KG --> GEN
  GEN --> GD{Guards}
  GD -->|valid ids, literal quotes| UI[Answer + proof]
  GD -->|anything else| DROP[Dropped, and counted]
```

1. **Read.** A connector pulls GitHub and Jira into `source_records` (raw, idempotent, hashed). Nothing is hidden: every cap and drop is counted in a manifest.
2. **Understand.** A deterministic builder derives a **knowledge graph** (services, modules, files, decisions, tickets, people, with typed, evidenced, time-aware edges) and curated **facts**. A model adds *judgments* (conflicts, compliance, reviewer guidance) that are checked before they are stored.
3. **Index.** Every record is cut into chunks, embedded once per model, and also full-text indexed.
4. **Retrieve.** A question is analysed by a model, searched three ways at once, fused with Reciprocal Rank Fusion, and reranked by a model.
5. **Answer.** A model writes short statements, each citing evidence ids. **Guards** keep only statements whose citations exist and whose quotes literally appear in the cited text. Labels such as *verified* or *inferred* come from the stored evidence, never from the model.

## 4. The concepts, explained

### 4.1 RAG (retrieval-augmented generation)
A language model on its own answers from what it memorised in training, which says nothing about *your* repositories. RAG
fixes that by **retrieving** relevant passages from your own data first and giving them to the model as the only material
it may use, so the answer is *grounded*.

Gitwhy's RAG differs from a plain "search, paste into a prompt, hope" pipeline in three ways:
- **Retrieval is hybrid and judged** (section 4.5 to 4.7), not a single vector lookup.
- **Generation is constrained to statements with citations** (4.10): the model returns structured JSON, each statement listing the ids of the evidence it relies on.
- **Verification is mechanical.** After generation, code checks every id and every quote. The model never gets to mark its own work as verified.

If nothing in the corpus backs an answer, Gitwhy says so ("No source backs this up") instead of guessing. Without any model configured it degrades honestly to keyword search over the raw query, and reports that.

### 4.2 Embeddings
An **embedding** turns a piece of text into a vector of numbers (here, 768 of them) so that texts with similar *meaning* land
near each other, even when they share no words ("don't page with offsets" ≈ "use opaque cursors").

- **Models.** Production uses **Vertex AI `text-embedding-005`** (768 dimensions), billed to the cloud project. Development can use **Voyage AI `voyage-4-large`** (1024 dimensions) or the Gemini embedding models. The model name is stored with every vector.
- **Task types.** Documents are embedded as `RETRIEVAL_DOCUMENT` and queries as `RETRIEVAL_QUERY`, the asymmetric pairing these models are trained for.
- **Normalisation.** Reduced-size vectors are scaled to unit length so cosine distance behaves.
- **Chunking.** Long texts are cut into spans of about 1,800 characters on natural boundaries (blank lines, then lines). The spans **tile the text with no gaps**, so a long document is embedded in full, not by its first N characters, and a tiny tail is folded into the previous chunk. Each chunk remembers its character range, so a hit can show the exact passage.
- **Each chunk once.** Vectors are keyed by *(record, chunk, model, content hash)*. Unchanged chunks are never re-embedded, and a reconciler reports every difference between what *should* be embedded and what is stored, per tier (decisions first, then facts, Jira issues, PRs, docs, files).
- **One model, one corpus slice.** Vectors from different models are never mixed. Queries filter on the model, so switching models means a new slice, not corrupted search.
- **Request hygiene (Vertex).** Requests are sized by characters to stay under the model's 20,000-token limit, a request that is still too big is halved and retried, one lone oversized text is shortened, and each text is capped at 8,000 characters (the model reads only the first 2,048 tokens). Quota answers are paced and never retried in a loop.

### 4.3 Vector similarity search (pgvector)
Vectors live in PostgreSQL through the **pgvector** extension (`vector` type). A query is embedded with the same model and the
nearest chunks are found with the cosine-distance operator (`embedding <=> query`), best chunk per record. At today's sizes
(a few thousand chunks per organization) exact search is fast and has perfect recall; the schema notes how to add a
per-model approximate index (HNSW) when an organization outgrows that.

### 4.4 Full-text (lexical) search
Meaning-based search misses exact strings such as `PAY-142`, `ADR-004` or a function name. So records and facts also carry a
generated `tsvector` column with a **GIN** index, queried with `websearch_to_tsquery` and ranked with `ts_rank_cd`.
Matching is *relaxed*: records containing every query word come first, then records containing any. The `pg_trgm` extension is enabled and entity names are trigram-indexed for fuzzy lookup; no current search path queries it yet, so it is groundwork, not a feature.

### 4.5 Hybrid search and Reciprocal Rank Fusion (RRF)
Three independent candidate lists are produced, all by plain database queries:
1. **Identifiers**: tokens in the question that are verbatim a ticket key, PR id or decision id. These are *pinned* to the top ("show me X" means X).
2. **Keywords**: full-text matches, from the original query and from the model's rewrites.
3. **Vectors**: nearest chunks.

They are merged with **Reciprocal Rank Fusion**: each list contributes `1 / (60 + rank)` to a record's score, and scores add.
A record that appears in several lists rises; no list needs a calibrated score, so there are **no hand-tuned boosts or
similarity thresholds** to maintain. Each hit keeps the rank it had in every list (`signals`) so a result can be explained.

### 4.6 Query analysis and HyDE-style semantic matching
Before searching, a model reads the question and returns structured JSON: the **intent**, 1 to 5 **search queries** (keywords,
synonyms, symbol names), the **identifiers** it names, and a short **hypothetical answer passage** (`answer_sketch`). The
vectors are searched with that passage rather than the raw question, in the spirit of *HyDE* (hypothetical document
embeddings): an answer-shaped text lands closer to real answers than a question does. The model is told not to answer and
not to invent identifiers.

### 4.7 Reranking
The fused pool (30 candidates by default) is graded by a model, 3 = directly answers or authoritative, 2 = strongly relevant,
1 = weak, 0 = not relevant, each with a one-line reason. Zero-graded results are dropped (and counted), pinned identifiers
survive, and the rest are ordered by grade, then fused score. Superseded decisions are graded by whether the question asks
about history or about what to do now. If the model is unavailable the fused order stands and the response says so.

### 4.8 The knowledge graph
Text search finds passages; a graph answers *structure* ("what depends on this service?", "who owns it?", "which decision
replaced which?"). Gitwhy keeps three layers in Postgres:

| Layer | Table | Holds |
|---|---|---|
| Raw evidence | `source_records` | PRs, issues, review comments, Jira tickets, ADRs, docs, files, with a content hash and the original payload |
| Canonical graph | `entities`, `edges` | Typed nodes and relationships |
| Curated knowledge | `facts` | Decisions, conventions, overrides, risks, lessons, ownership |

- **Entities:** `repo`, `service`, `module`, `file`, `package`, `endpoint`, `decision`, `ticket`, `pull_request`, `person`.
- **Edges:** `imports`, `depends_on`, `imports_external`, `calls_http`, `part_of`, `defined_in`, `owns`, `modifies`, `implements`, `applies_to`, `assigned_to`, `wrote`, `comments_on`, `supersedes`.
- **Every edge and fact records its provenance and how it is known:** `evidence_type` is `structural` (parsed from code), `explicit` (stated in a document or ticket) or `inferred`; `status` is `candidate`, `active`, `superseded` or `rejected`; plus a confidence and optional `valid_from` / `valid_until`. **Inferred claims are stored as candidates and are never shown as verified.**
- **Built deterministically** with Python's `ast` module plus parsed ADR, Jira and PR metadata, as idempotent upserts on natural keys, so rebuilds are safe.
- **Traversal** is a bounded **recursive CTE** over `depends_on` edges (no model involved), returning for every reachable service the shortest path and the evidence on each edge.
- **Supersession is first-class.** A replaced decision is kept as history but is never offered as a current rule.

This is *graph-augmented retrieval*: facts are searched alongside text, and the planner and impact views walk the graph for the
structural parts, using the model only for judgment on top.

### 4.9 LLM judgments: structured, cached, replayable
Every model call is a named **task** (query analysis, rerank, ask, plan, review, handover, conflicts, compliance, reuse, guidance
timeline, file explanation) with a JSON schema, temperature 0, and a prompt in one registry. Each judgment is **cached by
(organization, task, hash of prompt and payload, model)**, so repeating a question is free and a deployment can serve answers
with the model off ("replay"). Generation tries a chain (`gemini-3.8-flash`, then `3.7-flash`, then `3.5-flash-lite`), retries
transient errors, skips a model that no longer exists, and tries a recently failed model last (a circuit breaker). A second
API key covers quota exhaustion. Usage is metered (live calls versus replayed answers), and each answer records how many live model calls it took.

### 4.10 Guards: how hallucination is contained
The model proposes; code disposes. These rules hold for every feature:

1. **Citation guard.** Every statement must cite evidence ids that exist in the packet it was given. Otherwise it is dropped.
2. **Literal-quote guard.** A quote must occur word for word in the cited source. Whitespace, case, markdown emphasis and curly quotes are not content; the words are.
3. **Highlight guard.** A highlighted phrase is always a real stretch of the shown text.
4. **Labels derive from evidence.** *verified* / *inferred* / *replaced* come from stored `evidence_type` and `status`, never from model output.
5. **Superseded decisions are never rules.** A stale reference is reported, naming the replacement.
6. **Dropped statements are reported**, with a count, rather than silently vanishing.
7. **Drafts never leave the machine.** Nothing is posted to GitHub or Jira.

### 4.11 Reviewer memory and the timeline
A model reads review threads and extracts *guidance* ("never use offset pagination") with its **literal quote** (guarded). A
second judgment then places every later record relative to it: *restates, follows, conflicts, replaces, mentions*, and
decides whether it still holds, producing a short story with the evidence. Review drafts use only guidance dated **strictly
before the PR was merged**, and never from the PR's own thread, so a comment never claims "a reviewer already said this" about
something said afterwards.

### 4.12 Line-level pull-request review
Diffs are stored with the PR. A comment names a line only if the model's literal `diff_quote` is found in the diff, and a
decision or guidance comment must show the words in the PR that trigger it. A PR without a stored diff stays at file level.

### 4.13 Identity resolution, ownership and bus factor
One person appears as a git author name and as a GitHub login. They are merged only when the names are equal after ignoring
case, spaces and punctuation; looser matches are not merged. Bots (`[bot]`) are flagged. Commit shares, counts and last-activity
dates are **computed**, not model-guessed; the handover brief is a model judgment over that computed packet, with every item cited.

### 4.14 Code archaeology
For a file: the chain of commits that touched it, the PRs that changed it, the human discussion on them, the tickets they implement
and the decisions they mention, plus a style profile (docstrings, comments, function style) extracted with Python's parser and
tokenizer. No model is needed for the trail itself; a model only explains it in plain words, under the same guards.

### 4.15 MCP: the same knowledge for coding agents
Gitwhy exposes a **Model Context Protocol** server (JSON-RPC 2.0 over HTTP) with seven bounded tools: `search_context`,
`get_repo_overview`, `get_dependencies`, `get_decisions`, `analyze_feature_impact`, `create_feature_plan`,
`record_memory_candidate`. It is authenticated like the write endpoints. Every result carries source references, `evidence_type` and status so an IDE agent can show provenance.

### 4.16 Measurement without wishful thinking
The Results screen keeps three kinds of figure apart: **measured** (counted or timed), **rated** (a person's verdict on an answer),
and **estimate** (arithmetic on an assumption a viewer typed, never stored as a result). A comparison with manual search appears
only after at least five tasks were timed both ways.

![Change impact map](docs/images/09b-impact-map.png)

## 5. Tech stack in detail

| Layer | Technology | Why it is here |
|---|---|---|
| Language / API | **Python 3.12**, **FastAPI**, **Uvicorn**, **Pydantic / pydantic-settings** | Typed request models, settings from the environment, automatic OpenAPI. |
| Database | **PostgreSQL 16** (psycopg 3) | One store for records, graph, facts, vectors, jobs and accounts, with real transactions, and every row scoped to its organization. |
| Vector search | **pgvector 0.8** | Vectors beside the data they describe; no second system to keep in sync. |
| Lexical search | Postgres **full-text** (`tsvector`, GIN, `websearch_to_tsquery`, `ts_rank_cd`); **pg_trgm** enabled for name lookup | Exact identifiers and strings that embeddings miss. |
| Graph | Relational tables with a **recursive CTE** | Bounded, deterministic traversal without a separate graph database. |
| Code understanding | Python **`ast`** and **`tokenize`** | Structural imports, dependencies, docstrings; other languages are searchable text only. |
| Generation | **Gemini** via the `google-genai` SDK (Developer API keys, or Vertex AI with application default credentials) | Structured JSON output with a schema; swappable behind one `Provider` interface. |
| Embeddings | **Vertex AI `text-embedding-005`** (production, 768-d), **Voyage AI `voyage-4-large`** (development, 1024-d), Gemini embedding models | Swappable behind the same interface; each model is its own slice. |
| HTTP client | **httpx** | GitHub, Jira and Voyage calls. |
| Frontend | **React 18.3** and **Vite 5.4**, plain CSS design system | A light, calm UI: Inter and JetBrains Mono self-hosted as variable fonts, eased transitions, skeleton loading, honoring `prefers-reduced-motion`. |
| Auth | **scrypt** password hashes, **HMAC-SHA-256** signed bearer tokens (14-day expiry) | No external auth dependency; org selected with an `X-Org` header. |
| Tests | **pytest** (120 tests), **Playwright** browser flows | Guards, org isolation, sync, retrieval, API, metrics. |
| Containers | **Docker** (multi-stage: Node build, then Python runtime, non-root) | One image serves the UI and API. |
| Cloud | **Cloud Run**, **Cloud SQL for PostgreSQL**, **Cloud Build**, **Artifact Registry**, **Secret Manager**, **Cloud Storage** volume, **Vertex AI**, **Pub/Sub** budget alerts | Managed hosting; see section 10. |
| CI/CD | **GitHub Actions** (definitions in `deploy/github-workflows/`), **Dependabot** | Tests, build, secret scan, Docker build, deploy. |
| VM fallback | **Caddy** (automatic HTTPS) and **systemd** | A second live copy while the cloud one is the primary. |

## 6. Data model

| Table | Purpose |
|---|---|
| `organizations`, `repositories` | Tenancy and connected repos. |
| `source_records` | Raw evidence: `github_pr`, `github_comment`, `github_commit`, `jira_issue`, `adr`, `doc`, `file`; generated `search_tsv`. Unique on *(org, type, id)*; `content_hash` detects change. |
| `entities`, `edges` | The graph; edges carry `evidence_type`, `status`, `confidence`, validity window and the source record. |
| `facts` | Curated knowledge with `superseded_by`, scope (`org`/`repo`/`team`) and a generated `search_tsv`. |
| `embeddings` | One row per *(owner, chunk, model)* with character range, content hash and the vector. |
| `llm_judgments` | The judgment cache that makes answers replayable. |
| `embed_usage`, `embed_spend`, `quota_state` | Embedding budgets, spend caps and quota back-off. |
| `users`, `org_members`, `org_connections`, `sync_jobs` | Accounts, membership, connector settings, sync progress. |
| `usage_events`, `answer_feedback`, `timed_tasks` | The numbers behind the Results screen. |
| `ingestion_runs`, `ingestion_cursors`, `feature_plans` | Run records, incremental cursors, saved plans. |

Migrations are plain SQL in `migrations/`, applied in order and recorded in `schema_migrations`.

## 7. Ingestion and onboarding
- **GitHub (read-only):** shallow clone for code, docs and history; pull requests with changed files and **stored diffs**; issues; and the *human discussion* (review comments, PR conversation, review summaries, issue comments). The token reaches `git` through a temporary `GIT_ASKPASS` helper, never on a command line.
- **Jira Cloud:** issues and comments of a project, incremental by the newest `updated` timestamp; Atlassian Document Format (rich-text JSON) is flattened to text structurally.
- **Bounded and counted:** limits on PRs, issues, threads and commits are settings (`SYNC_MAX_*`); every drop is recorded in the manifest, never silent.
- **Onboarding:** sign up, name the organization, connect GitHub (choose repositories), optionally Jira, then watch a live status page (reading GitHub, reading Jira, connecting the dots, building the search index). A failed stage is recorded with its reason and the job stops there, with no hidden retries.
- **Tokens** are stored outside the database: a private directory locally, a private Cloud Storage bucket on Cloud Run.

## 8. API and MCP
All routes live under `/api`. Reads need a signed-in session (or run open in single-org local mode); writes need an authenticated user.

| Area | Endpoints |
|---|---|
| Accounts | `POST /auth/signup`, `POST /auth/login`, `GET /auth/me`, `POST /orgs`, `PUT /orgs/{slug}/connections`, `POST /orgs/{slug}/sync`, `GET /orgs/{slug}/sync`, `POST /connections/github/test`, `POST /connections/jira/test` |
| Ask and search | `POST /ask`, `GET /search`, `GET /tags`, `GET /starters`, `GET /provenance/{record_id}` |
| Review and memory | `GET /prs`, `POST /prs/{repo}/{number}/review`, `GET /memory/guidance`, `POST /memory/guidance/{id}/timeline`, `POST /memory/remember`, `POST /memory/override` |
| People and files | `GET /people`, `GET /people/{login}`, `POST /people/{login}/handover`, `GET /files`, `GET /archaeology`, `POST /archaeology/explain` |
| Planning | `POST /impact`, `POST /plans`, `GET /plans`, `GET /plans/{id}` |
| Knowledge and graph | `GET /graph`, `GET /entities/{id}`, `GET /knowledge`, `POST /knowledge/{id}/status` |
| Measurement | `GET /results`, `POST /timed-tasks`, `POST /feedback` |
| Health | `GET /health`, `GET /health/db`, `GET /meta` |
| MCP | `POST /mcp` (JSON-RPC 2.0, tools capability) |

## 9. Security and privacy
- **Isolation:** every row carries an `organization_id`; requests are scoped to the caller's organization and tests assert the isolation.
- **Passwords** are scrypt-hashed; sessions are HMAC-signed tokens with an expiry.
- **Least privilege on sources:** connectors are read-only; use read-only tokens.
- **Drafts are local:** review comments and plans are never posted anywhere.
- **Secrets** live in Secret Manager (cloud) or `~/.config/gitwhy` with mode 600 (local); `.env` files and key files are git-ignored, and CI runs a secret scan.
- **Customer data is sent to the model providers** (Google, and Voyage in development) to be read and embedded. Free-tier terms may allow the provider to use that data to improve its products, so use paid terms for sensitive code.

## 10. Deployment and CI/CD

```mermaid
flowchart LR
  U[Browser / IDE agent] --> CR[Cloud Run: FastAPI + built React UI]
  CR --> SQL[(Cloud SQL: PostgreSQL 16 + pgvector)]
  CR --> SM[Secret Manager]
  CR --> GCS[(Cloud Storage: org tokens)]
  CR --> VX[Vertex AI: embeddings]
  CR --> GM[Gemini API: generation]
  GA[GitHub Actions] --> CB[Cloud Build] --> AR[Artifact Registry] --> CR
```

- **Primary:** Cloud Run service `gitwhy-app` (1 vCPU, 1 GiB, always-on CPU and one minimum instance because sync runs in a background thread) with Cloud SQL attached over the Cloud SQL connector, secrets from Secret Manager, and a Cloud Storage volume mounted at `/secrets` for per-organization tokens.
- **Build and deploy:** `deploy/deploy.sh` builds with Cloud Build and deploys the image; `deploy/github-workflows/ci.yml` runs the backend tests (against Postgres with pgvector), the frontend build, a secret scan and a Docker build, and `deploy.yml` deploys after CI passes. They live under `deploy/` until a token with GitHub's `workflow` scope can move them into `.github/workflows/`.
- **Fallback:** the same code runs on a VM behind Caddy; redeploy with `sudo ops/deploy_vm.sh` after `npm run build`.
- **Budget:** a Cloud Billing budget publishes to Pub/Sub, and a small watcher (`ops/budget_watch.py`) sends a message at every 5% of the credit.
- **Change process:** `main` is protected; every change goes through a pull request.

## 11. Run it locally
```bash
# 1. PostgreSQL 16 with the pgvector and pg_trgm extensions; then point the app at it
export DATABASE_URL=postgresql://USER:PASSWORD@127.0.0.1:5432/gitwhy

# 2. Backend: migrate, ingest the synthetic "Northwind Labs" sample, build the graph
cd backend && python -m venv .venv && .venv/bin/pip install fastapi "uvicorn[standard]" "psycopg[binary]" pydantic-settings httpx google-genai pytest
.venv/bin/python -m app.seed
.venv/bin/uvicorn app.main:app --port 8000

# 3. Frontend (served by the backend from frontend/dist)
cd ../frontend && npm ci && npm run build
```
Open http://127.0.0.1:8000. With `AUTH_REQUIRED=1` the app uses accounts and onboarding; without it, it serves the single `ORG_SLUG` with no login.

**Model providers.** `PROVIDER=offline` (default) runs with no model: lexical search only, and anything needing a judgment says so.
`PROVIDER=gemini` + `GEMINI_API_KEY` uses the Gemini Developer API; `PROVIDER=vertex` + `GCP_PROJECT` uses Vertex AI with application default
credentials. Embeddings are chosen separately: `EMBED_PROVIDER=vertex` (production), `voyage` + `VOYAGE_API_KEY` (development), or `gemini`.
Build an organization's search index with `ORG_SLUG=<slug> python -m app.retrieval.embed`.

The product name lives in one place, `product.json`, which drives the UI brand, page title, API title, MCP server name and `/api/meta`.

## 12. Testing and evaluation
- `cd backend && python -m pytest -q` runs **120 tests** against a real Postgres (`TEST_DATABASE_URL`): guards, organization isolation, sync (with only the network stubbed), retrieval, ranking, review, people, change impact, metrics, the Vertex embedder.
- `node frontend/e2e/flows.mjs <out-dir> <base-url>` drives every screen in a real browser and fails on console errors or HTTP errors.
- `python3 scripts/evaluate.py` scores retrieval and planning on the synthetic organization, where the right answers are planted; `docs/eval-report.md` shows the latest report. `scripts/oss_probe.py` and `docs/oss-*-report.md` cover real open-source repositories (Flask, Werkzeug, Jinja, Click, MarkupSafe, ItsDangerous, Requests, urllib3).
- Evaluation numbers are reported as **counts, not percentages**, and a held-out set was frozen before any live output existed.

## 13. Honest limits
- **Python only** is understood structurally; other languages are searchable text.
- **Dependencies are only what was recorded** (imports, manifests, tickets), so change impact is thin on single-service repositories.
- **The generation model on the free tier is small**; quality with a stronger model has not been measured, and the held-out evaluation has not been run.
- **A review names a line only where the stored diff shows it.**
- **Time saved is never claimed**; see 4.16.
- **Exact vector search** is used today; add an approximate index for very large organizations.
- **Customer data goes to model providers** (section 9).

## 14. Repository layout and contributing
```
backend/app/
  ingestion/  sync/        connectors (GitHub, Jira) and the background sync job
  knowledge/  graph/       graph builder, model judgments, bounded traversal
  retrieval/               chunking, embedding, hybrid search, RRF, rerank
  ask/  memory/  review/   cited answers, reviewer memory, PR review drafts
  people/  archaeology/    knowledge map, handover, file trails
  planning/  impact/       feature planner, change impact
  intelligence/            task prompts and schemas, the judgment cache, guards
  models/                  provider interface: Gemini / Vertex, Voyage, offline
  api/  mcp/  metrics/     HTTP routes, MCP server, results numbers
frontend/                  React + Vite app (src/pages = one file per screen)
migrations/                plain SQL schema, in order
fixtures/  scripts/  eval/ synthetic organization, scorers, evaluation sets
deploy/  ops/              cloud deploy, CI/CD definitions, VM scripts
docs/                      plan, product, decisions, reports
```
Design decisions and incidents are logged in `DECISIONS.md`; more detail is in `docs/PLAN.md`, `docs/decisions.md`,
`docs/heuristics-audit.md`, `docs/operations.md` and `docs/demo-script.md`.

**Contributing.** `main` is protected: branch, open a pull request, and have someone else review and merge it. Keep secrets out of the
repository (the secret scan will fail the build), and add a test for any change to a guard.
