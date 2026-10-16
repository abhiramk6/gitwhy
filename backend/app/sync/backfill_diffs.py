"""Attach diffs to pull requests that were read before diffs were captured.  Read-only against GitHub, one call per PR.

    GH_TOKEN=... python -m app.sync.backfill_diffs <org-slug> [--limit N]

Only PRs whose source_url is a github.com pull URL and that carry no patches yet are touched; the record's content hash is
recomputed the same way ingestion does, so a later sync sees no spurious change.
"""
from __future__ import annotations

import json
import os
import re
import sys

from ..db import connect
from ..ingestion.fixtures import _h
from .github import GitHubError, pr_patches

URL = re.compile(r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)")


def main(argv: list[str]) -> int:
    slug = argv[0]
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 10_000
    token = os.environ["GH_TOKEN"]
    done = skipped = failed = 0
    with connect() as conn:
        org = conn.execute("SELECT id FROM organizations WHERE slug=%s", (slug,)).fetchone()["id"]
        rows = conn.execute("SELECT id, title, body, payload, source_url FROM source_records WHERE organization_id=%s AND "
                            "source_type='github_pr' AND NOT (payload ? 'patches') ORDER BY id", (org,)).fetchall()
        for r in rows[:limit]:
            m = URL.match(r["source_url"] or "")
            if not m:
                skipped += 1
                continue
            try:
                patches, _, cut = pr_patches(m.group(1), int(m.group(2)), token)
            except GitHubError as e:
                failed += 1
                print("fail", r["source_url"], e, file=sys.stderr)
                if "rate limit" in str(e) or "refused" in str(e):
                    break
                continue
            payload = {**r["payload"], "patches": patches}
            conn.execute("UPDATE source_records SET payload=%s::jsonb, content_hash=%s WHERE id=%s",
                         (json.dumps(payload), _h(r["title"], r["body"], json.dumps(payload, sort_keys=True)), r["id"]))
            conn.commit()
            done += 1
    print(json.dumps({"org": slug, "updated": done, "skipped": skipped, "failed": failed}))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
