# Dev scoring lists for the open-source demo: review sheet

Written by the agent, not human-reviewed. These apply to the 5 DEV cases only; held-out cases have no lists.

How to read: **Must appear** = the plan has to include this decision. **Fails if present** = the plan must not apply this decision. **Fine to mention** = relevant risks/reuse the plan may list. **Never relevant** = noise; if it appears, it is flagged. Anything not listed is only reported for review, never auto-failed.

Please tell me, per case, anything that is wrong: a decision that should be required, one that should not be excluded, a subject that should be allowed.

## D1: Let Flask session cookies survive a secret key rotation without logging users out

- **Must appear:** ADR-106
- **Fails if present:** ADR-105, ADR-102, ADR-103, ADR-104, ADR-107, ADR-108
- **Judged case by case (not failed):** ADR-101: no dependency version is being changed -> reviewed, not failed.
- **Fine to mention (risks):**
  - `flask:src/flask/sessions.py`: Cookie session implementation
  - `flask:src/flask/config.py`: SECRET_KEY / SECRET_KEY_FALLBACKS configuration
  - `itsdangerous:src/itsdangerous/*`: Signing library behind session cookies
  - `acme-handbook:docs/adr/ADR-106-*`: Governing decision
  - `acme-handbook:runbooks/rotating-session-keys.md`: Rotation procedure
  - `acme-handbook:runbooks/postmortem-PM-2025-11-session-logout.md`: Prior incident: mass logout on rotation
- **Fine to reuse:** flask (SECRET_KEY_FALLBACKS already exists), itsdangerous (Signer key rotation support)
- **Never relevant (flagged if it appears):**
  - `werkzeug:src/werkzeug/datastructures/*`: HTTP header/ETag/Accept structures: nothing to do with cookie signing (appeared as bus-factor noise in the old plan)
  - `flask:src/flask/ctx.py`: Request-context internals; not touched by key rotation (appeared as bus-factor noise in the old plan)
  - `click:*`: CLI framework: no role in session signing
  - `requests:*`: Outbound HTTP client: no role in session signing
  - `urllib3:*`: Outbound HTTP transport: no role in session signing
  - `jinja:*`: Templating: no role in session signing

## D2: Change markupsafe escape() so it also escapes backtick characters

- **Must appear:** ADR-102
- **Fails if present:** ADR-105, ADR-106, ADR-103, ADR-104, ADR-107, ADR-108
- **Judged case by case (not failed):** ADR-101 moved from 'allowed' to unlisted (review). Consistent rule: ADR-101 applies when the request changes the VERSION of a Pallets package (as in the held-out Jinja upgrade case); a behaviour change inside markupsafe only reaches that rule when it is released and consumers bump it, which the request does not ask for.
- **Fine to mention (risks):**
  - `markupsafe:src/markupsafe/*`: escape() implementation
  - `markupsafe:docs/escaping.rst`: Escaping documentation
  - `jinja:src/jinja2/*`: Consumer of escape(): blast radius
  - `flask:src/flask/*.py`: Consumer of escape(): blast radius
  - `werkzeug:src/werkzeug/*.py`: Consumer of escape(): blast radius
  - `acme-handbook:docs/adr/ADR-102-*`: Governing decision (security sign-off)
  - `acme-handbook:runbooks/upgrading-markupsafe-and-jinja.md`: Procedure for shipping a markupsafe change
- **Fine to reuse:** markupsafe (escape() is the single implementation to modify)
- **Never relevant (flagged if it appears):**
  - `werkzeug:src/werkzeug/datastructures/*`: Header/ETag/Accept structures do not call escape() (appeared as bus-factor noise in the old plan); wins over the broad werkzeug consumer glob
  - `click:*`: CLI framework: does not consume markupsafe.escape
  - `requests:*`: HTTP client: no escaping involved
  - `urllib3:*`: HTTP transport: no escaping involved
  - `itsdangerous:*`: Signing library: no escaping involved

## D3: Add retry with exponential backoff to outbound HTTP calls made through requests

- **Must appear:** ADR-103
- **Fails if present:** ADR-105, ADR-106, ADR-102, ADR-107, ADR-101
- **Judged case by case (not failed):** ADR-104 and ADR-108 (CLI) have requests/click scope but are not about HTTP retries -> reviewed.
- **Fine to mention (risks):**
  - `requests:src/requests/adapters.py`: HTTPAdapter mounts the Retry
  - `requests:src/requests/sessions.py`: Session adapters and timeouts
  - `urllib3:src/urllib3/util/retry.py`: Retry object
  - `urllib3:src/urllib3/util/timeout.py`: Timeout object
  - `acme-handbook:runbooks/http-client-reliability.md`: Team runbook
  - `acme-handbook:docs/adr/ADR-103-*`: Governing decision
- **Fine to reuse:** urllib3 (Retry is the mandated mechanism), requests (HTTPAdapter)
- **Never relevant (flagged if it appears):**
  - `flask:*`: Web framework: not on the requests/urllib3 retry path
  - `werkzeug:*`: WSGI toolkit: not on the requests/urllib3 retry path
  - `jinja:*`: Templating: unrelated
  - `markupsafe:*`: Escaping: unrelated
  - `itsdangerous:*`: Signing: unrelated

## D4: Add shell completion for a new Click command group

- **Must appear:** ADR-104
- **Fails if present:** ADR-105, ADR-106, ADR-102, ADR-103, ADR-107, ADR-101
- **Judged case by case (not failed):** ADR-108 (CLI error output) is plausibly relevant to a new command group -> reviewed.
- **Fine to mention (risks):**
  - `click:src/click/shell_completion.py`: Completion machinery
  - `click:docs/*completion*`: Completion documentation
  - `click:src/click/core.py`: Command groups
  - `click:src/click/decorators.py`: Group/command decorators
  - `acme-handbook:docs/adr/ADR-104-*`: Governing decision
- **Fine to reuse:** click (Built-in shell completion)
- **Never relevant (flagged if it appears):**
  - `werkzeug:src/werkzeug/datastructures/*`: HTTP structures: unrelated to CLI completion (appeared as bus-factor noise in the old plan)
  - `requests:*`: HTTP client: unrelated to CLI completion
  - `urllib3:*`: HTTP transport: unrelated to CLI completion
  - `jinja:*`: Templating: unrelated
  - `markupsafe:*`: Escaping: unrelated
  - `itsdangerous:*`: Signing: unrelated

## D5: Add GraphQL subscriptions backed by a Kafka event stream

- **Must appear:** none
- **Fails if present:** ADR-101, ADR-102, ADR-103, ADR-104, ADR-105, ADR-106, ADR-107, ADR-108
- **Fine to mention (risks):**
- **Fine to reuse:** none
- **Never relevant (flagged if it appears):**
