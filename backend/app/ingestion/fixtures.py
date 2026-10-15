"""Idempotent ingestion of the synthetic org fixture into source_records.

Each record is keyed by (organization, source_type, source_id). Re-running never grows the table:
unchanged content is skipped (hash match); changed content updates in place and is counted as `changed`.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import psycopg

HOST = "https://github.example/northwind"
SOURCE = "fixtures"


@dataclass
class Rec:
    source_type: str
    source_id: str
    repo: str | None
    title: str
    body: str
    payload: dict
    url: str | None
    when: str | None = None  # ISO date, used for incremental cursoring


@dataclass
class Stats:
    seen: int = 0
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    by_type: dict[str, int] = field(default_factory=dict)


def _h(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def _urls(manifest: dict) -> tuple[dict[str, str], dict[str, str]]:
    """Optional per-repo URL base / default branch (real GitHub sources); synthetic fixtures use HOST/main."""
    return manifest.get("repo_urls", {}), manifest.get("default_branch", {})


_UNDERLINE = re.compile(r"^([=\-~^#*+])\1{2,}\s*$")
_BAD_FIRST = ("from ", "import ", "#!", '"""', "'''", ".. ")


def _title(rel: str, text: str) -> str:
    """Readable record title: reST heading, markdown heading, else the path for code without a docstring."""
    lines = text.splitlines()
    if rel.endswith(".rst"):
        for i in range(len(lines) - 1):
            if lines[i].strip() and not lines[i].startswith((".. ", " ")) and _UNDERLINE.match(lines[i + 1]):
                return lines[i].strip()
    first = lines[0].lstrip("# ").strip() if lines else ""
    return rel if (not first or first.startswith(_BAD_FIRST)) else first


def _kind(rel: str) -> str:
    if "/adr/" in f"/{rel}":
        return "adr"
    return "file" if rel.endswith(".py") else "doc"


def iter_records(root: Path) -> Iterator[Rec]:
    manifest = json.loads((root / "manifest.json").read_text())
    urls, branches = _urls(manifest)
    for repo in manifest["repos"]:
        base = root / "repos" / repo
        rurl = urls.get(repo, f"{HOST}/{repo}")
        branch = branches.get(repo, "main")
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(base).as_posix()
            text = p.read_text()
            stype = _kind(rel)
            yield Rec(stype, f"{repo}:{rel}", repo, _title(rel, text), text, {"path": rel},
                      f"{rurl}/blob/{branch}/{rel}")
        for c in json.loads((root / "history" / f"{repo}.commits.json").read_text()):
            yield Rec("github_commit", c["sha"], repo, c["message"], c["message"], c,
                      f"{rurl}/commit/{c['sha']}", c["date"])
    for pr in json.loads((root / "history/prs.json").read_text()):
        yield Rec("github_pr", f"{pr['repo']}#{pr['number']}", pr["repo"], pr["title"], pr["body"], pr,
                  f"{urls.get(pr['repo'], f'{HOST}/' + pr['repo'])}/pull/{pr['number']}", pr["merged_at"])
    for t in json.loads((root / "history/jira.json").read_text()):
        yield Rec("jira_issue", t["key"], None, t["summary"], t["description"], t,
                  t.get("url") or f"https://jira.example/browse/{t['key']}", t["updated"])
    # Team knowledge layered on top of the ingested sources (curated decisions, runbooks). Not tied to a repo.
    overlay = root / "overlay"
    if overlay.is_dir():
        label = manifest.get("overlay_label", "handbook")
        for p in sorted(overlay.rglob("*.md")):
            rel = p.relative_to(overlay).as_posix()
            text = p.read_text()
            yield Rec(_kind(rel) if _kind(rel) == "adr" else "doc", f"{label}:{rel}", None, _title(rel, text), text,
                      {"path": rel, "overlay": True}, f"overlay://{label}/{rel}")


def ingest(conn: psycopg.Connection, root: Path, mode: str = "backfill") -> tuple[int, Stats]:
    assert mode in ("backfill", "incremental")
    manifest = json.loads((root / "manifest.json").read_text())
    org = manifest["organization"]
    urls, _ = _urls(manifest)
    org_id = conn.execute(
        "INSERT INTO organizations (slug, name, is_synthetic) VALUES (%s,%s,%s) "
        "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        (org["slug"], org["name"], org["is_synthetic"])).fetchone()["id"]
    repo_ids = {}
    for r in manifest["repos"]:
        repo_ids[r] = conn.execute(
            "INSERT INTO repositories (organization_id, name, url, language) VALUES (%s,%s,%s,'python') "
            "ON CONFLICT (organization_id, name) DO UPDATE SET url = EXCLUDED.url RETURNING id",
            (org_id, r, urls.get(r, f"{HOST}/{r}"))).fetchone()["id"]

    cur = conn.execute("SELECT cursor FROM ingestion_cursors WHERE organization_id=%s AND source=%s",
                       (org_id, SOURCE)).fetchone()
    cursor = cur["cursor"] if (cur and mode == "incremental") else None
    run_id = conn.execute(
        "INSERT INTO ingestion_runs (organization_id, source, mode) VALUES (%s,%s,%s) RETURNING id",
        (org_id, SOURCE, mode)).fetchone()["id"]
    st = Stats()
    newest = cursor or ""
    try:
        for rec in iter_records(root):
            if cursor and rec.when and rec.when <= cursor:
                continue  # already ingested in an earlier run
            st.seen += 1
            st.by_type[rec.source_type] = st.by_type.get(rec.source_type, 0) + 1
            if rec.when and rec.when > newest:
                newest = rec.when
            h = _h(rec.title, rec.body, json.dumps(rec.payload, sort_keys=True))
            row = conn.execute(
                "INSERT INTO source_records (organization_id, repository_id, source_type, source_id, source_url,"
                " title, body, payload, content_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s) "
                "ON CONFLICT (organization_id, source_type, source_id) DO UPDATE SET "
                " title=EXCLUDED.title, body=EXCLUDED.body, payload=EXCLUDED.payload, "
                " content_hash=EXCLUDED.content_hash, source_url=EXCLUDED.source_url, "
                " updated_at=now(), observed_at=now() "
                "WHERE source_records.content_hash <> EXCLUDED.content_hash "
                "RETURNING (xmax = 0) AS inserted",
                (org_id, repo_ids.get(rec.repo), rec.source_type, rec.source_id, rec.url, rec.title,
                 rec.body, json.dumps(rec.payload), h)).fetchone()
            if row is None:
                st.unchanged += 1
            elif row["inserted"]:
                st.new += 1
            else:
                st.changed += 1
        if newest:
            conn.execute(
                "INSERT INTO ingestion_cursors (organization_id, source, cursor) VALUES (%s,%s,%s) "
                "ON CONFLICT (organization_id, source) DO UPDATE SET cursor=EXCLUDED.cursor, updated_at=now()",
                (org_id, SOURCE, newest))
        conn.execute(
            "UPDATE ingestion_runs SET status='succeeded', finished_at=now(), records_seen=%s, records_new=%s,"
            " records_changed=%s WHERE id=%s", (st.seen, st.new, st.changed, run_id))
    except Exception as exc:
        conn.rollback()
        conn.execute("INSERT INTO ingestion_runs (organization_id, source, mode, status, finished_at, error) "
                     "VALUES (%s,%s,%s,'failed',now(),%s)", (org_id, SOURCE, mode, type(exc).__name__))
        conn.commit()
        raise
    return org_id, st
