"""Evidence-bound pull-request review drafts. LOCAL OUTPUT ONLY.

Drafts comments for one PR already in the corpus, using the team's decisions (including superseded ones), existing
compliance findings, ownership/bus-factor facts, dependency impact and runbooks. Same discipline as the planner:
  - a comment must cite evidence ids that exist in the registry, otherwise it is discarded;
  - 'decision_violation' needs a literal quote from the cited decision, otherwise it is discarded;
  - a violation of a superseded decision is never reported (a stale reference is, naming the replacement);
  - labels (verified/inferred) come from the cited evidence, never from the model;
  - when nothing is supported the draft says so. Silence beats a guess.
There is deliberately no network code in this module and no 'post' path: drafts are written to files under
reviews/ and nowhere else. A comment names a line only when the PR's stored diff shows it (verified literal match); otherwise it is file-level.

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
from . import diffs
from ..intelligence import tasks as T
from ..intelligence.judge import meter, run_task
from ..models.provider import LLMUnavailable, Provider
from ..planning.planner import Evidence, _label_for, _valid
from ..intelligence.guards import highlight as exact_phrase
from ..retrieval.search import search_with_meta

TYPES = {"decision_violation", "superseded_reference", "ownership_risk", "dependency_impact", "runbook_reminder",
         "missing_override", "reuse_opportunity", "past_guidance", "other"}
EVIDENCE_BUDGET_CHARS = 30_000
_WS = re.compile(r"\s+")
_ADR_DATE = re.compile(r"^\s*(?:\*\*)?date(?:\*\*)?\s*:\s*(\d{4}-\d{2}-\d{2})", re.I | re.M)
_ADR_WHO = re.compile(r"^\s*(?:\*\*)?(?:deciders?|author|decided[- ]by|owner)(?:\*\*)?\s*:\s*(.+)$", re.I | re.M)


def _norm(s: str) -> str:
    """Whitespace, case, markdown emphasis/code ticks and curly quotes are not content: quotes still must match words."""
    s = (s or "").replace("`", "").replace("*", "").translate(str.maketrans("\u2018\u2019\u201c\u201d", "''\"\""))
    return _WS.sub(" ", s).strip().lower()


def _short(quote: str, limit: int = 280) -> str:
    """A long quote is cut back to whole sentences from its start (still literal source words), so the card stays readable."""
    q = (quote or "").strip()
    if len(q) <= limit:
        return q
    cut = max((m.end() for m in re.finditer(r"[.!?](?=\s)", q) if m.end() <= limit), default=0)
    return q[:cut].strip() if cut else q[:limit].rsplit(" ", 1)[0] + "…"


def _trigger(words: str, title: str, body: str, patches: dict, files: list, imports: list) -> dict | None:
    """Where the model's trigger words literally occur in the PR: an added diff line, the description, the title or a file name."""
    hit = diffs.locate(patches, words) if patches else None
    if hit:
        return {"text": hit[2], "where": "diff", "file": hit[0], "line": hit[1]}
    for where, text in (("description", body), ("title", title), ("files", "\n".join(files)), ("imports", "\n".join(imports))):
        if _fits(words, text) and len(_norm(words)) >= 4:
            return {"text": words.strip(), "where": where}
    return None


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
    patches = payload.get("patches") or {}
    packet: dict = {"pull_request": {
        "id": pid, "repo": repo, "title": pr["title"], "description": pr["body"] or "", "files": files,
        "adds_imports": payload.get("adds_imports", []), "author": payload.get("author"),
        "labels": payload.get("labels", []), "linked_tickets": payload.get("linked_tickets", [])},
        "diff": diffs.digest(patches), "diff_available": bool(patches)}
    earlier: dict[str, dict] = {}  # who/when of each decision or reviewer statement, from the stored sources, not from the model

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
    others = {"existing_findings": [], "ownership": [], "reuse": [], "team_guidance": []}
    guidance_text: dict[str, str] = {}
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
                d, w = _ADR_DATE.search(text), _ADR_WHO.search(text)
                earlier[eid] = {"kind": "decision", "who": (f["author"] or (w.group(1).strip() if w else None)),
                                "when": d.group(1) if d else (f["valid_from"].date().isoformat() if f["valid_from"] else None),
                                "title": f["summary"], "source": f["source_url"]}
        elif f["source_type"] == "github_pr" and f["source_id"] == f"{repo}#{number}":
            eid = ev.add(f"fact:{f['id']}", f["fact_type"], f["summary"], f["source_url"], f["evidence_type"], f["status"])
            others["existing_findings"].append({"id": eid, "type": f["fact_type"], "predicate": f["predicate"],
                                                "status": f["status"], "summary": f["summary"]})
        elif f["fact_type"] == "review_guidance" and f["status"] in ("active", "candidate") and \
                (f["scope"] == "org" or f["repository_id"] == repo_id):
            src = conn.execute("SELECT body, payload FROM source_records WHERE organization_id=%s AND source_type=%s AND "
                               "source_id=%s", (org_id, f["source_type"], f["source_id"])).fetchone()
            said = ((src or {}).get("payload") or {}).get("date")
            if (said and payload.get("merged_at") and said >= payload["merged_at"]) or str(f["object_value"]).startswith(f"{repo}#{number}/"):
                continue  # guidance is only "earlier" if it was said before this PR merged, and never from this PR's own thread
            eid = ev.add(f"fact:{f['id']}", "review_guidance", f["summary"], f["source_url"], f["evidence_type"], f["status"])
            guidance_text[eid] = (src or {}).get("body") or f["summary"]
            earlier[eid] = {"kind": "review", "who": ((src or {}).get("payload") or {}).get("author"),
                            "when": ((src or {}).get("payload") or {}).get("date"), "title": f["summary"], "source": f["source_url"]}
            others["team_guidance"].append({"id": eid, "summary": f["summary"], "scope": f["scope"],
                                            "said_by": ((src or {}).get("payload") or {}).get("author"),
                                            "date": ((src or {}).get("payload") or {}).get("date"),
                                            "exact_words": guidance_text[eid]})
        elif f["fact_type"] == "reuse" and f["repository_id"] == repo_id and f["status"] in ("active", "candidate"):
            eid = ev.add(f"fact:{f['id']}", "reuse", f["summary"], f["source_url"], f["evidence_type"], f["status"])
            others["reuse"].append({"id": eid, "summary": f["summary"], "status": f["status"]})
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
    return packet, ev, {"search_mode": meta["mode"], "decision_text": decision_text, "guidance_text": guidance_text,
                     "files": files, "patches": patches, "earlier": earlier, "imports": payload.get("adds_imports", [])}


