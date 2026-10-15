"""Evidence-bound pull-request review drafts. LOCAL OUTPUT ONLY.

Drafts comments for one PR already in the corpus, using the team's decisions (including superseded ones), existing
compliance findings, ownership/bus-factor facts, dependency impact and runbooks. Same discipline as the planner:
  - a comment must cite evidence ids that exist in the registry, otherwise it is discarded;
  - 'decision_violation' needs a literal quote from the cited decision, otherwise it is discarded;
  - a violation of a superseded decision is never reported (a stale reference is, naming the replacement);
  - labels (verified/inferred) come from the cited evidence, never from the model;
  - when nothing is supported the draft says so. Silence beats a guess.
There is deliberately no network code in this module and no 'post' path: drafts are written to files under
reviews/ and nowhere else. Diffs are not ingested, so comments are file-level, never line-level.

    python -m app.review.reviewer --repo notify-svc --pr 41     # ORG_SLUG selects the corpus
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from ..graph.impact import impact
from ..intelligence import tasks as T
from ..intelligence.judge import meter, run_task
from ..models.provider import LLMUnavailable, Provider
from ..planning.planner import Evidence, _label_for, _valid
from ..retrieval.search import search_with_meta

TYPES = {"decision_violation", "superseded_reference", "ownership_risk", "dependency_impact", "runbook_reminder",
         "missing_override", "other"}
EVIDENCE_BUDGET_CHARS = 30_000
_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", s or "").strip().lower()


def _fits(quote: str, text: str) -> bool:
    q = _norm(quote)
    return bool(q) and q in _norm(text)


def build_packet(conn: psycopg.Connection, org_id: int, provider: Provider, repo: str, number: int) -> tuple[dict, Evidence, dict]:
    ev = Evidence()
    pr = conn.execute("SELECT s.id, s.source_id, s.title, s.body, s.payload, s.source_url FROM source_records s "
                      "WHERE s.organization_id=%s AND s.source_type='github_pr' AND s.source_id=%s",
                      (org_id, f"{repo}#{number}")).fetchone()
    if not pr:
        raise LookupError(f"{repo}#{number} is not in this corpus")
    payload = pr["payload"]
    files = payload.get("files", [])
    pid = ev.add(f"pr:{repo}#{number}", "pull_request", f"{repo}#{number}: {pr['title']}", pr["source_url"], "explicit")
    packet: dict = {"pull_request": {
        "id": pid, "repo": repo, "title": pr["title"], "description": pr["body"] or "", "files": files,
        "adds_imports": payload.get("adds_imports", []), "author": payload.get("author"),
        "labels": payload.get("labels", []), "linked_tickets": payload.get("linked_tickets", [])}}

    repo_row = conn.execute("SELECT id FROM repositories WHERE organization_id=%s AND name=%s", (org_id, repo)).fetchone()
    repo_id = repo_row["id"] if repo_row else None
    svc = {r["canonical_name"]: r["id"] for r in conn.execute(
        "SELECT id, canonical_name FROM entities WHERE organization_id=%s AND entity_type='service'", (org_id,))}
    applies = defaultdict(set)
    for r in conn.execute("SELECT src_id, dst_id FROM edges WHERE organization_id=%s AND rel_type='applies_to'", (org_id,)):
        applies[r["src_id"]].add(r["dst_id"])
    adr_body = {r["source_id"]: r["body"] for r in conn.execute(
        "SELECT source_id, body FROM source_records WHERE organization_id=%s AND source_type='adr'", (org_id,))}

    decisions, decision_text = [], {}
    others = {"existing_findings": [], "ownership": []}
    for f in conn.execute("SELECT * FROM facts WHERE organization_id=%s AND status IN ('active','candidate','superseded') "
                          "ORDER BY id", (org_id,)):
        if f["fact_type"] == "decision":
            scope = applies.get(f["subject_id"], set())
            if not scope or svc.get(repo) in scope:  # org-wide, or applies to this repository's service
                eid = ev.add(f"fact:{f['id']}", "decision", f["summary"], f["source_url"], f["evidence_type"], f["status"])
                text = adr_body.get(f["source_id"], f["summary"])
                decisions.append({"id": eid, "adr": f["object_value"], "status": f["status"], "summary": f["summary"],
                                  "text": text})
                decision_text[eid] = text
        elif f["source_type"] == "github_pr" and f["source_id"] == f"{repo}#{number}":
            eid = ev.add(f"fact:{f['id']}", f["fact_type"], f["summary"], f["source_url"], f["evidence_type"], f["status"])
            others["existing_findings"].append({"id": eid, "type": f["fact_type"], "predicate": f["predicate"],
                                                "status": f["status"], "summary": f["summary"]})
        elif f["fact_type"] in ("ownership", "risk") and f["repository_id"] == repo_id and f["status"] in ("active", "candidate"):
            eid = ev.add(f"fact:{f['id']}", f["fact_type"], f["summary"], f["source_url"], f["evidence_type"], f["status"])
            others["ownership"].append({"id": eid, "type": f["fact_type"], "summary": f["summary"], "status": f["status"]})
    packet["decisions"] = decisions
    packet.update(others)

    imp = impact(conn, org_id, [repo], 3)
    dep = []
    for kind, key in (("depends_on_changed_service", "dependents"), ("changed_service_depends_on", "dependencies")):
        for d in imp[key]:
            ids = [ev.add(f"edge:{e['from']}->{e['to']}", "dependency", f"{e['from']} depends on {e['to']}",
                          e["source"], e["evidence_type"]) for e in d["evidence"]]
            dep.append({"relation": kind, "service": d["service"], "path": d["path"], "evidence": ids})
    packet["dependency_impact"] = dep

    tickets = []
    for key in packet["pull_request"]["linked_tickets"]:
        t = conn.execute("SELECT title, payload, source_url FROM source_records WHERE organization_id=%s AND "
                         "source_type='jira_issue' AND source_id=%s", (org_id, key)).fetchone()
        if t:
            eid = ev.add(f"ticket:{key}", "ticket", f"{key}: {t['title']}", t["source_url"], "explicit")
            tickets.append({"id": eid, "key": key, "summary": t["title"], "status": t["payload"].get("status")})
    packet["linked_tickets"] = tickets

    hits, meta = search_with_meta(conn, org_id, provider, f"{pr['title']} {' '.join(files)}".strip(), k=8)
    docs = []
    for h in hits:
        if h.kind == "record" and h.source_type in ("doc", "adr"):
            eid = ev.add(f"hit:record:{h.id}", "retrieval", h.title, h.source_url, "inferred", h.status or "active")
            docs.append({"id": eid, "title": h.title, "source": h.source_id, "passage": h.snippet[:1500]})
    packet["runbooks_and_docs"] = docs
    return packet, ev, {"search_mode": meta["mode"], "decision_text": decision_text, "files": files}


def draft_review(conn: psycopg.Connection, org_id: int, provider: Provider, repo: str, number: int) -> dict:
    before = meter.snapshot()
    packet, ev, aux = build_packet(conn, org_id, provider, repo, number)
    try:
        raw = run_task(conn, org_id, provider, "pr_review", T.PR_REVIEW["system"], packet, T.PR_REVIEW["schema"])
    except LLMUnavailable as exc:
        return {"status": "llm_required", "repo": repo, "pr": number, "explanation": str(exc), "comments": []}
    comments, dropped = [], []
    seen = set()
    status_of = {i: it["status"] for i, it in ev.items.items()}
    for c in raw.get("comments", []):
        ctype = c.get("type") if c.get("type") in TYPES else "other"
        ids = _valid(c.get("evidence"), ev)
        ids = [i for i in ids if i != f"pr:{repo}#{number}"] or []  # the PR itself is not evidence for a judgment
        if not ids:
            dropped.append({"reason": "no valid evidence", "comment": c.get("comment", "")[:120]})
            continue
        if ctype == "decision_violation":
            cited = [i for i in ids if i in aux["decision_text"]]
            if not cited or any(status_of[i] == "superseded" for i in cited):
                dropped.append({"reason": "violation of a superseded or non-decision source", "comment": c.get("comment", "")[:120]})
                continue
            if not any(_fits(c.get("quote", ""), aux["decision_text"][i]) for i in cited):
                dropped.append({"reason": "quote not found in the cited decision", "comment": c.get("comment", "")[:120]})
                continue
        if ctype == "dependency_impact":
            # Impact means CONSUMERS of the changed service: a cited edge must end at it (X depends on <repo>).
            if not any(i.startswith("edge:") and i.rsplit("->", 1)[-1] == repo for i in ids):
                dropped.append({"reason": "dependency impact does not cite a consumer of the changed service",
                                "comment": c.get("comment", "")[:120]})
                continue
        file = c.get("file") or ""
        if file and file not in aux["files"]:
            file = ""  # we only know changed files; never point at a file the PR does not touch
        key = (ctype, file, _norm(c.get("comment", "")))
        if key in seen or not c.get("comment", "").strip():
            continue
        seen.add(key)
        comments.append({"type": ctype, "file": file or None, "comment": c["comment"].strip(),
                         "quote": (c.get("quote") or None) if ctype == "decision_violation" else None,
                         "evidence": ids, "label": _label_for(ev, ids)})
    after = meter.snapshot()
    return {"status": "draft", "repo": repo, "pr": number, "title": packet["pull_request"]["title"],
            "comments": comments, "dropped": dropped, "nothing_to_say": not comments,
            "evidence": {i: ev.items[i] for c in comments for i in c["evidence"]},
            "provenance": {"provider": provider.name, "search_mode": aux["search_mode"],
                           "model": getattr(provider, "last_model", None),
                           "model_calls_live": after["live"] - before["live"],
                           "replayed": after["replayed"] - before["replayed"],
                           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "limitations": "file-level only: diffs are not ingested; comments never claim line-level facts"}}


def render(review: dict) -> str:
    head = [f"# DRAFT review — {review['repo']}#{review['pr']}", "",
            "> **DRAFT. NOT POSTED.** Written to a local file only; no GitHub or other external service was contacted.", ""]
    if review["status"] == "llm_required":
        return "\n".join(head + ["Not generated: review drafting needs an LLM and no cached judgment exists.", ""])
    pv = review["provenance"]
    body = [f"**{review['title']}**", "",
            f"Provider `{pv['provider']}` · model `{pv['model']}` · search `{pv['search_mode']}` · live calls "
            f"{pv['model_calls_live']} · replayed {pv['replayed']} · comments {len(review['comments'])} · "
            f"discarded {len(review['dropped'])}", f"_Limitations: {pv['limitations']}_", ""]
    if not review["comments"]:
        body += ["**Nothing to say.** No comment was supported by evidence.", ""]
    for n, c in enumerate(review["comments"], 1):
        where = f"`{c['file']}`" if c["file"] else "whole PR"
        body += [f"### {n}. {c['type'].replace('_', ' ')} — {where} [{c['label']}]", "", c["comment"], ""]
        if c["quote"]:
            body += [f"> {c['quote']}", ""]
        for i in c["evidence"]:
            e = review["evidence"][i]
            body.append(f"- `{i}` ({e['kind']}, {e['status']}): {e['label'][:110]}" + (f" — {e['source']}" if e["source"] else ""))
        body.append("")
    if review["dropped"]:
        body += ["## Discarded by the evidence guard", ""] + [f"- {d['reason']}: {d['comment']}" for d in review["dropped"]] + [""]
    return "\n".join(head + body)


def main() -> int:
    import argparse

    from ..config import get_settings
    from ..db import connect
    from ..models.provider import make_provider

    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pr", type=int, required=True)
    a = ap.parse_args()
    s = get_settings()
    with connect() as conn:
        org = conn.execute("SELECT id FROM organizations WHERE slug=%s", (s.org_slug,)).fetchone()["id"]
        review = draft_review(conn, org, make_provider(s), a.repo, a.pr)
    out_dir = Path(__file__).resolve().parents[3] / "reviews" / s.org_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{a.repo}-PR{a.pr}"
    (out_dir / f"{stem}.md").write_text(render(review))
    (out_dir / f"{stem}.json").write_text(json.dumps(review, indent=2, default=str))
    print(f"{review['status']}: {len(review['comments'])} comment(s), {len(review.get('dropped', []))} discarded -> "
          f"reviews/{s.org_slug}/{stem}.md")
    return 0 if review["status"] == "draft" else 2


if __name__ == "__main__":
    raise SystemExit(main())
