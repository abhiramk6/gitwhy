"""BFF endpoints. NOTE: uses `requests` directly (no override recorded; see PR #57)."""
import requests

PAYMENTS_URL = "http://payments-api.internal/v1/payments"


def capture(payment_id: str, amount_cents: int, currency: str) -> dict:
    r = requests.post(f"{PAYMENTS_URL}/{payment_id}/capture",
                      json={"amount_cents": amount_cents, "currency": currency}, timeout=60)
    return r.json()


def list_receipts(customer_id: str) -> list[dict]:
    return []
