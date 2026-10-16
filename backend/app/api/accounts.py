"""Sign-up, sign-in, organizations, connections and sync (the onboarding flow)."""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import auth
from ..config import Settings
from ..sync import github, runner
from ..seed_users import TEST_EMAIL
from .deps import get_conn, ip_limit, require_user, settings_dep

router = APIRouter(prefix="/api")


class Signup(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(default="", max_length=100)


class Login(BaseModel):
    email: str
    password: str


class NewOrg(BaseModel):
    name: str = Field(min_length=2, max_length=80)


class GithubTest(BaseModel):
    token: str = Field(min_length=10, max_length=300)
    owner: str = Field(default="", max_length=100)


class JiraTest(BaseModel):
    site: str = Field(max_length=200)
    email: str = Field(max_length=200)
    token: str = Field(min_length=6, max_length=400)


class Connections(BaseModel):
    github_token: str = Field(default="", max_length=300)
    repos: list[str] = Field(default_factory=list, max_length=25)
    jira_site: str = Field(default="", max_length=200)
    jira_email: str = Field(default="", max_length=200)
    jira_token: str = Field(default="", max_length=400)
    jira_projects: list[str] = Field(default_factory=list, max_length=10)


def _user_json(conn, uid: int) -> dict:
    u = conn.execute("SELECT id, email, name FROM users WHERE id=%s", (uid,)).fetchone()
    orgs = conn.execute("SELECT o.slug, o.name, o.status, o.is_synthetic, m.role FROM organizations o JOIN org_members m ON m.organization_id=o.id "
                        "WHERE m.user_id=%s ORDER BY o.id", (uid,)).fetchall()
    return {"user": u, "organizations": orgs}


@router.post("/auth/signup")
def signup(b: Signup, request: Request, conn: psycopg.Connection = Depends(get_conn)):
    ip_limit(request, "signup", 8, 3600)
    email = b.email.strip().lower()
    if not auth.EMAIL.match(email):
        raise HTTPException(422, "enter a valid email address")
    if conn.execute("SELECT 1 FROM users WHERE email=%s", (email,)).fetchone():
        raise HTTPException(409, "an account with this email already exists; sign in instead")
    uid = conn.execute("INSERT INTO users (email, name, password_hash) VALUES (%s,%s,%s) RETURNING id",
                       (email, b.name.strip(), auth.hash_password(b.password))).fetchone()["id"]
    return {"token": auth.make_token(uid), **_user_json(conn, uid)}


@router.post("/auth/login")
def login(b: Login, request: Request, conn: psycopg.Connection = Depends(get_conn)):
    ip_limit(request, "login", 20, 600)
    u = conn.execute("SELECT id, password_hash FROM users WHERE email=%s", (b.email.strip().lower(),)).fetchone()
    if not u or not auth.verify_password(b.password, u["password_hash"]):
        raise HTTPException(401, "wrong email or password")
    return {"token": auth.make_token(u["id"]), **_user_json(conn, u["id"])}


@router.get("/auth/me")
def me(uid: int = Depends(require_user), conn: psycopg.Connection = Depends(get_conn)):
    return _user_json(conn, uid)


def _no_demo(conn, uid: int) -> None:
    if (conn.execute("SELECT email FROM users WHERE id=%s", (uid,)).fetchone() or {}).get("email") == TEST_EMAIL:
        raise HTTPException(403, "the shared test account is read-only here; create your own account to connect your repositories")


def _member_org(conn, uid: int, slug: str) -> dict:
    row = conn.execute("SELECT o.id, o.slug, o.name, o.status FROM organizations o JOIN org_members m ON m.organization_id=o.id "
                       "WHERE m.user_id=%s AND o.slug=%s", (uid, slug)).fetchone()
    if not row:
        raise HTTPException(404, "organization not found")
    return row


@router.post("/orgs")
def create_org(b: NewOrg, uid: int = Depends(require_user), conn: psycopg.Connection = Depends(get_conn)):
    _no_demo(conn, uid)
    base = auth.slugify(b.name)
    slug, n = base, 1
    while conn.execute("SELECT 1 FROM organizations WHERE slug=%s", (slug,)).fetchone():
        n += 1
        slug = f"{base}-{n}"
    oid = conn.execute("INSERT INTO organizations (slug, name, is_synthetic, status) VALUES (%s,%s,false,'onboarding') RETURNING id",
                       (slug, b.name.strip())).fetchone()["id"]
    conn.execute("INSERT INTO org_members (user_id, organization_id, role) VALUES (%s,%s,'owner')", (uid, oid))
    return {"slug": slug, "name": b.name.strip(), "status": "onboarding"}


@router.post("/connections/github/test")
def test_github(b: GithubTest, uid: int = Depends(require_user), conn: psycopg.Connection = Depends(get_conn)):
    _no_demo(conn, uid)
    try:
        me_ = github.whoami(b.token)
        repos = github.list_repos(b.token, b.owner.strip())
    except github.GitHubError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "login": me_["login"], "repos": repos}


