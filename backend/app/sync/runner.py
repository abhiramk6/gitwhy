"""Organization sync: GitHub -> (Jira) -> knowledge graph -> (embeddings), as a background job with visible stages.

The job row (`sync_jobs.stages`) is what the onboarding page polls. One job per organization at a time. A failed stage is
recorded with its reason and the job stops there (no hidden retries); stages that were not configured are marked skipped.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import threading
import traceback
from pathlib import Path

from ..auth import secrets_dir
from ..config import get_settings
from ..db import connect
from ..ingestion.fixtures import ingest
from ..ingestion import jira as jira_mod
from ..knowledge.build_graph import build
from ..models.provider import make_provider
from ..retrieval.embed import embed_org
from . import github

STAGES = [("github", "Reading GitHub"), ("jira", "Reading Jira"), ("graph", "Connecting the dots"), ("index", "Building the search index")]


def secret_path(slug: str) -> Path:
    return secrets_dir() / f"{slug}.json"


def save_secrets(slug: str, **kv) -> None:
    p = secret_path(slug)
    cur = json.loads(p.read_text()) if p.exists() else {}
    cur.update({k: v for k, v in kv.items() if v})
    p.write_text(json.dumps(cur))
    try:
        p.chmod(0o600)
    except OSError:  # object-storage mounts (Cloud Run) have no file modes; access is the bucket's IAM
        pass


def load_secrets(slug: str) -> dict:
    p = secret_path(slug)
    return json.loads(p.read_text()) if p.exists() else {}


def _set(job_id: int, key: str, state: str, detail: str = "") -> None:
    with connect() as c:
        row = c.execute("SELECT stages FROM sync_jobs WHERE id=%s", (job_id,)).fetchone()
        stages = row["stages"]
        for s in stages:
            if s["key"] == key:
                s["state"], s["detail"] = state, detail
        c.execute("UPDATE sync_jobs SET stages=%s::jsonb WHERE id=%s", (json.dumps(stages), job_id))


def latest_job(conn, org_id: int) -> dict | None:
    return conn.execute("SELECT id, status, stages, error, started_at, finished_at FROM sync_jobs WHERE organization_id=%s "
                        "ORDER BY id DESC LIMIT 1", (org_id,)).fetchone()


def start_sync(org_id: int, run=None) -> dict:
    """Create a job (or return the running one) and run it in a background thread. `run` is injectable for tests."""
    with connect() as c:
        cur = c.execute("SELECT id, status FROM sync_jobs WHERE organization_id=%s AND status IN ('queued','running') ORDER BY id DESC LIMIT 1",
                        (org_id,)).fetchone()
        if cur:
            return {"id": cur["id"], "already_running": True}
        stages = [{"key": k, "label": l, "state": "pending", "detail": ""} for k, l in STAGES]
        jid = c.execute("INSERT INTO sync_jobs (organization_id, status, stages) VALUES (%s,'running',%s::jsonb) RETURNING id",
                        (org_id, json.dumps(stages))).fetchone()["id"]
        c.execute("UPDATE organizations SET status='syncing' WHERE id=%s", (org_id,))
    threading.Thread(target=run or _run, args=(jid, org_id), daemon=True, name=f"sync-{org_id}").start()
    return {"id": jid, "already_running": False}


def _run(job_id: int, org_id: int) -> None:
    s = get_settings()
    work = Path(tempfile.mkdtemp(prefix="gitwhy-sync-"))
    failed = None
    try:
        with connect() as c:
            org = c.execute("SELECT slug, name FROM organizations WHERE id=%s", (org_id,)).fetchone()
            conns = c.execute("SELECT github, jira FROM org_connections WHERE organization_id=%s", (org_id,)).fetchone() or {"github": {}, "jira": {}}
        sec = load_secrets(org["slug"])
        gh, jr = conns["github"] or {}, conns["jira"] or {}
        jira_keys = jr.get("projects", []) if jr.get("site") else []
        provider = make_provider(s)

        # 1. GitHub
        repos = gh.get("repos", [])
        if repos and sec.get("github_token"):
            _set(job_id, "github", "running", f"{len(repos)} repositories")
            limits = {"commits": s.sync_max_commits, "prs": s.sync_max_prs, "issues": s.sync_max_issues, "threads": s.sync_max_threads}
            res = github.build_fixture(work / "fx", org["slug"], org["name"], repos, sec["github_token"], limits, jira_keys,
                                       progress=lambda st, d: _set(job_id, "github", "running", d.get("detail", "")))
            with connect() as c:
                _, st = ingest(c, work / "fx", "backfill")
            cn = res["counts"]
            _set(job_id, "github", "done", f"{len(repos)} repos, {cn['files'] + cn['docs']} files, {cn['commits']} commits, "
                 f"{cn['pull_requests']} pull requests, {cn['issues']} issues, {cn['comments']} review comments")
        else:
            _set(job_id, "github", "skipped", "no repositories connected")

        # 2. Jira
        if jr.get("site") and jr.get("projects") and sec.get("jira_token"):
            _set(job_id, "jira", "running", ", ".join(jr["projects"]))
            client = jira_mod.Jira(jr["site"], jr["email"], sec["jira_token"])
            total = 0
            for proj in jr["projects"]:
                with connect() as c:
                    _, st = jira_mod.sync(c, client, proj, org["slug"], org["name"], "backfill")
                total += st.seen
            _set(job_id, "jira", "done", f"{total} tickets from {len(jr['projects'])} project(s)")
        else:
            _set(job_id, "jira", "skipped", "Jira not connected")

        # 3. Graph (model judgments are skipped and reported when no model is available)
        _set(job_id, "graph", "running", "decisions, ownership, review guidance")
        with connect() as c:
            g = build(c, org_id, provider)
        note = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in g.by_fact_type.items()) or "structure only"
        skipped = [k for k, v in (g.judgments or {}).items() if isinstance(v, str) and v.startswith("skipped")]
        _set(job_id, "graph", "done", f"{g.entities} entities, {g.edges} links; remembered: {note}" + (f"; skipped without a model: {', '.join(skipped)}" if skipped else ""))

        with connect() as c:
            c.execute("UPDATE organizations SET status='ready' WHERE id=%s", (org_id,))  # usable now (keyword search) while the index builds

        # 4. Embeddings (optional: slow on free-tier quotas)
        if s.sync_embed and provider.semantic_embeddings:
            _set(job_id, "index", "running", "embedding chunks")
            with connect() as c:
                r = embed_org(c, org_id, provider)
            _set(job_id, "index", "done" if not r.get("pending") else "failed",
                 f"{r['embedded']} chunks embedded" + (f", {r['pending']} pending ({r['stopped']})" if r.get("pending") else ""))
        else:
            _set(job_id, "index", "skipped", "keyword search until the search index job runs")
    except Exception as exc:  # recorded for the user, never retried in a loop
        traceback.print_exc()
        failed = f"{type(exc).__name__}: {str(exc)[:300]}"
        with connect() as c:
            row = c.execute("SELECT stages FROM sync_jobs WHERE id=%s", (job_id,)).fetchone()
            stages = row["stages"]
            for st in stages:
                if st["state"] == "running":
                    st["state"], st["detail"] = "failed", failed
            c.execute("UPDATE sync_jobs SET stages=%s::jsonb WHERE id=%s", (json.dumps(stages), job_id))
            c.execute("UPDATE organizations SET status='onboarding' WHERE id=%s AND status='syncing'", (org_id,))
    finally:
        shutil.rmtree(work, ignore_errors=True)
        with connect() as c:
            c.execute("UPDATE sync_jobs SET status=%s, error=%s, finished_at=now() WHERE id=%s",
                      ("failed" if failed else "succeeded", failed, job_id))
