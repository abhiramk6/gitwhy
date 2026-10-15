#!/usr/bin/env python3
"""Convert locally cloned public GitHub repositories into the ingestion fixture layout.

    scripts/build_oss_fixture.py --src /root/oss-src --out /root/oss-fixture [--overlay fixtures/oss-overlay]

Read-only with respect to the clones: files are only read as data (never imported or executed).
Public GitHub metadata (issues, merged PRs) is fetched unauthenticated (60 req/h; ~16 calls used).
GitHub issue #N of <repo> is normalised to the ticket key <PREFIX>-N so the retrieval/planner
machinery that understands ticket keys works unchanged; each record keeps its real GitHub URL.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPOS = {  # clone dir -> (owner, ticket prefix, default branch)
    "flask": ("pallets", "FLASK", "main"),
    "werkzeug": ("pallets", "WERKZ", "main"),
    "jinja": ("pallets", "JINJA", "main"),
    "click": ("pallets", "CLICK", "main"),
    "markupsafe": ("pallets", "MSAFE", "main"),
    "itsdangerous": ("pallets", "ITSD", "main"),
    "requests": ("psf", "REQ", "main"),
    "urllib3": ("urllib3", "URLLB", "main"),
}
MAX_COMMITS = 300
MAX_PY = 150_000
MAX_DOC = 60_000
SKIP_DIRS = ("tests/", "test/", "docs/_", "examples/", "tox/", ".github/", "requirements/", "ci/", "scripts/")
FIX = re.compile(r"(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s+(?:[\w.-]+/[\w.-]+)?#(\d+)", re.I)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


def keep(rel: str, size: int) -> str | None:
    """'file' (python source), 'doc' or None."""
    low = rel.lower()
    if any(low.startswith(d) or f"/{d}" in f"/{low}" for d in SKIP_DIRS):
        return None
    if rel.endswith(".py"):
        return "file" if size <= MAX_PY and not rel.startswith(("setup.py", "docs/", "noxfile")) else None
    if rel.endswith((".rst", ".md")) and size <= MAX_DOC and (rel.startswith("docs/") or "/" not in rel):
        return None if rel.upper().startswith(("CHANGES", "CODE_OF", "LICENSE")) else "doc"
    return None


def changelog_chunks(repo: str, text: str, limit: int = 15) -> dict[str, str]:
    """Split CHANGES.rst into one doc per version (newest first)."""
    blocks = re.split(r"\n(?=Version [\d.]+[^\n]*\n[-=~]{3,}\n)", text)
    out = {}
    for blk in blocks:
        m = re.match(r"Version ([\d.]+)", blk)
        if m and len(out) < limit:
            out[f"changelog/Version-{m.group(1)}.md"] = f"{repo} changelog: Version {m.group(1)}\n\n{blk.strip()}"
    return out


def api(url: str) -> list[dict]:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "lore-intelligence-oss-demo"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--overlay", default=None)
    a = ap.parse_args()
    src, out = Path(a.src), Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "repos").mkdir(parents=True)
    (out / "history").mkdir()
    prs_all, tickets_all, counts = [], [], {"files": 0, "docs": 0, "commits": 0}

    for name, (owner, prefix, branch) in REPOS.items():
        clone = src / name
        base = out / "repos" / name
        copied: set[str] = set()
        for rel in git(clone, "ls-files").splitlines():
            p = clone / rel
            if not p.is_file() or p.is_symlink():
                continue
            kind = keep(rel, p.stat().st_size)
            if kind:
                try:
                    text = p.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                (base / rel).parent.mkdir(parents=True, exist_ok=True)
                (base / rel).write_text(text, encoding="utf-8")
                copied.add(rel)
                counts["files" if kind == "file" else "docs"] += 1
        for cand in ("CHANGES.rst", "CHANGES.md", "HISTORY.md", "HISTORY.rst"):
            if (clone / cand).is_file():
                for rel, body in changelog_chunks(name, (clone / cand).read_text(encoding="utf-8", errors="replace")).items():
                    (base / rel).parent.mkdir(parents=True, exist_ok=True)
                    (base / rel).write_text(body, encoding="utf-8")
                    counts["docs"] += 1

        # commit history (last MAX_COMMITS) with changed files
        raw = git(clone, "log", f"-n{MAX_COMMITS}", "--no-merges", "--name-only",
                  "--format=@@%H%x1f%an%x1f%as%x1f%s")
        commits, pr_files = [], {}
        for chunk in raw.split("@@")[1:]:
            head, *files = chunk.strip("\n").split("\n")
            sha, author, day, subject = head.split("\x1f", 3)
            fl = [f for f in files if f in copied]
            commits.append({"sha": sha, "repo": name, "author": author, "date": day, "message": subject, "files": fl})
            m = re.search(r"\(#(\d+)\)\s*$", subject)
            if m:
                pr_files[int(m.group(1))] = fl
        counts["commits"] += len(commits)
        (out / "history" / f"{name}.commits.json").write_text(json.dumps(commits, indent=1))

        # public GitHub metadata
        issues = api(f"https://api.github.com/repos/{owner}/{name}/issues?state=all&per_page=100&sort=updated")
        pulls = api(f"https://api.github.com/repos/{owner}/{name}/pulls?state=closed&per_page=100")
        time.sleep(0.5)
        issue_nums = set()
        for i in issues:
            if "pull_request" in i:
                continue
            issue_nums.add(i["number"])
            tickets_all.append({
                "key": f"{prefix}-{i['number']}", "summary": i["title"], "description": (i.get("body") or "")[:3000],
                "status": "Done" if i["state"] == "closed" else "Open", "type": "Issue",
                "labels": [l["name"] for l in i.get("labels", [])], "links": [],
                "assignee": (i.get("assignee") or {}).get("login"), "updated": i["updated_at"][:10],
                "url": i["html_url"], "repo": name})
        for p in pulls:
            if not p.get("merged_at"):
                continue
            body = p.get("body") or ""
            linked = sorted({f"{prefix}-{n}" for n in map(int, FIX.findall(body)) if n in issue_nums})
            prs_all.append({"repo": name, "number": p["number"], "title": p["title"], "body": body[:4000],
                            "author": p["user"]["login"], "merged_at": p["merged_at"][:10],
                            "files": pr_files.get(p["number"], []), "linked_tickets": linked, "adds_imports": []})
        print(f"{name}: {len(copied)} files, {len(commits)} commits, "
              f"{sum(1 for i in issues if 'pull_request' not in i)} issues, "
              f"{sum(1 for p in pulls if p.get('merged_at'))} merged PRs", file=sys.stderr)

    (out / "history/prs.json").write_text(json.dumps(prs_all, indent=1))
    (out / "history/jira.json").write_text(json.dumps(tickets_all, indent=1))
    manifest = {
        "organization": {"slug": "oss-pallets", "name": "Open-source Python web stack (public GitHub)",
                         "is_synthetic": False},
        "repos": list(REPOS),
        "repo_urls": {n: f"https://github.com/{o}/{n}" for n, (o, _, _) in REPOS.items()},
        "default_branch": {n: b for n, (_, _, b) in REPOS.items()},
        "overlay_label": "acme-handbook",
        "ticket_prefixes": {n: p for n, (_, p, _) in REPOS.items()},
        "reference_date": max(c["date"] for n in REPOS for c in json.loads(
            (out / "history" / f"{n}.commits.json").read_text())),
        "counts": {**counts, "pull_requests": len(prs_all), "issues": len(tickets_all)},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    if a.overlay:
        shutil.copytree(a.overlay, out / "overlay")
    print(json.dumps(manifest["counts"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
