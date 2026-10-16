"""Knowledge map: what each person knows, computed from the organization's own history, and a handover brief.

Everything numeric (commit shares, counts, last activity) is computed here from ingested records. The brief is a model
judgment over that packet; each item must cite evidence ids that exist in the packet or it is dropped.
"""
from __future__ import annotations

from collections import Counter, defaultdict

import psycopg

from ..intelligence import tasks as T
from ..intelligence.guards import exact, highlight
from ..intelligence.judge import run_task
from ..models.provider import LLMUnavailable, Provider


def _commits(conn, org):
    return [r["payload"] for r in conn.execute(
        "SELECT payload FROM source_records WHERE organization_id=%s AND source_type='github_commit'", (org,))]


def _people_names(conn, org) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in conn.execute("SELECT canonical_name, attributes FROM entities WHERE organization_id=%s AND entity_type='person'",
                          (org,)):
        out[r["canonical_name"]] = dict(r["attributes"] or {})
    return out


def roster(conn: psycopg.Connection, org: int) -> list[dict]:
    """Everyone seen in commits, PRs, review comments or ticket assignments, with activity counts."""
    commits = Counter(c["author"] for c in _commits(conn, org) if c.get("author"))
    prs, comments, tickets, last = Counter(), Counter(), Counter(), {}
    for r in conn.execute("SELECT source_type, payload FROM source_records WHERE organization_id=%s AND source_type IN "
                          "('github_pr','github_comment','jira_issue')", (org,)):
        p = r["payload"] or {}
        if r["source_type"] == "github_pr" and p.get("author"):
            prs[p["author"]] += 1
            last[p["author"]] = max(last.get(p["author"], ""), p.get("merged_at") or "")
        elif r["source_type"] == "github_comment" and p.get("author"):
            comments[p["author"]] += 1
            last[p["author"]] = max(last.get(p["author"], ""), p.get("date") or "")
        elif r["source_type"] == "jira_issue" and p.get("assignee"):
            tickets[p["assignee"]] += 1
    for c in _commits(conn, org):
        if c.get("author"):
            last[c["author"]] = max(last.get(c["author"], ""), c.get("date") or "")
    guidance = Counter()
    for r in conn.execute("SELECT source_id FROM facts WHERE organization_id=%s AND fact_type='review_guidance' AND "
                          "status IN ('active','candidate')", (org,)):
        a = conn.execute("SELECT payload->>'author' AS a FROM source_records WHERE organization_id=%s AND "
                         "source_type='github_comment' AND source_id=%s", (org, r["source_id"])).fetchone()
        if a and a["a"]:
            guidance[a["a"]] += 1
    names = set(commits) | set(prs) | set(comments) | set(tickets)
    return sorted(({"login": n, "commits": commits[n], "prs": prs[n], "comments": comments[n], "tickets": tickets[n],
                    "guidance": guidance[n], "last_active": last.get(n)} for n in names),
                  key=lambda x: -(x["commits"] + x["prs"] + 3 * x["comments"] + 5 * x["guidance"]))


