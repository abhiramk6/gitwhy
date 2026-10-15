# ADR-005: Errors use RFC 7807 problem+json

Status: accepted
Date: 2026-02-10
Scope: payments-api, platform-libs
Topic: error-format

HTTP errors are returned as `application/problem+json` using `platform_libs.errors.problem`.
