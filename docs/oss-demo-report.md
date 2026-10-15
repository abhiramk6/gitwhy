# Open-source demo report (oss-pallets)

Provider: `offline-deterministic`. Real public GitHub history for 8 repositories plus a synthetic team-knowledge overlay (ADR-101..108, runbooks).

## Retrieval

| Query | Expected (any of) | Rank | Top results | Result |
|---|---|---|---|---|
| SECRET_KEY_FALLBACKS | flask:src/flask/sessions.py, acme-handbook:docs/adr/ADR-106-session-key-rotation.md | 1 | acme-handbook:docs/adr/ADR-106-session-key-rotation.md (keyword+vector+graph)<br>acme-handbook:docs/adr/ADR-106-session-key-rotation.md (keyword+vector)<br>acme-handbook:runbooks/rotating-session-keys.md (keyword+vector) | PASS |
| what did we decide about rotating session signing keys | acme-handbook:docs/adr/ADR-106-session-key-rotation.md | 1 | acme-handbook:docs/adr/ADR-106-session-key-rotation.md (keyword+vector)<br>acme-handbook:runbooks/rotating-session-keys.md (keyword+vector)<br>flask:src/flask/sessions.py (keyword+vector) | PASS |
| retry with exponential backoff for flaky outbound calls | acme-handbook:docs/adr/ADR-103-outbound-http.md, urllib3:src/urllib3/util/retry.py | 2 | urllib3#5182 (keyword+vector)<br>acme-handbook:docs/adr/ADR-103-outbound-http.md (keyword+vector)<br>acme-handbook:runbooks/http-client-reliability.md (keyword+vector) | PASS |
| who may wrap text in Markup | acme-handbook:docs/adr/ADR-102-html-escaping.md, markupsafe:src/markupsafe/__init__.py | 3 | markupsafe:README.md (keyword+vector)<br>click:src/click/formatting.py (keyword+vector)<br>acme-handbook:docs/adr/ADR-102-html-escaping.md (vector+graph) | PASS |
| FLASK-6170 | FLASK-6170 | 1 | FLASK-6170 (identifier)<br>werkzeug:docs/middleware/http_proxy.rst (vector)<br>werkzeug#3299 (vector) | PASS |

## Feature plans

### PASS — Let Flask session cookies survive a secret key rotation without logging users out

_Why this case:_ flask -> itsdangerous is a real structural import (sessions.py); ADR-105 is superseded

| Component | Role | Label | Reason |
|---|---|---|---|
| flask | primary | inferred | flask is named in the request |
| click | downstream-dependency | verified | flask -> click |
| itsdangerous | downstream-dependency | verified | flask -> itsdangerous |
| jinja | downstream-dependency | verified | flask -> jinja |
| markupsafe | downstream-dependency | verified | flask -> markupsafe |
| werkzeug | downstream-dependency | verified | flask -> werkzeug |

Governing decisions: ADR-101 (verified), ADR-102 (verified), ADR-104 (verified), ADR-106 (verified), ADR-107 (verified), ADR-108 (verified)

- risk [verified] David Lord authored 14/15 commits (93%) to flask/src/flask/sessions.py; bus-factor risk.
- risk [verified] David Lord authored 13/13 commits (100%) to werkzeug/src/werkzeug/datastructures/headers.py; bus-factor risk.
- risk [verified] David Lord authored 19/20 commits (95%) to werkzeug/src/werkzeug/datastructures/structures.py; bus-factor risk.
- risk [verified] David Lord authored 10/10 commits (100%) to flask/src/flask/ctx.py; bus-factor risk.
- task [proposed] T1 Assess whether supporting changes are needed in click for: Let Flask session cookies survive a secret key rotation without logging users out
- task [proposed] T2 Assess whether supporting changes are needed in itsdangerous for: Let Flask session cookies survive a secret key rotation without logging users out
- task [proposed] T3 Assess whether supporting changes are needed in jinja for: Let Flask session cookies survive a secret key rotation without logging users out
- task [proposed] T4 Assess whether supporting changes are needed in markupsafe for: Let Flask session cookies survive a secret key rotation without logging users out
- task [proposed] T5 Assess whether supporting changes are needed in werkzeug for: Let Flask session cookies survive a secret key rotation without logging users out
- task [proposed] T6 Implement the feature core in flask for: Let Flask session cookies survive a secret key rotation without logging users out

