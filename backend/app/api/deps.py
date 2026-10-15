import hmac
from typing import Iterator

import psycopg
from fastapi import Depends, Header, HTTPException

from ..config import Settings, get_settings
from ..db import connect
from ..models.provider import Provider, make_provider


def settings_dep() -> Settings:
    return get_settings()


def get_conn() -> Iterator[psycopg.Connection]:
    with connect() as conn:  # commits on clean exit, rolls back on exception
        yield conn


def get_provider(settings: Settings = Depends(settings_dep)) -> Provider:
    return make_provider(settings)


def get_org_id(conn: psycopg.Connection = Depends(get_conn), settings: Settings = Depends(settings_dep)) -> int:
    row = conn.execute("SELECT id FROM organizations WHERE slug=%s", (settings.org_slug,)).fetchone()
    if not row:
        raise HTTPException(404, f"organization '{settings.org_slug}' not found; run ingestion first")
    return row["id"]


def _check_token(supplied: str | None, settings: Settings) -> None:
    if not settings.demo_token:
        if settings.environment == "local":
            return
        raise HTTPException(503, "write access disabled: no demo token configured")
    if not supplied or not hmac.compare_digest(supplied, settings.demo_token):
        raise HTTPException(401, "missing or invalid token")


def require_write(x_demo_token: str | None = Header(default=None),
                  authorization: str | None = Header(default=None),
                  settings: Settings = Depends(settings_dep)) -> None:
    bearer = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None
    _check_token(x_demo_token or bearer, settings)
