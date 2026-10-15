# Postmortem PM-2025-11: all users logged out after secret rotation

Impact: every active session was invalidated for roughly forty minutes during a routine secret rotation.
Cause: the service signed cookies with a single SECRET_KEY (ADR-105) and the rotation replaced it in place.
Follow-up: adopt SECRET_KEY_FALLBACKS (ADR-106) and add a rotation rehearsal to the runbook.
