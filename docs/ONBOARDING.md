# Onboarding an organization (current state, honestly)

**Status: assisted onboarding by script works for a Python-centric org; there is no self-serve flow yet.**

## What exists
| Piece | State |
|---|---|
| Jira Cloud | Live connector, one project per run (`python -m app.ingestion.jira`; env JIRA_SITE, JIRA_EMAIL, JIRA_TOKEN, JIRA_PROJECT, JIRA_ORG_SLUG). Incremental by `updated`. Issues, comments, links. |
| GitHub | No live connector. Data comes from a fixture folder built by `scripts/build_oss_fixture.py` (repos hard-coded, local clones, public API, newest 100 PRs/issues + 300 commits per repo) and `scripts/fetch_pr_discussion.py` (review comments, PR conversation, review summaries, issue comments; token from GH_TOKEN). Then `python -m app.seed --path <fixture>`. |
| Pipeline | ingest -> knowledge graph (model judgments) -> embeddings (`python -m app.retrieval.embed`) -> reviewer guidance. Idempotent, resumable. |
| Tenancy | One organization per running server (`ORG_SLUG`); several orgs can live in one database. No users, roles or per-org secrets. |
| Code understanding | Python only for imports/calls/routes/style; other languages are ingested and searchable as text. |

## Manual procedure for a new org (today)
1. Provide: a read-only GitHub token (fine-grained: contents, pull requests, issues, metadata) and the repo list; Jira site, email, read API token, project keys.
2. Clone the repos; list them in a manifest/`REPOS`; run the fixture builder, then `fetch_pr_discussion.py`.
3. Run the Jira connector for each project with the same `JIRA_ORG_SLUG` as the manifest slug.
4. `python -m app.seed --path <fixture>`; then `python -m app.retrieval.embed` with `ORG_SLUG`, `EMBED_PROVIDER=voyage`.
5. Start the API with `ORG_SLUG=<slug>`; check *Sources* for counts, coverage and limits.
Known gaps: PR-to-ticket linking relies on ticket keys in PR text (no branch-name or smart-commit parsing yet); no pagination beyond the limits above; no diffs; free-tier model quotas make large orgs slow; data is sent to the configured model providers (Gemini, Voyage), which the customer must accept.

## What a self-serve flow needs (not built)
Org settings screen (name, GitHub org + token, repos, Jira projects + token) -> encrypted per-org secrets -> GitHub connector with full pagination, incremental sync and webhooks -> multi-project Jira -> background job with progress on *Sources* -> org switcher in the UI -> basic auth and roles -> paid model tier for large orgs.
