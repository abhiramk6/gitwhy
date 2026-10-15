# ADR-101: Flask, Werkzeug, Jinja, Click, MarkupSafe and ItsDangerous are upgraded together

Status: accepted
Date: 2026-02-10
Scope: flask, werkzeug, jinja, click, markupsafe, itsdangerous
Topic: dependency-management

The Pallets projects move in lockstep and Flask imports from all of the others. We keep a single constraints file and upgrade them as one change set, never one at a time. A bump of markupsafe, werkzeug or jinja must be exercised against flask's test suite before merge.