def profile(conn: psycopg.Connection, org: int, login: str, areas_n: int = 12) -> dict | None:
    """Deterministic packet for one person, including the evidence registry the brief may cite."""
    commits = _commits(conn, org)
    ref = max((c.get("date") or "" for c in commits), default="")
    per_file: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for c in commits:
        for f in c.get("files", []):
            per_file[(c["repo"], f)][c.get("author")] += 1
    ev: dict[str, dict] = {}
    areas = []
    for (repo, f), cnt in per_file.items():
        n, tot = cnt.get(login, 0), sum(cnt.values())
        if not n:
            continue
        others = sorted(((a, k) for a, k in cnt.items() if a != login), key=lambda x: -x[1])
        areas.append({"repo": repo, "file": f, "commits": n, "total": tot, "share": round(n / tot, 3),
                      "others": [{"login": a, "commits": k} for a, k in others[:3]]})
    areas.sort(key=lambda a: (-a["share"] * a["commits"], a["repo"], a["file"]))
    areas = areas[:areas_n]
    for a in areas:
        eid = f"area:{a['repo']}/{a['file']}"
        a["id"] = eid
        who = ", ".join(f"{o['login']} ({o['commits']})" for o in a["others"]) or "nobody else"
        ev[eid] = {"id": eid, "kind": "statistic", "evidence_type": "structural", "status": "active",
                   "label": f"{login} made {a['commits']} of {a['total']} commits to {a['repo']}/{a['file']} "
                            f"({a['share']:.0%}); others: {who}", "url": None}
    prs, comments, tickets = [], [], []
    for r in conn.execute("SELECT id, source_type, source_id, title, source_url, payload FROM source_records WHERE "
                          "organization_id=%s AND source_type IN ('github_pr','github_comment','jira_issue') "
                          "ORDER BY id", (org,)):
        p = r["payload"] or {}
        item = {"id": f"record:{r['id']}", "source_id": r["source_id"], "title": r["title"], "url": r["source_url"]}
        if r["source_type"] == "github_pr" and (p.get("author") == login or login in (p.get("reviewers") or [])):
            item.update(role="author" if p.get("author") == login else "reviewer", date=p.get("merged_at"),
                        repo=p.get("repo"), files=p.get("files", [])[:6])
            prs.append(item)
        elif r["source_type"] == "github_comment" and p.get("author") == login:
            item.update(date=p.get("date"), repo=p.get("repo"), kind=p.get("kind"), path=p.get("path"))
            comments.append(item)
        elif r["source_type"] == "jira_issue" and p.get("assignee") == login:
            item.update(status=p.get("status"), key=p.get("key"))
            tickets.append(item)
    for it in prs + comments + tickets:
        ev[it["id"]] = {"id": it["id"], "kind": "record", "evidence_type": "explicit", "status": "active",
                        "label": it["title"], "url": it["url"]}
    # comment bodies for the brief (need text, fetched separately to keep the loop light)
    bodies = {r["id"]: r["body"] for r in conn.execute(
        "SELECT id, body FROM source_records WHERE organization_id=%s AND id = ANY(%s)",
        (org, [int(c["id"].split(":")[1]) for c in comments] or [0]))}
    for c in comments:
        c["text"] = (bodies.get(int(c["id"].split(":")[1])) or "")[:600]
    facts = []
    for f in conn.execute(
            "SELECT f.id, f.fact_type, f.predicate, f.summary, f.status, f.evidence_type, f.source_url, f.source_id, "
            "f.source_type FROM facts f WHERE f.organization_id=%s AND f.status IN ('active','candidate') AND "
            "f.fact_type IN ('ownership','review_guidance') ORDER BY f.id", (org,)):
        mine = login in f["summary"]
        if f["fact_type"] == "review_guidance":
            src = conn.execute("SELECT payload->>'author' AS a FROM source_records WHERE organization_id=%s AND "
                               "source_type=%s AND source_id=%s", (org, f["source_type"], f["source_id"])).fetchone()
            mine = bool(src and src["a"] == login)
        if mine:
            facts.append({"id": f"fact:{f['id']}", "type": f["fact_type"], "predicate": f["predicate"],
                          "summary": f["summary"], "url": f["source_url"]})
            ev[f"fact:{f['id']}"] = {"id": f"fact:{f['id']}", "kind": "fact", "evidence_type": f["evidence_type"],
                                     "status": f["status"], "label": f["summary"], "url": f["source_url"]}
    if not (areas or prs or comments or tickets or facts):
        return None
    last = max([c.get("date") or "" for c in commits if c.get("author") == login] +
               [x.get("date") or "" for x in prs + comments] + [""])
    people = {r["login"]: r for r in roster(conn, org)}
    row = people.get(login, {})
    return {"login": login, "commits": row.get("commits", 0), "last_active": last or None, "reference_date": ref,
            "areas": areas, "pull_requests": prs, "comments": comments, "tickets": tickets, "facts": facts,
            "evidence": ev}


def handover(conn: psycopg.Connection, org: int, provider: Provider, login: str) -> dict:
    prof = profile(conn, org, login)
    if prof is None:
        return {"status": "unknown_person", "login": login}
    if not provider.has_llm:
        return {"status": "llm_required", "login": login, "profile": prof,
                "note": "The brief needs a model; the profile above is computed without one."}
    packet = {"person": login, "last_active": prof["last_active"], "reference_date": prof["reference_date"],
              "areas": [{"id": a["id"], "repo": a["repo"], "file": a["file"], "commits": a["commits"],
                         "of_total": a["total"], "others": a["others"]} for a in prof["areas"]],
              "pull_requests": [{k: v for k, v in p.items() if k != "url"} for p in prof["pull_requests"]],
              "comments": [{k: v for k, v in c.items() if k != "url"} for c in prof["comments"]],
              "tickets": [{k: v for k, v in t.items() if k != "url"} for t in prof["tickets"]],
              "facts": [{k: v for k, v in f.items() if k != "url"} for f in prof["facts"]]}
    try:
        res = run_task(conn, org, provider, "handover", T.HANDOVER["system"], packet, T.HANDOVER["schema"])
    except LLMUnavailable as exc:
        return {"status": "llm_required", "login": login, "profile": prof, "note": str(exc)}
    ev = prof["evidence"]
    sections = {}
    for k in ("only_they_know", "standards_they_set", "open_work", "people_to_ask", "risks", "first_week"):
        items = []
        for it in res[k]:
            ids = [i for i in dict.fromkeys(it.get("cites") or []) if i in ev]
            if it["text"].strip() and ids:
                items.append({"text": it["text"].strip(), "cites": ids, "key": highlight(it.get("key", ""), it["text"])})
        sections[k] = items
    used = {i for items in sections.values() for it in items for i in it["cites"]}
    return {"status": "ok", "login": login, "summary": res["summary"], **sections,
            "citations": [ev[i] for i in ev if i in used], "profile": prof}