@router.post("/connections/jira/test")
def test_jira(b: JiraTest, uid: int = Depends(require_user), conn: psycopg.Connection = Depends(get_conn)):
    _no_demo(conn, uid)
    site = b.site.strip().rstrip("/")
    if not site.startswith("https://"):
        raise HTTPException(400, "the Jira site must start with https://")
    req = urllib.request.Request(f"{site}/rest/api/3/project/search?maxResults=50", headers={
        "Authorization": "Basic " + base64.b64encode(f"{b.email}:{b.token}".encode()).decode(), "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raise HTTPException(400, "Jira rejected the email or token" if e.code in (401, 403) else f"Jira answered HTTP {e.code}")
    except Exception:
        raise HTTPException(400, "could not reach that Jira site")
    return {"ok": True, "projects": [{"key": p["key"], "name": p["name"]} for p in data.get("values", [])]}


@router.put("/orgs/{slug}/connections")
def save_connections(slug: str, b: Connections, uid: int = Depends(require_user), conn: psycopg.Connection = Depends(get_conn)):
    _no_demo(conn, uid)
    org = _member_org(conn, uid, slug)
    gh = {"repos": [r for r in b.repos if r.count("/") == 1]}
    jr = {"site": b.jira_site.strip().rstrip("/"), "email": b.jira_email.strip(), "projects": b.jira_projects} if b.jira_site else {}
    conn.execute("INSERT INTO org_connections (organization_id, github, jira) VALUES (%s,%s::jsonb,%s::jsonb) "
                 "ON CONFLICT (organization_id) DO UPDATE SET github=EXCLUDED.github, jira=EXCLUDED.jira, updated_at=now()",
                 (org["id"], json.dumps(gh), json.dumps(jr)))
    runner.save_secrets(org["slug"], github_token=b.github_token, jira_token=b.jira_token)  # tokens never go into the database
    return {"saved": True, "repos": len(gh["repos"]), "jira_projects": len(jr.get("projects", []))}


@router.post("/orgs/{slug}/sync")
def start_sync(slug: str, uid: int = Depends(require_user), conn: psycopg.Connection = Depends(get_conn)):
    _no_demo(conn, uid)
    org = _member_org(conn, uid, slug)
    conn.commit()
    return runner.start_sync(org["id"])


@router.get("/orgs/{slug}/sync")
def sync_status(slug: str, uid: int = Depends(require_user), conn: psycopg.Connection = Depends(get_conn)):
    org = _member_org(conn, uid, slug)
    job = runner.latest_job(conn, org["id"])
    return {"organization": {"slug": org["slug"], "name": org["name"], "status": conn.execute(
        "SELECT status FROM organizations WHERE id=%s", (org["id"],)).fetchone()["status"]}, "job": job}
