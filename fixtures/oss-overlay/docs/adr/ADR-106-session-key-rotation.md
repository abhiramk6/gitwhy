# ADR-106: Session signing keys are rotated using SECRET_KEY_FALLBACKS

Status: accepted
Supersedes: ADR-105
Date: 2026-04-14
Scope: flask, itsdangerous
Topic: session-security

Keys are rotated quarterly. The new key becomes SECRET_KEY and the previous keys are listed in SECRET_KEY_FALLBACKS so existing sessions keep validating until they expire. Fallback keys are removed after the maximum session lifetime.