### PASS — Change markupsafe escape() so it also escapes backtick characters

_Why this case:_ jinja, werkzeug and flask import markupsafe: the blast radius of a one-line change

| Component | Role | Label | Reason |
|---|---|---|---|
| markupsafe | primary | inferred | markupsafe is named in the request |
| flask | upstream-consumer | verified | flask -> markupsafe |
| jinja | upstream-consumer | verified | jinja -> markupsafe |
| werkzeug | upstream-consumer | verified | werkzeug -> markupsafe |

Governing decisions: ADR-101 (verified), ADR-102 (verified), ADR-104 (verified), ADR-106 (verified), ADR-107 (verified)

- risk [verified] David Lord authored 12/12 commits (100%) to werkzeug/src/werkzeug/datastructures/accept.py; bus-factor risk.
- risk [verified] David Lord authored 13/13 commits (100%) to werkzeug/src/werkzeug/datastructures/etag.py; bus-factor risk.
- risk [verified] David Lord authored 13/13 commits (100%) to werkzeug/src/werkzeug/datastructures/headers.py; bus-factor risk.
- risk [verified] David Lord authored 38/39 commits (97%) to werkzeug/src/werkzeug/http.py; bus-factor risk.
- task [proposed] T1 Implement the feature core in markupsafe for: Change markupsafe escape() so it also escapes backtick characters
- task [proposed] T2 Verify and adapt the consumer in flask for: Change markupsafe escape() so it also escapes backtick characters
- task [proposed] T3 Verify and adapt the consumer in jinja for: Change markupsafe escape() so it also escapes backtick characters
- task [proposed] T4 Verify and adapt the consumer in werkzeug for: Change markupsafe escape() so it also escapes backtick characters
- task [proposed] T5 Reuse the shared implementation instead of duplicating it: werkzeug:src/werkzeug/middleware/lint.py::ErrorStream appears to re-implement click:src/click/_termui_impl.py::_PagerWriter (interface overlap 80%). Prefer the shared implementation.

### PASS — Add retry with exponential backoff to outbound HTTP calls made through requests

_Why this case:_ requests -> urllib3 (models.py imports urllib3.filepost); ADR-103 governs timeouts/retries

| Component | Role | Label | Reason |
|---|---|---|---|
| requests | primary | inferred | requests is named in the request |
| urllib3 | downstream-dependency | verified | requests -> urllib3 |

Governing decisions: ADR-103 (verified), ADR-108 (verified)

- risk [verified] Nate Prewitt authored 13/14 commits (93%) to requests/src/requests/__version__.py; bus-factor risk.
- task [proposed] T1 Assess whether supporting changes are needed in urllib3 for: Add retry with exponential backoff to outbound HTTP calls made through requests
- task [proposed] T2 Implement the feature core in requests for: Add retry with exponential backoff to outbound HTTP calls made through requests

### PASS — Add shell completion for a new Click command group

_Why this case:_ click is the CLI framework; ADR-104 mandates it

| Component | Role | Label | Reason |
|---|---|---|---|
| click | primary | inferred | click is named in the request |
| flask | upstream-consumer | verified | flask -> click |

Governing decisions: ADR-101 (verified), ADR-102 (verified), ADR-104 (verified), ADR-106 (verified), ADR-107 (verified), ADR-108 (verified)

- risk [verified] David Lord authored 10/10 commits (100%) to flask/src/flask/ctx.py; bus-factor risk.
- risk [verified] David Lord authored 14/15 commits (93%) to flask/src/flask/sessions.py; bus-factor risk.
- task [proposed] T1 Implement the feature core in click for: Add shell completion for a new Click command group
- task [proposed] T2 Verify and adapt the consumer in flask for: Add shell completion for a new Click command group
- task [proposed] T3 Reuse the shared implementation instead of duplicating it: werkzeug:src/werkzeug/middleware/lint.py::ErrorStream appears to re-implement click:src/click/_termui_impl.py::_PagerWriter (interface overlap 80%). Prefer the shared implementation.

### PASS — Add GraphQL subscriptions backed by a Kafka event stream

_Why this case:_ nothing in the corpus supports this; the planner must refuse rather than invent a plan

Planner response: `insufficient_evidence` — No repository or service could be linked to this request. Name an API, ticket or component.

---
**Failed expectations: 0**
