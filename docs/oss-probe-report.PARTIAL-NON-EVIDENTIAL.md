# Open-source probe report

Questions were written from general knowledge of Flask/Werkzeug/Jinja/Click/Requests/urllib3, not from the indexed text. Result: **PASS 12 / FAIL 0 / SKIPPED 0** (all expectations met)

## Run provenance

> ⚠️ **NON-EVIDENTIAL RUN** — partial embedding coverage: ADRs 8/8 · facts 35/35 · issues 303/303 · PRs 722/722 · comments 0/832 · docs 1054/1054 · code 118/1428 · total 2240/4382. Development use only; not a result and not to be cited.
- **Provider:** `gemini-api` · LLM available: **yes**
- **Generation model chain:** gemini-3.8-flash → gemini-3.7-flash → gemini-3.5-flash-lite (answered by: `gemini-3.5-flash-lite`)
- **Embedding model for this corpus:** `voyage-4-large` (2240 vectors), `gemini-embedding-001` (832 vectors) · configured: `voyage-4-large`
- **Embedding coverage (`voyage-4-large`), per tier:** ADRs 8/8 · facts 35/35 · issues 303/303 · PRs 722/722 · comments 0/832 · docs 1054/1054 · code 118/1428 · total 2240/4382 · missing 2142 · stale 0 · orphaned 0 · 27 empty-body records embedded title-only
- ⚠️ **Mixed embedding models in one corpus** — vectors are not comparable across models; re-embed with a single model.
- **Demo-only embedding model.** This corpus uses `voyage-4-large`; the deployment default is `gemini-embedding-2`. Retrieval results on this corpus are **not predictive of `gemini-embedding-2` quality**.
- **Model calls this run:** live **42** · replayed from judgment cache **0** (originally produced by: none) · judgments unavailable **0**
- **Provider accounting:** 42 successful calls, 40 answered by a fallback model, 4 retries, 168093 prompt / 29882 output tokens

## Questions (top 5)

| Question | First correct source (rank) | Mode | Model calls | Top 3 |
|---|---|---|---|---|
| Where is the application context pushed during a request in Flask? | rank 2 | llm+rerank | live 2 · replayed 0 | flask:docs/lifecycle.rst~04-how-a-request-is-handled<br>flask:src/flask/ctx.py<br>flask:src/flask/app.py |
| How does Flask sign session cookies? | rank 1 | llm+rerank | live 2 · replayed 0 | flask:src/flask/sessions.py<br>flask:docs/api.rst~05-sessions<br>acme-handbook:docs/adr/ADR-105-session-signing.md |
| How does Werkzeug match a URL to an endpoint? | rank 2 | llm+rerank | live 2 · replayed 0 | werkzeug:docs/tutorial.rst~07-step-4-the-routing<br>werkzeug:docs/routing.rst~01-quickstart<br>werkzeug:docs/routing.rst~11-host-matching |
| What does click.echo do differently from print? | rank 1 | llm+rerank | live 2 · replayed 0 | click:docs/utils.md~01-printing-to-stdout<br>click:docs/quickstart.md~04-echoing<br>click:docs/wincmd.md |
| How does requests handle redirects? | rank 1 | llm+rerank | live 2 · replayed 0 | requests:docs/user/quickstart.rst~13-redirection-and-history<br>requests:src/requests/models.py<br>requests:src/requests/sessions.py |
| How does urllib3 decide whether to retry a request? | rank 1 | llm+rerank | live 2 · replayed 0 | urllib3:src/urllib3/util/retry.py<br>urllib3:docs/user-guide.rst~16-retrying-requests<br>urllib3:docs/user-guide.rst~17-configuring-exponential-backoff |
| What is the Jinja sandbox for? | rank 1 | llm+rerank | live 2 · replayed 0 | jinja:docs/sandbox.rst~00-sandbox<br>jinja:src/jinja2/sandbox.py<br>jinja:docs/sandbox.rst~01-security-considerations |
| When was SECRET_KEY_FALLBACKS added to Flask? | rank 2 | llm+rerank | live 2 · replayed 0 | flask:docs/config.rst~03-builtin-configuration-values<br>flask:changelog/Version-3.1.0.md<br>acme-handbook:docs/adr/ADR-106-session-key-rotation.md |
| Who maintains Flask session handling? | rank 1 | llm+rerank | live 2 · replayed 0 | flask:src/flask/sessions.py<br>flask:docs/testing.rst~07-accessing-and-modifying-the-session<br>flask:docs/api.rst~05-sessions |
| What happens if Markup is built from user input? | rank 1 | llm+rerank | live 2 · replayed 0 | acme-handbook:docs/adr/ADR-102-html-escaping.md<br>markupsafe:README.md<br>markupsafe:docs/html.rst |
| Why must POST retries use an idempotency key? | rank 1 | llm+rerank | live 2 · replayed 0 | acme-handbook:docs/adr/ADR-103-outbound-http.md<br>urllib3:docs/user-guide.rst~16-retrying-requests |
| Which decision replaced single-key session signing? | rank 1 | llm+rerank | live 2 · replayed 0 | acme-handbook:docs/adr/ADR-106-session-key-rotation.md<br>acme-handbook:docs/adr/ADR-106-session-key-rotation.md<br>acme-handbook:docs/adr/ADR-105-session-signing.md |
| How does the Django ORM generate migrations? | n/a - out of corpus: a good system returns nothing relevant | llm+rerank | live 2 · replayed 0 | jinja:docs/switching.rst~01-django<br>jinja:docs/switching.rst~02-method-calls |

**Answered within top 5: 12/12**

## Feature requests

### Add CSRF protection to Flask forms

_Model calls: live 4 · replayed 0 · search mode: llm+rerank · guard drops: 0_

Components: flask (primary, inferred), click (downstream-dependency, verified), itsdangerous (downstream-dependency, verified), jinja (downstream-dependency, verified), markupsafe (downstream-dependency, verified), werkzeug (downstream-dependency, verified)

Decisions: ADR-101, ADR-102, ADR-107

Risks: 1; tasks: 2; open questions: 2

### Make Jinja templates compile once and be cached across processes

_Model calls: live 4 · replayed 0 · search mode: llm+rerank · guard drops: 0_

Components: jinja (primary, inferred), markupsafe (downstream-dependency, verified), flask (upstream-consumer, verified)

Decisions: ADR-101, ADR-102

Risks: 1; tasks: 2; open questions: 2

### Upgrade urllib3 to the next major version

_Model calls: live 4 · replayed 0 · search mode: llm+rerank · guard drops: 0_

Components: urllib3 (primary, inferred), requests (upstream-consumer, verified)

Decisions: ADR-103, ADR-108

Risks: 2; tasks: 3; open questions: 1

### Rewrite Flask in Rust

_Model calls: live 4 · replayed 0 · search mode: llm+rerank · guard drops: 0_

Components: flask (primary, inferred), click (downstream-dependency, verified), itsdangerous (downstream-dependency, verified), jinja (downstream-dependency, verified), markupsafe (downstream-dependency, verified), werkzeug (downstream-dependency, verified)

Decisions: ADR-101, ADR-102, ADR-104, ADR-106, ADR-107, ADR-108

Risks: 1; tasks: 4; open questions: 2

