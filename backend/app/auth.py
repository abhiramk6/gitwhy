"""Accounts: scrypt password hashes and HMAC-signed bearer tokens (no external dependencies).

Token = base64url(user_id.expiry).signature, signed with the session secret. The secret comes from GITWHY_SESSION_SECRET or a
file created once (mode 600) under the secrets directory, so tokens survive restarts without being stored in git.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from pathlib import Path

from .config import get_settings

TOKEN_TTL_S = 14 * 24 * 3600


def secrets_dir() -> Path:
    d = Path(get_settings().secrets_dir).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    try:
        d.chmod(0o700)
    except OSError:
        pass
    return d


def _secret() -> bytes:
    env = os.environ.get("GITWHY_SESSION_SECRET") or get_settings().session_secret
    if env:
        return env.encode()
    f = secrets_dir() / "session_secret"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
        f.chmod(0o600)
    return f.read_text().strip().encode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


def make_token(user_id: int, ttl: int = TOKEN_TTL_S) -> str:
    body = base64.urlsafe_b64encode(f"{user_id}.{int(time.time()) + ttl}".encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_token(token: str | None) -> int | None:
    """User id for a valid, unexpired token; otherwise None."""
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest(), sig):
        return None
    try:
        uid, exp = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode().split(".")
        return int(uid) if int(exp) > time.time() else None
    except Exception:
        return None


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:40] or "org"


EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
