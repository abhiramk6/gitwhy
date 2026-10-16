"""Read models for the UI: PR list, source health, the provenance of one record, and data-derived starter questions."""
from __future__ import annotations

import psycopg

from ..retrieval.embed import TIERS, coverage_text, tier_coverage


def pr_list(conn: psycopg.Connection, org: int, limit: int = 60) -> list[dict]:
    comments = {r["k"]: r["n"] for r in conn.execute(
        "SELECT (payload->>'repo') || '#' || (payload->>'number') AS k, count(*) n FROM source_records "
        "WHERE organization_id=%s AND source_type='github_comment' GROUP BY 1", (org,))}
    out = []
    for r in conn.execute("SELECT source_id, title, source_url, payload FROM source_records WHERE organization_id=%s AND "
                          "source_type='github_pr' ORDER BY payload->>'merged_at' DESC NULLS LAST, id DESC LIMIT %s",
                          (org, limit)):
        p = r["payload"]
        out.append({"repo": p.get("repo"), "number": p.get("number"), "id": r["source_id"], "title": r["title"],
                    "author": p.get("author"), "merged_at": p.get("merged_at"), "files": p.get("files", []),
                    "reviewers": p.get("reviewers", []), "comments": comments.get(r["source_id"], 0), "url": r["source_url"]})
    return out


def sources(conn: psycopg.Connection, org: int) -> dict:
    org_row = conn.execute("SELECT slug, name, is_synthetic FROM organizations WHERE id=%s", (org,)).fetchone()
    by_type = {r["source_type"]: {"count": r["n"], "latest": r["latest"]} for r in conn.execute(
        "SELECT source_type, count(*) n, max(coalesce(payload->>'merged_at', payload->>'date', payload->>'updated')) latest "
        "FROM source_records WHERE organization_id=%s GROUP BY 1 ORDER BY 1", (org,))}
    models = [r["model"] for r in conn.execute("SELECT DISTINCT model FROM embeddings WHERE organization_id=%s ORDER BY 1", (org,))]
    cov = {}
    for m in models:
        rows = tier_coverage(conn, org, m)
        cov[m] = {"tiers": rows, "text": coverage_text(rows),
                  "stored": sum(r["stored"] for r in rows), "wanted": sum(r["wanted"] for r in rows)}
    facts = {r["fact_type"]: r["n"] for r in conn.execute(
        "SELECT fact_type, count(*) n FROM facts WHERE organization_id=%s AND status IN ('active','candidate') GROUP BY 1", (org,))}
    people = conn.execute("SELECT count(DISTINCT coalesce(payload->>'author', payload->>'assignee')) n FROM source_records "
                          "WHERE organization_id=%s", (org,)).fetchone()["n"]
    prs = conn.execute("SELECT count(*) n, count(*) FILTER (WHERE payload ? 'patches' AND payload->'patches' <> '{}'::jsonb) with_diff "
                       "FROM source_records WHERE organization_id=%s AND source_type='github_pr'", (org,)).fetchone()
    diff_line = (f"{prs['with_diff']} of {prs['n']} pull requests carry their diff; a review names a line only where the diff shows it, "
                 "and stays at file level elsewhere." if prs["n"] else "No pull requests were read.")
    return {"organization": org_row, "by_type": by_type, "embeddings": cov, "facts": facts, "people": people,
            "tiers": list(TIERS),
            "limits": [diff_line,
                       "Each embedding model is its own index; vectors of different models are never mixed.",
                       "Judgments are made by a model and kept only when they cite sources that exist."]}


def provenance(conn: psycopg.Connection, org: int, record_id: int) -> dict | None:
    r = conn.execute("SELECT id, source_type, source_id, title, body, source_url, payload FROM source_records "
                     "WHERE organization_id=%s AND id=%s", (org, record_id)).fetchone()
    if not r:
        return None
    p = r["payload"] or {}
    out = {"id": f"record:{r['id']}", "type": r["source_type"], "source_id": r["source_id"], "title": r["title"],
           "body": r["body"] or "", "url": r["source_url"], "author": p.get("author") or p.get("assignee"),
           "date": p.get("date") or p.get("merged_at") or p.get("updated"), "path": p.get("path"), "thread": [], "related": []}
    pr_key = None
    if r["source_type"] == "github_comment":
        pr_key = f"{p.get('repo')}#{p.get('number')}"
    elif r["source_type"] == "github_pr":
        pr_key = r["source_id"]
    if pr_key:
        pr = conn.execute("SELECT id, title, source_url, payload FROM source_records WHERE organization_id=%s AND "
                          "source_type='github_pr' AND source_id=%s", (org, pr_key)).fetchone()
        if pr:
            pp = pr["payload"]
            out["related"].append({"id": f"record:{pr['id']}", "kind": "pull_request", "title": f"{pr_key}: {pr['title']}",
                                   "url": pr["source_url"], "who": pp.get("author"), "when": pp.get("merged_at"),
                                   "files": pp.get("files", [])})
            for k in pp.get("linked_tickets", []):
                t = conn.execute("SELECT id, title, source_url, payload FROM source_records WHERE organization_id=%s AND "
                                 "source_type='jira_issue' AND source_id=%s", (org, k)).fetchone()
                if t:
                    out["related"].append({"id": f"record:{t['id']}", "kind": "ticket", "title": f"{k}: {t['title']}",
                                           "url": t["source_url"], "who": t["payload"].get("assignee"),
                                           "when": t["payload"].get("updated")})
        for c in conn.execute("SELECT id, title, body, source_url, payload FROM source_records WHERE organization_id=%s AND "
                              "source_type='github_comment' AND payload->>'repo'=%s AND payload->>'number'=%s "
                              "ORDER BY payload->>'date', id", (org, p.get("repo"), str(p.get("number")))):
            out["thread"].append({"id": f"record:{c['id']}", "who": c["payload"].get("author"), "when": c["payload"].get("date"),
                                  "kind": c["payload"].get("kind"), "path": c["payload"].get("path"), "body": c["body"],
                                  "url": c["source_url"], "current": c["id"] == r["id"]})
    return out