def draft_review(conn: psycopg.Connection, org_id: int, provider: Provider, repo: str, number: int) -> dict:
    before = meter.snapshot()
    packet, ev, aux = build_packet(conn, org_id, provider, repo, number)
    try:
        raw = run_task(conn, org_id, provider, "pr_review", T.PR_REVIEW["system"], packet, T.PR_REVIEW["schema"])
    except LLMUnavailable as exc:
        return {"status": "llm_required", "repo": repo, "pr": number, "explanation": str(exc), "comments": []}
    comments, dropped = [], []
    pr_title, pr_body = packet["pull_request"]["title"], packet["pull_request"]["description"]
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
        if ctype == "past_guidance":
            cited = [i for i in ids if i in aux["guidance_text"]]
            if not cited or not any(_fits(c.get("quote", ""), aux["guidance_text"][i]) for i in cited):
                dropped.append({"reason": "past guidance not cited, or quote not in the reviewer's words",
                                "comment": c.get("comment", "")[:120]})
                continue
        trig = None
        if ctype in ("decision_violation", "past_guidance"):
            trig = _trigger(c.get("trigger", ""), pr_title, pr_body, aux["patches"], aux["files"], aux["imports"])
            if not trig:
                dropped.append({"reason": "nothing in the PR (title, description or added lines) matches what the earlier words warn against",
                                "comment": c.get("comment", "")[:120]})
                continue
        if ctype == "reuse_opportunity" and not any(ev.items[i]["kind"] == "reuse" for i in ids):
            dropped.append({"reason": "reuse suggestion does not cite a reuse finding", "comment": c.get("comment", "")[:120]})
            continue
        if ctype == "dependency_impact" and any(x["type"] == "dependency_impact" for x in comments):
            dropped.append({"reason": "duplicate dependency impact (one blast-radius note per PR)",
                            "comment": c.get("comment", "")[:120]})
            continue
        if ctype == "dependency_impact":
            # Impact means CONSUMERS of the changed service: a cited edge must end at it (X depends on <repo>).
            if not any(i.startswith("edge:") and i.rsplit("->", 1)[-1] == repo for i in ids):
                dropped.append({"reason": "dependency impact does not cite a consumer of the changed service",
                                "comment": c.get("comment", "")[:120]})
                continue
        file = c.get("file") or ""
        if file and file not in aux["files"] and file not in aux["patches"]:
            file = ""  # we only know changed files; never point at a file the PR does not touch
        key = (ctype, file, _norm(c.get("comment", "")))
        if key in seen or not c.get("comment", "").strip():
            continue
        # line-level only when the model's literal added line really sits in the stored diff; the number comes from the hunks
        hit = diffs.locate(aux["patches"], c.get("diff_quote", ""), file) if aux["patches"] else None
        if not hit and diffs.claims_a_line(c.get("comment", "") + " " + c.get("why_conflict", "")):
            dropped.append({"reason": "names a line that the stored diff does not show", "comment": c.get("comment", "")[:120]})
            continue
        if hit:
            file = hit[0]
        seen.add(key)
        src_id = next((i for i in ids if i in aux["earlier"]), None)
        comments.append({"type": ctype, "file": file or None, "comment": c["comment"].strip(),
                         "why": (c.get("why_conflict") or "").strip() or None, "trigger": trig,
                         "earlier": ({**aux["earlier"][src_id], "id": src_id, "quote": _short(c.get("quote")) or None} if src_id and ctype in
                                     ("decision_violation", "past_guidance", "superseded_reference") else None),
                         "in_pr": ({"file": hit[0], "line": hit[1], "text": hit[2]} if hit else None),
                         "key": exact_phrase(c.get("key", ""), c["comment"]),
                         "quote": (_short(c.get("quote")) or None) if ctype in ("decision_violation", "past_guidance") else None,
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
                           "diff": bool(aux["patches"]),
                           "limitations": ("line-level comments only where the stored diff shows the line; elsewhere file-level"
                                           if aux["patches"] else "file-level only: no diff is stored for this PR, so no comment claims a line")}}


def render(review: dict) -> str:
    head = [f"# DRAFT review — {review['repo']}#{review['pr']}", "",
            "> **DRAFT. NOT POSTED.** Written to a local file only; no GitHub or other external service was contacted.", ""]
    if review["status"] == "llm_required":
        return "\n".join(head + ["Not generated: review drafting needs an LLM and no cached judgment exists.", ""])
    pv = review["provenance"]
    body = [f"**{review['title']}**", "",
            f"Provider `{pv["provider"]}` · model `{pv['model']}` · search `{pv['search_mode']}` · live calls "
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
