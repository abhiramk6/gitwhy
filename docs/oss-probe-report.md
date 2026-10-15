# Open-source probe report

Provider: `offline`. Questions were written from general knowledge of Flask/Werkzeug/Jinja/Click/Requests/urllib3, not from the indexed text.

## Questions (top 5)

| Question | First correct source (rank) | Top 3 |
|---|---|---|
| Where is the application context pushed during a request in Flask? | rank 1 | flask:docs/appcontext.rst~04-visibility-of-the-context<br>flask:src/flask/ctx.py<br>flask:docs/testing.rst~09-tests-that-depend-on-an-active-context |
| How does Flask sign session cookies? | rank 1 | acme-handbook:docs/adr/ADR-105-session-signing.md<br>flask:docs/api.rst~05-sessions<br>flask:src/flask/sessions.py |
| How does Werkzeug match a URL to an endpoint? | rank 1 | werkzeug:docs/routing.rst~12-websockets<br>werkzeug:src/werkzeug/routing/rules.py<br>werkzeug:docs/routing.rst~11-host-matching |
| What does click.echo do differently from print? | rank 1 | click:docs/utils.md~01-printing-to-stdout<br>click:docs/wincmd.md<br>CLICK-3841 |
| How does requests handle redirects? | rank 5 | urllib3:docs/user-guide.rst~16-retrying-requests<br>flask:docs/api.rst~19-url-route-registrations<br>flask:docs/lifecycle.rst~04-how-a-request-is-handled |
| How does urllib3 decide whether to retry a request? | rank 1 | urllib3:src/urllib3/util/retry.py<br>requests:src/requests/adapters.py<br>requests:src/requests/sessions.py |
| What is the Jinja sandbox for? | rank 1 | jinja:docs/sandbox.rst~00-sandbox<br>jinja:docs/sandbox.rst~03-operator-intercepting<br>jinja:changelog/Version-3.1.5.md |
| When was SECRET_KEY_FALLBACKS added to Flask? | rank 1 | flask:changelog/Version-3.1.0.md<br>flask:src/flask/app.py<br>flask:src/flask/sessions.py |
| Who maintains Flask session handling? | rank 2 | flask:docs/quickstart.rst~09-about-responses<br>flask:src/flask/sessions.py<br>flask:src/flask/app.py |
| What happens if Markup is built from user input? | rank 3 | jinja:src/jinja2/filters.py<br>click:src/click/testing.py<br>markupsafe:src/markupsafe/__init__.py |
| Why must POST retries use an idempotency key? | MISS | werkzeug:src/werkzeug/datastructures/headers.py<br>werkzeug:src/werkzeug/datastructures/structures.py<br>urllib3:src/urllib3/poolmanager.py |
| Which decision replaced single-key session signing? | MISS | flask:src/flask/sessions.py<br>flask:docs/config.rst~03-builtin-configuration-values<br>requests:src/requests/sessions.py |
| How does the Django ORM generate migrations? | n/a - out of corpus: a good system returns nothing relevant | flask:docs/patterns/streaming.rst<br>flask:src/flask/helpers.py<br>jinja:src/jinja2/environment.py |

**Answered within top 5: 10/12**

## Feature requests

### Add CSRF protection to Flask forms

Not planned: `llm_required`.

### Make Jinja templates compile once and be cached across processes

Not planned: `llm_required`.

### Upgrade urllib3 to the next major version

Not planned: `llm_required`.

### Rewrite Flask in Rust

Not planned: `llm_required`.

