"""Idempotency keys for mutating endpoints. Reuse this; do not re-implement."""


class IdempotencyStore:
    def __init__(self) -> None:
        self._seen: dict[str, str] = {}

    def claim(self, key: str, fingerprint: str) -> bool:
        """Return True if this key is new; False if it was already claimed."""
        if key in self._seen:
            return False
        self._seen[key] = fingerprint
        return True

    def release(self, key: str) -> None:
        self._seen.pop(key, None)

    def result(self, key: str) -> str | None:
        return self._seen.get(key)
