# ADR-006: Notification errors use a {code, message} envelope

Status: accepted
Date: 2026-03-04
Scope: notify-svc
Topic: error-format

notify-svc responses use `{ "code": ..., "message": ... }` so downstream templates stay simple.
