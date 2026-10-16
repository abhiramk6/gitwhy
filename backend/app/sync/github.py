"""GitHub connector: a token and a list of repositories -> the fixture folder format that `ingestion.fixtures.ingest` reads.

Everything is read-only against GitHub: shallow clones (code, docs, commit history), pull requests with changed files, issues,
and the human discussion (review comments, PR conversation, review summaries, issue comments). Bounded by settings
(`sync_max_*`); every drop is counted in the manifest, never silent. The token is passed to git through a temporary
GIT_ASKPASS helper, never on a command line.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

API = "https://api.github.com"
MAX_FILE = 150_000
CODE_EXT = (".py",)
TEXT_CODE_EXT = (".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".kt", ".rb", ".rs", ".cs", ".php", ".swift", ".c", ".cc", ".cpp", ".h",
                ".hpp", ".sql", ".sh", ".scala", ".vue")
DOC_EXT = (".md", ".rst", ".txt", ".adoc")
SKIP_DIRS = ("node_modules/", "vendor/", "dist/", "build/", ".github/", "third_party/", "__pycache__/", ".venv/", "venv/", "migrations/versions/")
FIX = re.compile(r"(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s+(?:[\w.-]+/[\w.-]+)?#(\d+)", re.I)
Progress = Callable[[str, dict], None]


class GitHubError(RuntimeError):
    pass


def _get(url: str, token: str):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
                                               "User-Agent": "gitwhy", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404, 429):
            raise GitHubError({401: "GitHub rejected the token", 403: "GitHub refused (rate limit or missing permission)",
                               404: "not found, or the token cannot see it", 429: "GitHub rate limit"}[e.code]) from None
        raise GitHubError(f"GitHub HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise GitHubError(f"could not reach GitHub: {e.reason}") from None


def _pages(url: str, token: str, limit: int):
    n, page = 0, 1
    while n < limit:
        batch = _get(f"{url}{'&' if '?' in url else '?'}per_page=100&page={page}", token)
        for x in batch:
            yield x
            n += 1
            if n >= limit:
                return
        if len(batch) < 100:
            return
        page += 1


PATCH_PER_FILE = 6_000
PATCH_PER_PR = 30_000


def pr_patches(full: str, number: int, token: str) -> tuple[dict, list[str], int]:
    """The unified-diff hunks GitHub returns for a PR's changed files, bounded per file and per PR.
    Returns (patches by file, every changed file name, how many patches were cut short or left out)."""
    patches, names, cut, used = {}, [], 0, 0
    for f in _pages(f"{API}/repos/{full}/pulls/{number}/files", token, 100):
        names.append(f["filename"])
        patch = f.get("patch")
        if not patch:
            continue  # binary, renamed without change, or too large for GitHub to inline
        if len(patch) > PATCH_PER_FILE:
            patch, cut = patch[:PATCH_PER_FILE].rsplit("\n", 1)[0], cut + 1
        if used + len(patch) > PATCH_PER_PR:
            cut += 1
            continue
        patches[f["filename"]] = patch
        used += len(patch)
    return patches, names, cut


def whoami(token: str) -> dict:
    u = _get(f"{API}/user", token)
    return {"login": u["login"], "name": u.get("name")}


def list_repos(token: str, owner: str = "") -> list[dict]:
    """Repositories the token can read: for an owner (organization or user) when given, else the token's own."""
    if owner:
        try:
            rows = list(_pages(f"{API}/orgs/{owner}/repos?type=all&sort=pushed", token, 100))
        except GitHubError:
            rows = list(_pages(f"{API}/users/{owner}/repos?sort=pushed", token, 100))
    else:
        rows = list(_pages(f"{API}/user/repos?sort=pushed&affiliation=owner,collaborator,organization_member", token, 100))
    return [{"full_name": r["full_name"], "private": r["private"], "language": r.get("language"), "pushed_at": (r.get("pushed_at") or "")[:10],
             "description": r.get("description") or "", "archived": r.get("archived", False)} for r in rows if not r.get("fork")]


