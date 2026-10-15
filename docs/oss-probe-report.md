# Open-source probe report

Provider: `offline-deterministic`. Questions were written from general knowledge of Flask/Werkzeug/Jinja/Click/Requests/urllib3, not from the indexed text.

## Questions (top 5)

| Question | First correct source (rank) | Top 3 |
|---|---|---|
| Where is the application context pushed during a request in Flask? | rank 1 | flask:docs/appcontext.rst~04-visibility-of-the-context<br>flask:docs/appcontext.rst~06-how-the-context-works<br>flask:docs/extensiondev.rst~05-data-during-a-request |
| How does Flask sign session cookies? | MISS | flask:docs/web-security.rst~10-set-cookie-options<br>requests:docs/user/advanced.rst~01-session-objects<br>flask:docs/testing.rst~07-accessing-and-modifying-the-session |
| How does Werkzeug match a URL to an endpoint? | rank 1 | werkzeug:docs/routing.rst~12-websockets<br>werkzeug:docs/tutorial.rst~07-step-4-the-routing<br>werkzeug:docs/tutorial.rst~08-step-5-the-first-view |
| What does click.echo do differently from print? | rank 1 | click:docs/utils.md~01-printing-to-stdout<br>click:docs/arguments.md~04-environment-variables<br>CLICK-3841 |
| How does requests handle redirects? | MISS | urllib3:docs/user-guide.rst~16-retrying-requests<br>requests:src/requests/__version__.py<br>requests:README.md |
| How does urllib3 decide whether to retry a request? | rank 2 | werkzeug:src/werkzeug/exceptions.py<br>urllib3:docs/user-guide.rst~16-retrying-requests<br>urllib3:src/urllib3/util/retry.py |
| What is the Jinja sandbox for? | rank 1 | JINJA-2206<br>jinja:docs/api.rst~02-high-level-api<br>flask:docs/templating.rst~01-jinja-setup |
| When was SECRET_KEY_FALLBACKS added to Flask? | rank 1 | flask:changelog/Version-3.1.0.md<br>acme-handbook:runbooks/rotating-session-keys.md<br>acme-handbook:docs/adr/ADR-106-session-key-rotation.md |
| Who maintains Flask session handling? | rank 5 | flask:docs/testing.rst~07-accessing-and-modifying-the-session<br>requests:docs/user/advanced.rst~01-session-objects<br>flask:docs/quickstart.rst~01-a-minimal-application |
| What happens if Markup is built from user input? | rank 2 | werkzeug:src/werkzeug/sansio/request.py<br>markupsafe:src/markupsafe/__init__.py<br>flask:docs/tutorial/views.rst~03-login |
| Why must POST retries use an idempotency key? | rank 5 | itsdangerous:docs/concepts.rst~04-key-rotation<br>urllib3:src/urllib3/util/retry.py<br>urllib3:docs/user-guide.rst~16-retrying-requests |
| Which decision replaced single-key session signing? | rank 3 | flask:docs/testing.rst~07-accessing-and-modifying-the-session<br>requests:docs/user/advanced.rst~03-prepared-requests<br>acme-handbook:docs/adr/ADR-106-session-key-rotation.md |
| How does the Django ORM generate migrations? | n/a - out of corpus: a good system returns nothing relevant | jinja:docs/switching.rst~01-django<br>flask:docs/patterns/streaming.rst<br>click:docs/click-concepts.md |

**Answered within top 5: 10/12**

## Feature requests

### Add CSRF protection to Flask forms

Components: flask (primary, inferred), click (downstream-dependency, verified), itsdangerous (downstream-dependency, verified), jinja (downstream-dependency, verified), markupsafe (downstream-dependency, verified), werkzeug (downstream-dependency, verified)

Decisions: ADR-101, ADR-102, ADR-104, ADR-106, ADR-107, ADR-108

Risks: 4; tasks: 7; open questions: 3

### Make Jinja templates compile once and be cached across processes

Components: jinja (primary, inferred), markupsafe (downstream-dependency, verified), flask (upstream-consumer, verified)

Decisions: ADR-101, ADR-102, ADR-104, ADR-106, ADR-107

Risks: 2; tasks: 3; open questions: 2

### Upgrade urllib3 to the next major version

Components: urllib3 (primary, inferred), requests (upstream-consumer, verified)

Decisions: ADR-103, ADR-108

Risks: 1; tasks: 2; open questions: 2

### Rewrite Flask in Rust

Components: flask (primary, inferred), click (downstream-dependency, verified), itsdangerous (downstream-dependency, verified), jinja (downstream-dependency, verified), markupsafe (downstream-dependency, verified), werkzeug (downstream-dependency, verified)

Decisions: ADR-101, ADR-102, ADR-104, ADR-106, ADR-107, ADR-108

Risks: 4; tasks: 7; open questions: 3

