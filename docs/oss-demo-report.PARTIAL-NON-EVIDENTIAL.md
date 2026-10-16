# Open-source demo report (oss-pallets)

Real public GitHub history for 8 repositories plus a synthetic team-knowledge overlay (ADR-101..108, runbooks).

## Run provenance

> ⚠️ **NON-EVIDENTIAL RUN** — partial embedding coverage: ADRs 8/8 · facts 35/35 · issues 303/303 · PRs 722/722 · comments 0/832 · docs 1054/1054 · code 118/1428 · total 2240/4382. Development use only; not a result and not to be cited.
- **Provider:** `gemini-api` · LLM available: **yes**
- **Generation model chain:** gemini-3.8-flash → gemini-3.7-flash → gemini-3.5-flash-lite (answered by: `gemini-3.5-flash-lite`)
- **Embedding model for this corpus:** `voyage-4-large` (2240 vectors), `gemini-embedding-001` (832 vectors) · configured: `voyage-4-large`
- **Embedding coverage (`voyage-4-large`), per tier:** ADRs 8/8 · facts 35/35 · issues 303/303 · PRs 722/722 · comments 0/832 · docs 1054/1054 · code 118/1428 · total 2240/4382 · missing 2142 · stale 0 · orphaned 0 · 27 empty-body records embedded title-only
- ⚠️ **Mixed embedding models in one corpus** — vectors are not comparable across models; re-embed with a single model.
- **Demo-only embedding model.** This corpus uses `voyage-4-large`; the deployment default is `gemini-embedding-2`. Retrieval results on this corpus are **not predictive of `gemini-embedding-2` quality**.
- **Model calls this run:** live **29** · replayed from judgment cache **0** (originally produced by: none) · judgments unavailable **0**
- **Provider accounting:** 29 successful calls, 28 answered by a fallback model, 4 retries, 134435 prompt / 16640 output tokens

## Retrieval

| Query | Expected (any of) | Rank | Mode | Model calls | Top results | Result |
|---|---|---|---|---|---|---|
| SECRET_KEY_FALLBACKS | flask:src/flask/sessions.py, acme-handbook:docs/adr/ADR-106-session-key-rotation.md | 2 | llm+rerank | live 2 · replayed 0 | flask:docs/config.rst~03-builtin-configuration-values (keyword+keyword2+keyword3+keyword4)<br>acme-handbook:docs/adr/ADR-106-session-key-rotation.md (keyword+keyword3+keyword4)<br>acme-handbook:runbooks/rotating-session-keys.md (keyword+keyword3+keyword4) | PASS |
| what did we decide about rotating session signing keys | acme-handbook:docs/adr/ADR-106-session-key-rotation.md | 1 | llm+rerank | live 2 · replayed 0 | acme-handbook:docs/adr/ADR-106-session-key-rotation.md (keyword+keyword2+keyword3+keyword4+keyword5)<br>acme-handbook:docs/adr/ADR-105-session-signing.md (keyword+keyword2+keyword3+keyword4+keyword5)<br>acme-handbook:runbooks/rotating-session-keys.md (keyword+keyword2+keyword3+keyword4) | PASS |
| retry with exponential backoff for flaky outbound calls | acme-handbook:docs/adr/ADR-103-outbound-http.md, urllib3:src/urllib3/util/retry.py | 3 | llm+rerank | live 2 · replayed 0 | urllib3:docs/user-guide.rst~17-configuring-exponential-backoff (keyword+keyword2+keyword3+keyword4)<br>urllib3#5182 (keyword+keyword2+keyword3)<br>acme-handbook:runbooks/http-client-reliability.md (keyword+keyword2+keyword3) | PASS |
| who may wrap text in Markup | acme-handbook:docs/adr/ADR-102-html-escaping.md, markupsafe:src/markupsafe/__init__.py | 1 | llm+rerank | live 2 · replayed 0 | acme-handbook:docs/adr/ADR-102-html-escaping.md (keyword+keyword2+keyword3+vector)<br>acme-handbook:docs/adr/ADR-102-html-escaping.md (keyword2+keyword3+vector)<br>markupsafe:src/markupsafe/__init__.py (keyword+keyword2+keyword3+keyword4) | PASS |
| FLASK-6170 | FLASK-6170 | 1 | llm+rerank | live 2 · replayed 0 | FLASK-6170 (identifier+vector)<br>flask#6170/issue_comment-6183743535 (keyword2) | PASS |

