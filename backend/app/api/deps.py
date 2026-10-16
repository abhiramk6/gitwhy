import hmac
import time
from collections import defaultdict, deque
from typing import Iterator

import psycopg
from fastapi import Depends, Header, HTTPException, Request

from .. import auth
from ..config import Settings, get_settings
from ..db import connect
from ..models.provider import Provider, make_provider


_HITS: dict[str, deque] = defaultdict(deque)


def rate_limit(key: str, limit: int, window_s: int) -> None:
    """In-memory sliding window (one process). Raises 429 when `key` has used `limit` calls in the last `window_s` seconds."""
    now, q = time.monotonic(), _HITS[key]
    while q and now - q[0] > window_s:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "too many requests; wait a little and try again")
    q.append(now)


def reset_limits() -> None:
    _HITS.clear()


def ip_limit(request: Request, name: str, limit: int = 10, window_s: int = 600) -> None:
    rate_limit(f"{name}:{request.client.host if request.client else '?'}", limit, window_s)


def settings_dep() -> Settings:
    return get_settings()


def get_conn() -> Iterator[psycopg.Connection]:
    with connect() as conn:  # commits on clean exit, rolls back on exception
        yield conn


def get_provider(settings: Settings = Depends(settings_dep)) -> Provider:
    return make_provider(settings)


def _bearer(authorization: str | None) -> str | None:
    return authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None


def optional_user_id(authorization: str | None = Header(default=None)) -> int | None:
    return auth.read_token(_bearer(authorization))


def require_user(uid: int | None = Depends(optional_user_id)) -> int:
    if uid is None:
        raise HTTPException(401, "sign in required")
    return uid


def get_org_id(conn: psycopg.Connection = Depends(get_conn), settings: Settings = Depends(settings_dep),
               uid: int | None = Depends(optional_user_id), x_org: str | None = Header(default=None)) -> int:
    if settings.auth_required:  # multi-organization mode: the signed-in user's organization, checked for membership
        if uid is None:
            raise HTTPException(401, "sign in required")
        if x_org:
            row = conn.execute("SELECT o.id FROM organizations o JOIN org_members m ON m.organization_id=o.id "
                               "WHERE m.user_id=%s AND o.slug=%s", (uid, x_org)).fetchone()
        else:
            row = conn.execute("SELECT o.id FROM organizations o JOIN org_members m ON m.organization_id=o.id "
                               "WHERE m.user_id=%s ORDER BY o.id LIMIT 1", (uid,)).fetchone()
        if not row:
            raise HTTPException(403, "you do not belong to this organization")
        return row["id"]
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
    bearer = _bearer(authorization)
    if settings.auth_required:  # a signed-in member may write; membership of the org is checked by get_org_id
        uid = auth.read_token(bearer)
        if uid is None:
            raise HTTPException(401, "sign in required")
        rate_limit(f"llm:{uid}", settings.llm_calls_per_hour, 3600)  # every write endpoint spends model quota
        return
    _check_token(x_demo_token or bearer, settings)
