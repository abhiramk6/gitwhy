"""Notification de-duplication (own implementation, added in PR #48)."""


class DedupeStore:
    def __init__(self) -> None:
        self._seen: dict[str, str] = {}

    def claim(self, key: str, fingerprint: str) -> bool:
        if key in self._seen:
            return False
        self._seen[key] = fingerprint
        return True

    def release(self, key: str) -> None:
        self._seen.pop(key, None)

    def result(self, key: str) -> str | None:
        return self._seen.get(key)