## Feature plans

### PASS — Let Flask session cookies survive a secret key rotation without logging users out

_Why this case:_ flask -> itsdangerous is a real structural import (sessions.py); ADR-105 is superseded

_Search mode:_ llm+rerank · _model calls:_ live 4 · replayed 0 · _guard drops:_ 0

| Component | Role | Label | Reason |
|---|---|---|---|
| flask | primary | inferred | Flask supports SECRET_KEY_FALLBACKS for key rotation via itsdangerous, preventing mass user logouts upon rotation. |
| click | downstream-dependency | verified | flask -> click |
| itsdangerous | downstream-dependency | verified | flask -> itsdangerous |
| jinja | downstream-dependency | verified | flask -> jinja |
| markupsafe | downstream-dependency | verified | flask -> markupsafe |
| werkzeug | downstream-dependency | verified | flask -> werkzeug |

Governing decisions: ADR-106 (inferred)

_Bucket counts (dev):_ decisions required-missing 0 · excluded-present 0 · unlisted 0; risks ok 0 · excluded 0 · unlisted 1; reuse ok 0 · unlisted 0

- risk [inferred] Services still pinned to older versions without SECRET_KEY_FALLBACKS will log every user out upon key rotation.
- task [proposed] task-1 Configure SECRET_KEY_FALLBACKS in Flask

### PASS — Change markupsafe escape() so it also escapes backtick characters

_Why this case:_ jinja, werkzeug and flask import markupsafe: the blast radius of a one-line change

_Search mode:_ llm+rerank · _model calls:_ live 4 · replayed 0 · _guard drops:_ 0

| Component | Role | Label | Reason |
|---|---|---|---|
| markupsafe | primary | inferred | The feature request explicitly requires changing markupsafe's escape() function to also escape backticks. |
| flask | upstream-consumer | verified | ADR-101 dictates that Pallets projects move in lockstep and any change to dependencies like markupsafe must be exercised against flask's test suite. |
| jinja | upstream-consumer | verified | ADR-101 requires testing upstream consumers like jinja when markupsafe is updated. |
| werkzeug | upstream-consumer | verified | ADR-101 requires testing upstream consumers like werkzeug when markupsafe is updated. |

Governing decisions: ADR-101 (verified), ADR-102 (verified)

_Bucket counts (dev):_ decisions required-missing 0 · excluded-present 0 · unlisted 1; risks ok 0 · excluded 0 · unlisted 1; reuse ok 0 · unlisted 0

- risk [verified] Modifying escape() behavior is security-sensitive and can cause unforeseen rendering or escaping regressions in templates and applications if not reviewed and signed off by the security guild.
- task [proposed] task-1 Update markupsafe escape() implementation
- task [proposed] task-2 Obtain security guild sign-off
- task [proposed] task-3 Run lockstep validation across Pallets test suites

### PASS — Add retry with exponential backoff to outbound HTTP calls made through requests

_Why this case:_ requests -> urllib3 (models.py imports urllib3.filepost); ADR-103 governs timeouts/retries

_Search mode:_ llm+rerank · _model calls:_ live 4 · replayed 0 · _guard drops:_ 0

| Component | Role | Label | Reason |
|---|---|---|---|
| requests | primary | inferred | Requests library needs to implement automatic retries with exponential backoff using urllib3. |
| urllib3 | downstream-dependency | verified | urllib3 provides the underlying Retry utility used by requests HTTPAdapter. |

Governing decisions: ADR-103 (inferred), ADR-108 (verified)

_Bucket counts (dev):_ decisions required-missing 0 · excluded-present 0 · unlisted 1; risks ok 0 · excluded 0 · unlisted 1; reuse ok 0 · unlisted 0

