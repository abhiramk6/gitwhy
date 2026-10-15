# ADR-004: Outbound HTTP goes through platform_libs.http_client

Status: accepted
Date: 2026-02-03
Scope: org
Topic: outbound-http

Every outbound HTTP call must use `platform_libs.http_client.request` so timeouts and bounded retries are enforced. Exceptions require an `Override:` trailer in the PR description naming this ADR and a reason.
