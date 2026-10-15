from fastapi import APIRouter

from .dedupe import DedupeStore
from .sender import send

router = APIRouter()
_dedupe = DedupeStore()


@router.post("/v1/notifications")
def create_notification(body: dict) -> dict:
    key = body.get("dedupe_key", body.get("payment_id", ""))
    if not _dedupe.claim(key, body.get("template", "")):
        return {"code": "duplicate", "message": "already sent"}
    send(body)
    return {"code": "ok", "message": "queued"}