def starters(conn: psycopg.Connection, org: int, n: int = 3) -> list[str]:
    """Questions the corpus can answer, derived from remembered reviewer guidance (topic) when it exists, else from ADR titles."""
    out = []
    for r in conn.execute("SELECT summary FROM facts WHERE organization_id=%s AND fact_type='review_guidance' AND "
                          "status IN ('active','candidate') ORDER BY valid_from DESC NULLS LAST, id LIMIT %s", (org, n)):
        topic = r["summary"].split(":", 1)[0].strip()
        if topic:
            out.append(f"What is our rule on {topic if topic[:2].isupper() else topic[0].lower() + topic[1:]}, and who set it?")
    if len(out) < n:
        for r in conn.execute("SELECT title FROM source_records WHERE organization_id=%s AND source_type='adr' ORDER BY id LIMIT %s",
                              (org, n - len(out))):
            out.append(f"What does \"{r['title']}\" mean for a new change?")
    return out


def _meta(r) -> dict:
    p = r["payload"] or {}
    return {"type": r["source_type"], "who": p.get("author") or p.get("assignee"),
            "when": p.get("date") or p.get("merged_at") or p.get("updated"), "title": r["title"], "record": r["id"]}


def tags(conn: psycopg.Connection, org: int, ids: list[str]) -> dict[str, dict]:
    """Who/when/type for evidence ids as the planner, reviewer and ask produce them (record:, fact:, hit:record:, pr:, ticket:,
    edge:, area:). Unknown ids are simply absent; nothing is invented."""
    out: dict[str, dict] = {}
    q = "SELECT id, source_type, title, payload FROM source_records WHERE organization_id=%s AND "
    for i in dict.fromkeys(ids[:200]):
        r = None
        try:
            if i.startswith("record:") or i.startswith("hit:record:"):
                r = conn.execute(q + "id=%s", (org, int(i.rsplit(":", 1)[1]))).fetchone()
            elif i.startswith("pr:"):
                r = conn.execute(q + "source_type='github_pr' AND source_id=%s", (org, i[3:])).fetchone()
            elif i.startswith("ticket:"):
                r = conn.execute(q + "source_type='jira_issue' AND source_id=%s", (org, i[7:])).fetchone()
            elif i.startswith("fact:"):
                f = conn.execute("SELECT fact_type, source_type, source_id, valid_from FROM facts WHERE organization_id=%s AND id=%s",
                                 (org, int(i[5:]))).fetchone()
                if f:
                    r = conn.execute(q + "source_type=%s AND source_id=%s", (org, f["source_type"], f["source_id"])).fetchone()
                    out[i] = {**(_meta(r) if r else {"type": f["source_type"], "who": None, "when": None, "title": None,
                                                     "record": None}), "fact_type": f["fact_type"]}
                    if not r and f["valid_from"]:
                        out[i]["when"] = f["valid_from"].date().isoformat()
                continue
            elif i.startswith("edge:"):
                out[i] = {"type": "dependency", "who": None, "when": None, "title": i[5:], "record": None}
                continue
            elif i.startswith("area:"):
                out[i] = {"type": "statistic", "who": None, "when": None, "title": i[5:], "record": None}
                continue
        except (ValueError, IndexError):
            continue
        if r:
            out[i] = _meta(r)
    return out


def files(conn: psycopg.Connection, org: int, limit: int = 600) -> list[dict]:
    """Code files that can be traced: id is 'repo:path'."""
    return [{"id": r["source_id"], "repo": r["source_id"].split(":", 1)[0], "path": r["source_id"].split(":", 1)[1]}
            for r in conn.execute("SELECT source_id FROM source_records WHERE organization_id=%s AND source_type='file' "
                                  "ORDER BY source_id LIMIT %s", (org, limit))]