def _git(args: list[str], env: dict, cwd: Path | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    if r.returncode != 0:
        raise GitHubError("git failed: " + re.sub(r"https://[^@\s]*@", "https://", r.stderr.strip())[-300:])
    return r.stdout


def _clone(full: str, token: str, dest: Path, depth: int) -> dict:
    with tempfile.TemporaryDirectory() as td:
        ask = Path(td) / "askpass.sh"
        ask.write_text("#!/bin/sh\necho \"$GITWHY_GIT_TOKEN\"\n")
        ask.chmod(stat.S_IRWXU)
        env = {**os.environ, "GIT_ASKPASS": str(ask), "GITWHY_GIT_TOKEN": token, "GIT_TERMINAL_PROMPT": "0", "GIT_USERNAME": "x-access-token"}
        _git(["-c", "credential.username=x-access-token", "clone", "--quiet", f"--depth={depth}", "--no-tags",
              f"https://github.com/{full}.git", str(dest)], env)
    return {}


def _ticket_regex(project_keys: list[str]):
    return re.compile(r"\b(" + "|".join(re.escape(k) for k in project_keys) + r")-(\d+)\b") if project_keys else None


def build_fixture(root: Path, slug: str, name: str, repos: list[str], token: str, limits: dict, jira_keys: list[str],
                  progress: Progress = lambda *_: None) -> dict:
    """Write <root>/{manifest.json, repos/, history/} for `repos` ('owner/name'). Returns counts and drops."""
    if root.exists():
        shutil.rmtree(root)
    (root / "repos").mkdir(parents=True)
    (root / "history").mkdir()
    dropped: dict[str, int] = {}
    drop = lambda why: dropped.__setitem__(why, dropped.get(why, 0) + 1)  # noqa: E731
    prs_all, tickets, disc, counts = [], [], [], {"files": 0, "docs": 0, "commits": 0, "pull_requests": 0, "issues": 0, "comments": 0}
    repo_urls, branches, names = {}, {}, []
    tkt = _ticket_regex(jira_keys)
    for ri, full in enumerate(repos, 1):
        owner, rname = full.split("/", 1)
        names.append(rname)
        meta = _get(f"{API}/repos/{full}", token)
        repo_urls[rname], branches[rname] = meta["html_url"], meta.get("default_branch", "main")
        progress("github", {"detail": f"cloning {full} ({ri} of {len(repos)})"})
        clone = root / "_clone" / rname
        _clone(full, token, clone, int(limits["commits"]))
        base = root / "repos" / rname
        copied: set[str] = set()
        env = {**os.environ}
        for rel in _git(["ls-files"], env, clone).splitlines():
            p = clone / rel
            low = rel.lower()
            if not p.is_file() or p.is_symlink():
                continue
            if any(low.startswith(d) or f"/{d}" in f"/{low}" for d in SKIP_DIRS) or "/test" in f"/{low}" or low.startswith(("test/", "tests/")):
                drop("excluded_directory"); continue
            ext = os.path.splitext(low)[1]
            if ext not in CODE_EXT + TEXT_CODE_EXT + DOC_EXT or os.path.basename(low).startswith(("license", "licence", "changes", "code_of")):
                continue
            if p.stat().st_size > MAX_FILE:
                drop("file_too_large"); continue
            try:
                text = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                drop("not_utf8"); continue
            (base / rel).parent.mkdir(parents=True, exist_ok=True)
            # non-Python source is stored as searchable text with a .txt suffix on its record id so it is classed as a document
            out = rel if ext in CODE_EXT + DOC_EXT else rel + ".txt"
            (base / out).parent.mkdir(parents=True, exist_ok=True)
            (base / out).write_text(text, encoding="utf-8")
            copied.add(rel)
            counts["files" if ext in CODE_EXT else "docs"] += 1
        raw = _git(["log", f"-n{int(limits['commits'])}", "--no-merges", "--name-only", "--format=@@%H%x1f%an%x1f%as%x1f%s"], env, clone)
        commits, pr_files = [], {}
        for chunk in raw.split("@@")[1:]:
            head, *files = chunk.strip("\n").split("\n")
            sha, author, day, subject = head.split("\x1f", 3)
            fl = [f for f in files if f in copied]
            commits.append({"sha": sha, "repo": rname, "author": author, "date": day, "message": subject, "files": fl})
            m = re.search(r"\(#(\d+)\)\s*$", subject)
            if m:
                pr_files[int(m.group(1))] = fl
        counts["commits"] += len(commits)
        (root / "history" / f"{rname}.commits.json").write_text(json.dumps(commits))
        progress("github", {"detail": f"reading pull requests and issues of {full}"})
        prefix = re.sub(r"[^A-Z0-9]", "", rname.upper())[:6] or "GH"
        issue_nums = set()
        issues_before = counts["issues"]
        for i in _pages(f"{API}/repos/{full}/issues?state=all&sort=updated", token, int(limits["issues"]) * 4):
            if "pull_request" in i:
                continue
            if counts["issues"] - issues_before >= int(limits["issues"]):
                break
            issue_nums.add(i["number"])
            tickets.append({"key": f"{prefix}-{i['number']}", "summary": i["title"], "description": i.get("body") or "",
                            "status": "Done" if i["state"] == "closed" else "Open", "type": "Issue",
                            "labels": [l["name"] for l in i.get("labels", [])], "links": [], "assignee": (i.get("assignee") or {}).get("login"),
                            "updated": i["updated_at"][:10], "url": i["html_url"], "repo": rname})
            counts["issues"] += 1
        merged = []
        for p in _pages(f"{API}/repos/{full}/pulls?state=closed&sort=updated&direction=desc", token, int(limits["prs"]) * 5):
            if len(merged) >= int(limits["prs"]):
                break
            if not p.get("merged_at"):
                continue
            body = p.get("body") or ""
            linked = sorted({f"{prefix}-{n}" for n in map(int, FIX.findall(body)) if n in issue_nums})
            if tkt:
                linked += [f"{k}-{n}" for k, n in tkt.findall(f"{p['title']} {body} {p['head']['ref']}")]
            files = pr_files.get(p["number"])
            try:
                patches, names, cut = pr_patches(full, p["number"], token)
            except GitHubError:
                patches, names, cut = {}, [], 0
                drop("pr_diff_unavailable")
            if files is None:
                files = [n for n in names if n in copied]
            if cut:
                drop("pr_diff_truncated")
            prs_all.append({"repo": rname, "number": p["number"], "title": p["title"], "body": body, "author": (p.get("user") or {}).get("login"),
                            "merged_at": p["merged_at"][:10], "files": files, "linked_tickets": sorted(set(linked)), "adds_imports": [],
                            "reviewers": [], "patches": patches})
            merged.append(p["number"])
            counts["pull_requests"] += 1
        progress("github", {"detail": f"reading review discussion of {full}"})
        for num in merged[: int(limits["threads"])]:
            rows = []
            for c in _pages(f"{API}/repos/{full}/pulls/{num}/comments", token, 100):
                rows.append(("review_comment", c, c.get("path")))
            for r in _pages(f"{API}/repos/{full}/pulls/{num}/reviews", token, 50):
                if (r.get("body") or "").strip():
                    rows.append(("review", r, None))
            for c in _pages(f"{API}/repos/{full}/issues/{num}/comments", token, 100):
                rows.append(("pr_comment", c, None))
            for k, c, path in rows:
                disc.append({"repo": rname, "number": num, "kind": k, "id": c["id"], "author": (c.get("user") or {}).get("login"),
                             "date": (c.get("created_at") or c.get("submitted_at") or "")[:10], "body": c.get("body") or "",
                             "path": path, "url": c.get("html_url"), "in_reply_to": c.get("in_reply_to_id")})
        counts["comments"] = len(disc)
        shutil.rmtree(clone, ignore_errors=True)
    shutil.rmtree(root / "_clone", ignore_errors=True)
    (root / "history" / "prs.json").write_text(json.dumps(prs_all))
    (root / "history" / "jira.json").write_text(json.dumps(tickets))
    (root / "history" / "discussion.json").write_text(json.dumps(disc))
    manifest = {"organization": {"slug": slug, "name": name, "is_synthetic": False}, "repos": names, "repo_urls": repo_urls,
                "default_branch": branches, "counts": counts, "dropped": dropped,
                "limits": {k: limits[k] for k in ("commits", "prs", "issues", "threads")}}
    (root / "manifest.json").write_text(json.dumps(manifest))
    return {"counts": counts, "dropped": dropped}
