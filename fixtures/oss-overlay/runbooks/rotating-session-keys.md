# Runbook: rotating the Flask session signing key

1. Generate a new random key and add it as SECRET_KEY, moving the old value to SECRET_KEY_FALLBACKS.
2. Deploy. Existing sessions keep working because itsdangerous also tries the fallback keys.
3. After the maximum session lifetime has passed, remove the old key from SECRET_KEY_FALLBACKS.
Known gotcha: services still pinned to a Flask version without SECRET_KEY_FALLBACKS log every user out on rotation (see postmortem PM-2025-11).
