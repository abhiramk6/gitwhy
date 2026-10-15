# Runbook: flaky outbound calls

Symptoms: intermittent ConnectionError or ReadTimeout from requests. First confirm an explicit timeout is set (ADR-103). Then mount a urllib3 Retry with backoff_factor and status_forcelist on an HTTPAdapter; check that the retried method is idempotent. Raising the timeout is not a fix.
