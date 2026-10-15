"""Provider delivery. Uses `requests` directly (override recorded in PR #41)."""
import requests

PROVIDER_URL = "https://mail-provider.example/send"


def send(body: dict) -> None:
    requests.post(PROVIDER_URL, json=body, timeout=30)
