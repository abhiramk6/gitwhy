from fastapi import APIRouter
from platform_libs.errors import problem
from platform_libs.idempotency import IdempotencyStore

from .ledger_client import post_ledger_entry
from .notifier import notify_customer

router = APIRouter()
_store = IdempotencyStore()


@router.post("/v1/payments")
def create_payment(body: dict) -> dict:
    return {"id": body.get("id", "pay_1"), "status": "authorized"}


@router.post("/v1/payments/{payment_id}/capture")
def capture_payment(payment_id: str, body: dict) -> dict:
    key = body.get("idempotency_key", payment_id)
    if not _store.claim(key, payment_id):
        return problem(409, "duplicate capture")
    post_ledger_entry(payment_id, body["amount_cents"], body["currency"], "capture")
    notify_customer(payment_id, "payment_captured")
    return {"id": payment_id, "status": "captured"}
