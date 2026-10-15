# ADR-105: Session cookies are signed with a single SECRET_KEY

Status: superseded
Superseded-by: ADR-106
Date: 2025-11-02
Scope: flask, itsdangerous
Topic: session-security

Flask session cookies are signed with one SECRET_KEY through itsdangerous. Rotating the key invalidates every active session.