- risk [verified] Nate Prewitt authored 93% of commits to requests/src/requests/__version__.py; bus-factor risk.
- task [proposed] task-1 Configure requests HTTPAdapter with urllib3 Retry object
- task [proposed] task-2 Verify exponential backoff and jitter configuration in urllib3

### FAIL — Add shell completion for a new Click command group

_Why this case:_ click is the CLI framework; ADR-104 mandates it

_Search mode:_ llm+rerank · _model calls:_ live 4 · replayed 0 · _guard drops:_ 0

**Problems:** excluded decision present: ADR-101

| Component | Role | Label | Reason |
|---|---|---|---|
| click | primary | inferred | The request is to add shell completion for a new Click command group, which requires modifying Click/command group definitions to support and expose shell completion scripts. |
| flask | upstream-consumer | verified | Flask consumes Click for its CLI and application commands via FlaskGroup/AppGroup, but adding a shell completion for a Click command group is handled entirely at the Click level or through standard Click environment mechanisms without requiring changes to Flask core application logic. |

Governing decisions: ADR-101 (verified), ADR-104 (verified), ADR-108 (verified)

_Bucket counts (dev):_ decisions required-missing 0 · excluded-present 1 · unlisted 1; risks ok 0 · excluded 0 · unlisted 1; reuse ok 0 · unlisted 0

- risk [inferred] Conflict between ADR-107 (Flask services return RFC 7807 problem+json errors) and ADR-108 (Command line tools print plain-text errors and exit non-zero). Ensure CLI error handling adheres to ADR-108 and does not return JSON error bodies.
- task [proposed] task-1 Define the new Click command group
- task [proposed] task-2 Enable shell completion variables and instructions for the command group

### PASS — Add GraphQL subscriptions backed by a Kafka event stream

_Why this case:_ nothing in the corpus supports this; the planner must refuse rather than invent a plan

_Search mode:_ llm+rerank · _model calls:_ live 3 · replayed 0 · _guard drops:_ 0

Planner response: `insufficient_evidence` — {'type': 'question', 'label': 'proposed', 'evidence': [], 'summary': 'The provided evidence discusses Flask and Blinker signal subscriptions, but the feature request is about adding GraphQL subscriptions backed by a Kafka event stream, which is unrelated to the provided repositories and documentation.'}

## Scoring lists

- Lists: `eval/oss_dev_lists.json` — **agent-confirmed, not human-reviewed (owner delegated confirmation on 2026-10-15; to be reviewed once at the next milestone)**. excluded_subjects were drafted AFTER the author had seen output of the earlier rule-based (pre-LLM, commit a7fccfa) planner, which listed bus-factor risks about unrelated werkzeug datastructures files and unrelated libraries for these requests. They are therefore informed by that output and are used on DEV cases only. Held-out cases have no excluded_subjects; their unlisted risks and reuse are reported as counts only.
- Unlisted items for review (dev only; not auto-failed): **7**

  - [Let Flask session cookies survive a secr…] risk (unlisted): Services still pinned to older versions without SECRET_KEY_FALLBACKS will log every user out upon key rotation
  - [Change markupsafe escape() so it also es…] decision ADR-101 (unlisted)
  - [Change markupsafe escape() so it also es…] risk (unlisted): Modifying escape() behavior is security-sensitive and can cause unforeseen rendering or escaping regressions i
  - [Add retry with exponential backoff to ou…] decision ADR-108 (unlisted)
  - [Add retry with exponential backoff to ou…] risk (unlisted): Nate Prewitt authored 93% of commits to requests/src/requests/__version__.py; bus-factor risk.
  - [Add shell completion for a new Click com…] decision ADR-108 (unlisted)
  - [Add shell completion for a new Click com…] risk (unlisted): Conflict between ADR-107 (Flask services return RFC 7807 problem+json errors) and ADR-108 (Command line tools 

---
**Result: **PASS 9 / FAIL 1 / SKIPPED 0** — 1 failed**
**Failed expectations: 1**
