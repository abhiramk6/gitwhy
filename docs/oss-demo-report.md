# Open-source demo report (oss-pallets)

Provider: `offline`. Real public GitHub history for 8 repositories plus a synthetic team-knowledge overlay (ADR-101..108, runbooks).

## Retrieval

| Query | Expected (any of) | Rank | Top results | Result |
|---|---|---|---|---|
| SECRET_KEY_FALLBACKS | flask:src/flask/sessions.py, acme-handbook:docs/adr/ADR-106-session-key-rotation.md | 1 | acme-handbook:docs/adr/ADR-106-session-key-rotation.md (keyword)<br>acme-handbook:runbooks/rotating-session-keys.md (keyword)<br>acme-handbook:docs/adr/ADR-106-session-key-rotation.md (keyword) | PASS |
| what did we decide about rotating session signing keys | acme-handbook:docs/adr/ADR-106-session-key-rotation.md | - | werkzeug:src/werkzeug/datastructures/structures.py (keyword)<br>werkzeug:src/werkzeug/datastructures/headers.py (keyword)<br>flask:src/flask/sessions.py (keyword) | FAIL |
| retry with exponential backoff for flaky outbound calls | acme-handbook:docs/adr/ADR-103-outbound-http.md, urllib3:src/urllib3/util/retry.py | 1 | urllib3:src/urllib3/util/retry.py (keyword)<br>urllib3:src/urllib3/connectionpool.py (keyword)<br>urllib3:docs/user-guide.rst~17-configuring-exponential-backoff (keyword) | PASS |
| who may wrap text in Markup | acme-handbook:docs/adr/ADR-102-html-escaping.md, markupsafe:src/markupsafe/__init__.py | 2 | jinja:src/jinja2/filters.py (keyword)<br>markupsafe:src/markupsafe/__init__.py (keyword)<br>click:src/click/termui.py (keyword) | PASS |
| FLASK-6170 | FLASK-6170 | 1 | FLASK-6170 (identifier) | PASS |

## Feature plans

### SKIPPED — Let Flask session cookies survive a secret key rotation without logging users out

Planning needs an LLM provider; none configured.

### SKIPPED — Change markupsafe escape() so it also escapes backtick characters

Planning needs an LLM provider; none configured.

### SKIPPED — Add retry with exponential backoff to outbound HTTP calls made through requests

Planning needs an LLM provider; none configured.

### SKIPPED — Add shell completion for a new Click command group

Planning needs an LLM provider; none configured.

### SKIPPED — Add GraphQL subscriptions backed by a Kafka event stream

Planning needs an LLM provider; none configured.

---
**Failed expectations: 1**
