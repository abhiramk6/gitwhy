"""Nightly reconciliation of ledger entries against processor settlement files.

Critical path: month-end close depends on this module.
"""
from platform_libs.http_client import request

from .entries import _ENTRIES


def reconcile_batch(settlement_url: str) -> dict:
    raw = request("GET", settlement_url)
    expected = len(raw.splitlines())
    return {"expected": expected, "posted": len(_ENTRIES), "balanced": expected == len(_ENTRIES)}
