"""Live Jira Cloud connector: issues of one project -> `jira_issue` source records.

    python -m app.ingestion.jira            # reads ~/.config/lore/jira.env (JIRA_SITE, JIRA_EMAIL, JIRA_TOKEN,
                                            # JIRA_PROJECT) and writes into organization JIRA_ORG_SLUG (default live-demo)

Records have the same shape as the fixture tickets, so the graph builder, search and planner are unchanged.
Incremental: the cursor is the newest `updated` timestamp seen; a run re-reads issues updated since then.
Atlassian Document Format (the rich-text JSON of descriptions/comments) is flattened to plain text structurally.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request

import psycopg

from ..config import get_settings
from ..db import connect
from .fixtures import Rec, Stats, upsert_record

SOURCE = "jira"
FIELDS = "summary,description,status,issuetype,labels,assignee,reporter,issuelinks,created,updated,project,comment"


def adf_text(node) -> str:
    """Flatten an Atlassian Document Format tree to text (paragraph/list/code structure kept as line breaks)."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    kind = node.get("type")
    if kind == "text":
        return node.get("text", "")
    if kind == "hardBreak":
        return "\n"
    if kind in ("mention", "emoji", "inlineCard"):
        a = node.get("attrs", {})
        return a.get("text") or a.get("url") or a.get("shortName") or ""
    inner = "".join(adf_text(c) for c in node.get("content", []))
    if kind in ("paragraph", "heading", "codeBlock", "blockquote", "listItem", "tableRow"):
        return inner + "\n"
    return inner


def map_links(links: list[dict]) -> list[dict]:
    """Jira issue links -> [{key, type}] from THIS issue's point of view (the builder reads 'blocks')."""
    out = []
    for l in links or []:
        t = l.get("type", {})
        if "outwardIssue" in l:
            key, label = l["outwardIssue"]["key"], t.get("outward", t.get("name", "relates to"))
        elif "inwardIssue" in l:
            key, label = l["inwardIssue"]["key"], t.get("inward", t.get("name", "relates to"))
        else:
            continue
        out.append({"key": key, "type": label.strip().lower().replace(" ", "-")})
    return out


class Jira:
    def __init__(self, site: str, email: str, token: str):
        self.site = site.rstrip("/")
        self._auth = "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()

    def get(self, path: str, **params) -> dict:
        url = f"{self.site}{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers={"Authorization": self._auth, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    def issues(self, jql: str):
        token = None
        while True:
            params = {"jql": jql, "fields": FIELDS, "maxResults": 100}
            if token:
                params["nextPageToken"] = token
            page = self.get("/rest/api/3/search/jql", **params)
            yield from page.get("issues", [])
            token = page.get("nextPageToken")
            if page.get("isLast", True) or not token:
                return


def to_rec(site: str, issue: dict) -> Rec:
    f = issue["fields"]
    comments = [f"{(c.get('author') or {}).get('displayName', '?')}: {adf_text(c.get('body')).strip()}"
                for c in (f.get("comment") or {}).get("comments", [])]
    body = adf_text(f.get("description")).strip()
    if comments:
        body += "\n\nComments:\n" + "\n".join(comments)
    payload = {
        "key": issue["key"], "summary": f["summary"], "description": body, "status": f["status"]["name"],
        "type": f["issuetype"]["name"], "labels": f.get("labels", []), "links": map_links(f.get("issuelinks")),
        "project": f["project"]["key"], "assignee": (f.get("assignee") or {}).get("displayName"),
        "reporter": (f.get("reporter") or {}).get("displayName"), "created": f["created"][:10],
        "updated": f["updated"][:10], "updated_at": f["updated"]}
    return Rec("jira_issue", issue["key"], None, f["summary"], body, payload, f"{site}/browse/{issue['key']}",
               f["updated"])


def sync(conn: psycopg.Connection, jira: Jira, project: str, org_slug: str, org_name: str,
         mode: str = "incremental") -> tuple[int, Stats]:
    org_id = conn.execute(
        "INSERT INTO organizations (slug, name, is_synthetic) VALUES (%s,%s,false) "
        "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name RETURNING id", (org_slug, org_name)).fetchone()["id"]
    cur = conn.execute("SELECT cursor FROM ingestion_cursors WHERE organization_id=%s AND source=%s",
                       (org_id, SOURCE)).fetchone()
    cursor = cur["cursor"] if (cur and mode == "incremental") else None
    jql = f'project = "{project}"' + (f' AND updated >= "{cursor[:16].replace("T", " ")}"' if cursor else "") \
        + " ORDER BY updated ASC"
    run_id = conn.execute("INSERT INTO ingestion_runs (organization_id, source, mode) VALUES (%s,%s,%s) RETURNING id",
                          (org_id, SOURCE, mode)).fetchone()["id"]
    st, newest = Stats(), cursor or ""
    try:
        for issue in jira.issues(jql):
            rec = to_rec(jira.site, issue)
            st.seen += 1
            st.by_type["jira_issue"] = st.by_type.get("jira_issue", 0) + 1
            outcome = upsert_record(conn, org_id, None, rec)
            setattr(st, outcome, getattr(st, outcome) + 1)
            newest = max(newest, rec.when or "")
        if newest:
            conn.execute("INSERT INTO ingestion_cursors (organization_id, source, cursor) VALUES (%s,%s,%s) "
                         "ON CONFLICT (organization_id, source) DO UPDATE SET cursor=EXCLUDED.cursor, updated_at=now()",
                         (org_id, SOURCE, newest))
        conn.execute("UPDATE ingestion_runs SET status='succeeded', finished_at=now(), records_seen=%s, "
                     "records_new=%s, records_changed=%s WHERE id=%s", (st.seen, st.new, st.changed, run_id))
    except Exception as exc:
        conn.rollback()
        conn.execute("INSERT INTO ingestion_runs (organization_id, source, mode, status, finished_at, error) "
                     "VALUES (%s,%s,%s,'failed',now(),%s)", (org_id, SOURCE, mode, type(exc).__name__))
        conn.commit()
        raise
    return org_id, st


def main() -> None:
    env = {k: os.environ[k] for k in ("JIRA_SITE", "JIRA_EMAIL", "JIRA_TOKEN", "JIRA_PROJECT")}
    jira = Jira(env["JIRA_SITE"], env["JIRA_EMAIL"], env["JIRA_TOKEN"])
    slug = os.environ.get("JIRA_ORG_SLUG", "live-demo")
    with connect() as conn:
        org_id, st = sync(conn, jira, env["JIRA_PROJECT"], slug, os.environ.get("JIRA_ORG_NAME", "Live Jira project"),
                          os.environ.get("JIRA_MODE", "incremental"))
    print(json.dumps({"organization": slug, "organization_id": org_id, **st.__dict__}, default=str))


if __name__ == "__main__":
    get_settings()
    main()
