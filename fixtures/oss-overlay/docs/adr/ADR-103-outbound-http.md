# ADR-103: Outbound HTTP uses requests with explicit timeouts and urllib3 Retry

Status: accepted
Date: 2026-03-18
Scope: requests, urllib3
Topic: http-client

All outbound HTTP calls set an explicit (connect, read) timeout; there is no default. Retries are configured through a urllib3 Retry object mounted on a requests HTTPAdapter, with exponential backoff and only for idempotent methods. Never retry POST without an idempotency key.
