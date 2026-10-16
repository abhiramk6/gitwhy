#!/usr/bin/env python3
"""Fetch the human discussion around PRs and issues from public GitHub: review comments (inline, with file/line context),
PR conversation comments, review summaries, and issue comments. Output: <fixture>/history/discussion.json
  [{"repo","number","kind": "review_comment|pr_comment|review|issue_comment","id","author","date","body","path","url","in_reply_to"}]
Resumable (appends per PR, skips PRs already fetched). Read-only against GitHub; token from GH_TOKEN (~/.config/lore/github.env).
No retry loops: a 403/429 stops the run and says when the limit resets.
Usage: fetch_pr_discussion.py --fixture /root/oss-fixture
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def get(url: str, token: str):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
                                               "User-Agent": "lore-intelligence-oss-demo", "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def pages(url: str, token: str):
    page = 1
    while True:
        batch = get(f"{url}{'&' if '?' in url else '?'}per_page=100&page={page}", token)
        yield from batch
        if len(batch) < 100:
            return
        page += 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", required=True)
    a = ap.parse_args()
    root = Path(a.fixture)
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        print("GH_TOKEN missing", file=sys.stderr)
        return 2
    manifest = json.loads((root / "manifest.json").read_text())
    urls = manifest["repo_urls"]
    prs = json.loads((root / "history/prs.json").read_text())
    issues = json.loads((root / "history/jira.json").read_text())
    out_path = root / "history/discussion.json"
    rows = json.loads(out_path.read_text()) if out_path.exists() else []
    done = {(r["repo"], r["number"]) for r in rows if r["kind"] == "_done"}
    todo = [(p["repo"], p["number"], "pr") for p in prs] + \
           [(t["repo"], int(t["key"].rsplit("-", 1)[1]), "issue") for t in issues]
    todo = [t for t in todo if (t[0], t[1]) not in done]
    print(f"{len(todo)} threads to fetch", file=sys.stderr)
    try:
        for n, (repo, num, kind) in enumerate(todo, 1):
            api = "https://api.github.com/repos/" + urls[repo].split("github.com/")[1]
            got = []
            try:
                if kind == "pr":
                    for c in pages(f"{api}/pulls/{num}/comments", token):
                        got.append(("review_comment", c, c.get("path")))
                    for r in pages(f"{api}/pulls/{num}/reviews", token):
                        if (r.get("body") or "").strip():
                            got.append(("review", r, None))
                for c in pages(f"{api}/issues/{num}/comments", token):
                    got.append(("pr_comment" if kind == "pr" else "issue_comment", c, None))
            except urllib.error.HTTPError as e:
                if e.code not in (404, 410):      # a deleted/transferred thread is skipped; limits and auth stop the run
                    raise
                print(f"skip {repo}#{num}: HTTP {e.code}", file=sys.stderr)
            for k, c, path in got:
                rows.append({"repo": repo, "number": num, "kind": k, "id": c["id"],
                             "author": (c.get("user") or {}).get("login"),
                             "date": (c.get("created_at") or c.get("submitted_at") or "")[:10],
                             "body": c.get("body") or "", "path": path, "url": c.get("html_url"),
                             "in_reply_to": c.get("in_reply_to_id")})
            rows.append({"repo": repo, "number": num, "kind": "_done"})
            if n % 25 == 0:
                out_path.write_text(json.dumps(rows))
                print(f"{n}/{len(todo)}", file=sys.stderr)
            time.sleep(0.2)
    except urllib.error.HTTPError as e:
        reset = e.headers.get("x-ratelimit-reset")
        print(f"STOPPED HTTP {e.code} at {todo[n-1] if 'n' in dir() else None}; limit resets at epoch {reset}", file=sys.stderr)
        out_path.write_text(json.dumps(rows))
        return 3
    out_path.write_text(json.dumps(rows))
    real = [r for r in rows if r["kind"] != "_done"]
    print(json.dumps({"threads": len(todo), "comments": len(real),
                      "by_kind": {k: sum(1 for r in real if r["kind"] == k) for k in {r["kind"] for r in real}}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
