from fastapi import APIRouter

from .entries import get_entry, post_entry
from .models import Entry

router = APIRouter()


@router.post("/v1/ledger/entries")
def create_entry(body: dict) -> dict:
    e = post_entry(Entry(**body))
    return {"id": e.id}


@router.get("/v1/ledger/entries/{entry_id}")
def read_entry(entry_id: str) -> dict:
    e = get_entry(entry_id)
    return {"found": e is not None}
