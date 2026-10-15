"""Client for ledger-core.

NOTE: synchronous call per ADR-002. (ADR-002 is superseded by ADR-007; migration to the outbox is pending.)
"""
import json

from platform_libs.http_client import request

LEDGER_URL = "http://ledger-core.internal/v1/ledger/entries"


def post_ledger_entry(payment_id: str, amount_cents: int, currency: str, kind: str) -> None:
    payload = {"id": f"{payment_id}:{kind}", "payment_id": payment_id,
               "amount_cents": amount_cents, "currency": currency, "kind": kind}
    request("POST", LEDGER_URL, json.dumps(payload).encode())
