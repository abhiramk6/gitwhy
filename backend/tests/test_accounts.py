"""Accounts, organization isolation and the onboarding sync job."""
import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth, db
from app.api.deps import get_conn, get_provider, settings_dep
from app.config import Settings
from app.main import app
from app.sync import github, runner
from tests.fake_model import ideal_provider

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "northwind"


@pytest.fixture()
def api(conn, tmp_path, monkeypatch):
    cfg = Settings(auth_required=True, environment="test", secrets_dir=str(tmp_path / "secrets"), session_secret="s3cret")
    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[get_provider] = lambda: ideal_provider()
    app.dependency_overrides[settings_dep] = lambda: cfg
    monkeypatch.setattr(auth, "get_settings", lambda: cfg)  # secrets dir + session secret for token helpers
    yield TestClient(app)
    app.dependency_overrides.clear()


def signup(c, email, pw="correct horse battery"):
    r = c.post("/api/auth/signup", json={"email": email, "password": pw, "name": "T"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_tokens_roundtrip_expire_and_reject_tampering(api):
    t = auth.make_token(7)
    assert auth.read_token(t) == 7
    assert auth.read_token(t[:-1] + ("0" if t[-1] != "0" else "1")) is None
    assert auth.read_token(auth.make_token(7, ttl=-1)) is None and auth.read_token("junk") is None


def test_signup_login_me_and_bad_credentials(api):
    h = signup(api, "a@example.com")
    assert api.get("/api/auth/me", headers=h).json()["user"]["email"] == "a@example.com"
    assert api.post("/api/auth/signup", json={"email": "A@example.com", "password": "another long pass"}).status_code == 409
    assert api.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong password!"}).status_code == 401
    assert api.post("/api/auth/login", json={"email": "a@example.com", "password": "correct horse battery"}).status_code == 200
    assert api.post("/api/auth/signup", json={"email": "not-an-email", "password": "long enough pw"}).status_code == 422
    assert api.get("/api/auth/me").status_code == 401


def test_organizations_are_isolated_between_users(api, conn):
    a, b = signup(api, "a@example.com"), signup(api, "b@example.com")
    org = api.post("/api/orgs", json={"name": "Acme Robotics"}, headers=a).json()
    assert org["slug"] == "acme-robotics" and org["status"] == "onboarding"
    assert api.post("/api/orgs", json={"name": "Acme Robotics"}, headers=a).json()["slug"] == "acme-robotics-2"
    assert api.get("/api/overview").status_code == 401                                   # data needs a sign-in
    assert api.get("/api/overview", headers={**a, "X-Org": "acme-robotics"}).status_code == 200
    assert api.get("/api/overview", headers={**b, "X-Org": "acme-robotics"}).status_code == 403   # not a member
    assert api.get("/api/orgs/acme-robotics/sync", headers=b).status_code == 404
    assert [o["slug"] for o in api.get("/api/auth/me", headers=a).json()["organizations"]] == ["acme-robotics", "acme-robotics-2"]


def test_connection_tokens_are_stored_outside_the_database(api, conn, tmp_path):
    h = signup(api, "a@example.com")
    slug = api.post("/api/orgs", json={"name": "Acme"}, headers=h).json()["slug"]
    r = api.put(f"/api/orgs/{slug}/connections", headers=h, json={"github_token": "ghp_secretvalue123", "repos": ["acme/web", "bad"],
                                                                  "jira_site": "https://acme.atlassian.net", "jira_email": "a@acme.com",
                                                                  "jira_token": "jira-secret-xyz", "jira_projects": ["WEB"]})
    assert r.json() == {"saved": True, "repos": 1, "jira_projects": 1}
    dump = json.dumps([dict(x) for x in conn.execute("SELECT github, jira FROM org_connections").fetchall()])
    assert "ghp_secretvalue123" not in dump and "jira-secret-xyz" not in dump and "acme/web" in dump
    secret_file = tmp_path / "secrets" / f"{slug}.json"
    assert json.loads(secret_file.read_text())["github_token"] == "ghp_secretvalue123" and oct(secret_file.stat().st_mode)[-3:] == "600"


def test_sync_job_runs_stages_and_makes_the_org_ready(api, conn, test_url, tmp_path, monkeypatch):
    h = signup(api, "a@example.com")
    slug = api.post("/api/orgs", json={"name": "Acme"}, headers=h).json()["slug"]
    api.put(f"/api/orgs/{slug}/connections", headers=h, json={"github_token": "ghp_x" * 4, "repos": ["acme/web"]})
    conn.commit()

    def fake_build(root, slug_, name, repos, token, limits, jira_keys, progress=lambda *_: None):
        assert repos == ["acme/web"] and token == "ghp_x" * 4
        progress("github", {"detail": "cloning acme/web"})
        shutil.copytree(FIX, root)
        m = json.loads((root / "manifest.json").read_text())
        m["organization"] = {"slug": slug_, "name": name, "is_synthetic": False}
        (root / "manifest.json").write_text(json.dumps(m))
        return {"counts": {"files": 1, "docs": 1, "commits": 1, "pull_requests": 1, "issues": 1, "comments": 1}, "dropped": {}}

    monkeypatch.setattr(github, "build_fixture", fake_build)
    monkeypatch.setattr(runner, "connect", lambda: db.connect(test_url))
    monkeypatch.setattr(runner, "make_provider", lambda s: ideal_provider(choose=lambda p: []))
    monkeypatch.setattr(runner, "get_settings", lambda: Settings(environment="test", secrets_dir=str(tmp_path / "secrets")))
    r = api.post(f"/api/orgs/{slug}/sync", headers=h).json()
    assert r["already_running"] is False
    for _ in range(100):
        job = api.get(f"/api/orgs/{slug}/sync", headers=h).json()
        if job["job"]["status"] != "running":
            break
        time.sleep(0.2)
    assert job["job"]["status"] == "succeeded", job
    states = {s["key"]: s["state"] for s in job["job"]["stages"]}
    assert states == {"github": "done", "jira": "skipped", "graph": "done", "index": "skipped"}
    assert job["organization"]["status"] == "ready"
    assert conn.execute("SELECT count(*) n FROM source_records sr JOIN organizations o ON o.id=sr.organization_id WHERE o.slug=%s", (slug,)).fetchone()["n"] > 50


def test_sync_failure_is_recorded_not_hidden(api, conn, test_url, tmp_path, monkeypatch):
    h = signup(api, "a@example.com")
    slug = api.post("/api/orgs", json={"name": "Acme"}, headers=h).json()["slug"]
    api.put(f"/api/orgs/{slug}/connections", headers=h, json={"github_token": "ghp_x" * 4, "repos": ["acme/web"]})
    conn.commit()

    def boom(*a, **k):
        raise github.GitHubError("GitHub rejected the token")
    monkeypatch.setattr(github, "build_fixture", boom)
    monkeypatch.setattr(runner, "connect", lambda: db.connect(test_url))
    monkeypatch.setattr(runner, "get_settings", lambda: Settings(environment="test", secrets_dir=str(tmp_path / "secrets")))
    api.post(f"/api/orgs/{slug}/sync", headers=h)
    for _ in range(100):
        job = api.get(f"/api/orgs/{slug}/sync", headers=h).json()
        if job["job"]["status"] != "running":
            break
        time.sleep(0.2)
    assert job["job"]["status"] == "failed" and "rejected the token" in job["job"]["error"]
    assert next(s for s in job["job"]["stages"] if s["key"] == "github")["state"] == "failed"
    assert job["organization"]["status"] == "onboarding"


def test_shared_test_account_is_read_only_and_limits_apply(api, conn):
    from app import seed_users
    from app.api import deps
    deps.reset_limits()
    conn.execute("INSERT INTO organizations (slug, name, is_synthetic) VALUES ('northwind','Northwind',true)")
    conn.commit()
    monkey_db = conn  # seed into the test database through the same connection
    uid = conn.execute("INSERT INTO users (email, name, password_hash) VALUES (%s,'d',%s) RETURNING id", (seed_users.TEST_EMAIL, auth.hash_password("x" * 10))).fetchone()["id"]
    h = {"Authorization": "Bearer " + auth.make_token(uid)}
    assert api.post("/api/orgs", json={"name": "Mine"}, headers=h).status_code == 403
    assert api.post("/api/connections/github/test", json={"token": "x" * 12}, headers=h).status_code == 403
    for i in range(20):
        api.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrongpassword"})
    assert api.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrongpassword"}).status_code == 429
    deps.reset_limits()
