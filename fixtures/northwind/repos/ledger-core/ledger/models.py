from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    id: str
    payment_id: str
    amount_cents: int  # ADR-003: integer minor units; see LED-88 for widening
    currency: str
    kind: str  # "capture" | "refund" | "adjustment"
