"""Outbound HTTP with enforced timeouts and bounded retries (ADR-004)."""
import urllib.request

DEFAULT_TIMEOUT_S = 5
MAX_RETRIES = 2


def request(method: str, url: str, body: bytes | None = None, timeout: float = DEFAULT_TIMEOUT_S) -> bytes:
    last_exc: Exception | None = None
    for _ in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, data=body, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except OSError as exc:
            last_exc = exc
    raise RuntimeError(f"request failed: {url}") from last_exc
