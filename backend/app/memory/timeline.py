"""Memory timeline: reviewer guidance remembered from threads, traced through everything that later touched the topic.

The guidance itself was extracted by a model with a literal-quote guard (knowledge/judgments.review_guidance). Here a
second judgment places other records relative to it (restates / follows / conflicts / replaces / mentions) and decides
whether it still holds today; quotes must literally occur in the cited record, otherwise the item is discarded.
"""
from __future__ import annotations

import re

import psycopg

from ..intelligence import tasks as T
from ..intelligence.judge import run_task
from ..models.provider import LLMUnavailable, Provider
from ..retrieval.search import search_with_meta

RELATIONS = ("restates", "follows", "conflicts", "replaces", "mentions")
STATUSES = ("holds", "contradicted", "replaced", "unclear")


def _norm(s: str) -> str:
    """Whitespace, case, markdown ticks/emphasis and curly quotes are not content; the words themselves must match."""
    s = (s or "").replace("`", "").replace("*", "").translate(str.maketrans("\u2018\u2019\u201c\u201d", "''\"\""))
    return re.sub(r"\s+", " ", s).strip().lower()


def _source(conn, org: int, f: dict) -> dict | None:
    r = conn.execute("SELECT id, title, body, source_url, payload FROM source_records WHERE organization_id=%s AND "
                     "source_type=%s AND source_id=%s", (org, f["source_type"], f["source_id"])).fetchone()
    if not r:
        return None
    p = r["payload"] or {}
    return {"id": f"record:{r['id']}", "rid": r["id"], "title": r["title"], "url": r["source_url"], "author": p.get("author"),
            "date": p.get("date"), "path": p.get("path"), "repo": p.get("repo"), "pr": f"{p.get('repo')}#{p.get('number')}",
            "original": r["body"] or ""}


def list_guidance(conn: psycopg.Connection, org: int) -> list[dict]:
    out = []
    for f in conn.execute("SELECT id, summary, scope, status, source_type, source_id, source_url, valid_from FROM facts "
                          "WHERE organization_id=%s AND fact_type='review_guidance' AND status IN ('active','candidate') "
                          "ORDER BY valid_from DESC NULLS LAST, id", (org,)):
        src = _source(conn, org, f)
        out.append({"id": f["id"], "ref": f"fact:{f['id']}", "summary": f["summary"], "scope": f["scope"],
                    "date": f["valid_from"].date().isoformat() if f["valid_from"] else (src or {}).get("date"),
                    "source": {k: v for k, v in (src or {}).items() if k not in ("rid",)}})
    return out


def timeline(conn: psycopg.Connection, org: int, provider: Provider, fact_id: int) -> dict | None:
    f = conn.execute("SELECT id, summary, scope, status, source_type, source_id, source_url, valid_from FROM facts "
                     "WHERE organization_id=%s AND id=%s AND fact_type='review_guidance'", (org, fact_id)).fetchone()
    if not f:
        return None
    src = _source(conn, org, f)
    head = {"id": f["id"], "ref": f"fact:{f['id']}", "summary": f["summary"], "scope": f["scope"],
            "source": {k: v for k, v in (src or {}).items() if k != "rid"}}
    if not provider.has_llm:
        return {"status": "llm_required", "guidance": head, "events": [],
                "note": "Placing later records against the guidance needs a model."}
    try:
        hits, _ = search_with_meta(conn, org, provider, f["summary"], 16)
    except LLMUnavailable:
        hits = []
    cands = {}
    for h in hits:
        if h.kind != "record" or (src and h.id == src["rid"]):
            continue
        r = conn.execute("SELECT id, source_type, title, body, source_url, payload FROM source_records WHERE id=%s", (h.id,)).fetchone()
        p = r["payload"] or {}
        cands[h.ref] = {"id": h.ref, "type": r["source_type"], "title": r["title"], "url": r["source_url"], "repo": h.repo,
                        "status": h.status, "author": p.get("author") or p.get("assignee"),
                        "date": p.get("date") or p.get("merged_at") or p.get("updated"), "path": p.get("path"),
                        "text": (r["body"] or "")[:2500], "_body": r["body"] or ""}
    if not cands:
        return {"status": "ok", "guidance": head, "events": [], "verdict": {"status": "unclear", "reason":
                "No other records touch this topic.", "cites": []}}
    try:
        res = run_task(conn, org, provider, "guidance_timeline", T.GUIDANCE_TIMELINE["system"], {
            "guidance": {"text": f["summary"], "said_by": (src or {}).get("author"), "date": (src or {}).get("date"),
                         "exact_words": (src or {}).get("original", "")[:2500]},
            "candidates": [{k: v for k, v in c.items() if k != "_body"} for c in cands.values()]},
            T.GUIDANCE_TIMELINE["schema"])
    except LLMUnavailable as exc:
        return {"status": "llm_required", "guidance": head, "events": [], "note": str(exc)}
    events = []
    for e in res["events"]:
        c = cands.get(e["id"])
        if not c or e["relation"] not in RELATIONS or _norm(e["quote"]) not in _norm(c["_body"]) or not _norm(e["quote"]):
            continue                      # unknown record, unknown relation, or words that are not in the record
        events.append({"id": c["id"], "relation": e["relation"], "quote": e["quote"], "note": e["note"], "type": c["type"],
                       "title": c["title"], "url": c["url"], "author": c["author"], "date": c["date"], "path": c["path"],
                       "repo": c["repo"]})
    events.sort(key=lambda e: (e["date"] is None, e["date"] or ""))
    ids = [i for i in dict.fromkeys(res["status_cites"]) if i in cands]
    status = res["status"] if res["status"] in STATUSES else "unclear"
    if status in ("contradicted", "replaced") and not ids:
        status = "unclear"               # a verdict against the guidance needs the records that justify it
    dated = {c["id"]: c["date"] for c in cands.values()}
    gdate = (src or {}).get("date")
    if status == "replaced" and not any(dated.get(i) and gdate and dated[i] >= gdate for i in ids):
        status = "unclear"               # only a later record can replace it
    return {"status": "ok", "guidance": head, "events": events,
            "verdict": {"status": status, "reason": res["status_reason"], "cites": ids}}
