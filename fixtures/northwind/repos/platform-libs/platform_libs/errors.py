"""RFC 7807 problem+json error bodies (ADR-005)."""


def problem(status: int, title: str, detail: str = "") -> dict:
    return {"type": "about:blank", "title": title, "status": status, "detail": detail}
