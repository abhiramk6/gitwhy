"""Change impact and decision map: "if I change X, what else could break, and which earlier decisions apply?"

Structure is deterministic and verified: the services that depend on the changed one come from graph edges, each with its evidence.
What a model adds is judgment, and every piece of it is guarded:
  - a service, rule or risk must cite evidence ids that exist in the packet;
  - a rule must quote its decision or reviewer statement literally, and a superseded decision is never a rule;
  - statements about what "could break" are labelled inferred; the dependency itself is labelled by its edge evidence.
The graph only knows dependencies that were recorded (manifests, imports, tickets); anything undeclared is outside its view and the
result says so.
"""
from __future__ import annotations

from collections import defaultdict

import psycopg

from ..graph.impact import impact
from ..intelligence import tasks as T
from ..intelligence.guards import highlight, occurs
from ..intelligence.judge import run_task
from ..models.provider import LLMUnavailable, Provider
from ..planning.planner import Evidence, _budget, _catalog, _label_for, _valid
from ..retrieval.search import search_with_meta

LIMITS = ["Only dependencies recorded in the graph are followed; calls that were never declared are not visible here.",
          "“Could break” is a model judgment from the cited sources and is marked inferred; the dependency itself is shown with its own evidence."]


def _open_tickets(conn, org: int, repos: list[str], ev: Evidence) -> list[dict]:
    keys = {r["k"] for r in conn.execute(
        "SELECT DISTINCT jsonb_array_elements_text(payload->'linked_tickets') AS k FROM source_records "
        "WHERE organization_id=%s AND source_type='github_pr' AND source_id ~ ('^(' || %s || ')#')", (org, "|".join(repos)))} if repos else set()
    out = []
    for t in conn.execute("SELECT source_id, title, payload, source_url FROM source_records WHERE organization_id=%s AND "
                          "source_type='jira_issue' AND (source_id = ANY(%s) OR payload->>'repo' = ANY(%s)) "
                          "AND coalesce(payload->>'status','') NOT IN ('Done','Closed','Resolved') ORDER BY source_id LIMIT 12",
                          (org, list(keys), repos)):
        eid = ev.add(f"ticket:{t['source_id']}", "ticket", f"{t['source_id']}: {t['title']}", t["source_url"], "explicit")
        out.append({"id": eid, "key": t["source_id"], "summary": t["title"], "status": t["payload"].get("status")})
    return out


def change_impact(conn: psycopg.Connection, org_id: int, provider: Provider, question: str, depth: int = 3) -> dict:
    ev = Evidence()
    hits, meta = search_with_meta(conn, org_id, provider, question, k=12)
    hit_items = []
    for h in hits:
        eid = ev.add(f"hit:{h.ref}", "retrieval", h.title, h.source_url, "inferred" if h.kind == "record" else (h.evidence_type or "inferred"))
        hit_items.append({"id": eid, "type": h.source_type, "repo": h.repo, "title": h.title, "status": h.status, "passage": h.snippet})
    hit_items, _ = _budget(hit_items, 9000)
    catalog = _catalog(conn, org_id)
    names = {c["name"] for c in catalog}
    base = {"question": question, "status": "draft", "provider": provider.name, "search_mode": meta["mode"], "limits": LIMITS}
    try:
        sel = run_task(conn, org_id, provider, "select_changed", T.SELECT_CHANGED["system"],
                       {"request": question, "services": catalog, "evidence": hit_items}, T.SELECT_CHANGED["schema"])
    except LLMUnavailable as exc:
        return {**base, "status": "llm_required", "explanation": str(exc)}
    seeds = list(dict.fromkeys(p["service"] for p in sel["primary_services"] if p["service"] in names))
    if sel["insufficient_evidence"] or not seeds:
        return {**base, "status": "insufficient_evidence", "explanation": sel.get("explanation") or
                "No service could be linked to this question. Name a component, API or ticket."}
    why = {p["service"]: p["reason"] for p in sel["primary_services"] if p["service"] in names}

    imp = impact(conn, org_id, seeds, depth)

    def edge_ids(path: dict) -> list[str]:
        return [ev.add(f"edge:{e['from']}->{e['to']}", "dependency", f"{e['from']} depends on {e['to']}", e["source"], e["evidence_type"])
                for e in path["evidence"]]

    comps: dict[str, dict] = {s: {"service": s, "role": "changed", "relationship": why.get(s, ""), "depth": 0,
                                  "evidence": [ev.add(f"service:{s}", "service", f"{s} (named by the question)", None, "inferred")]} for s in seeds}
    for d in imp["dependents"]:
        comps.setdefault(d["service"], {"service": d["service"], "role": "caller", "depth": d["depth"],
                                        "relationship": " depends on ".join(reversed(d["path"])), "path": list(reversed(d["path"])),
                                        "evidence": edge_ids(d)})
    for d in imp["dependencies"]:
        comps.setdefault(d["service"], {"service": d["service"], "role": "relied_on", "depth": d["depth"],
                                        "relationship": " depends on ".join(d["path"]), "path": d["path"], "evidence": edge_ids(d)})
    scope = list(comps)

    # candidate knowledge scoped by the graph, never by a relevance judgment
    repo_ids = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM repositories WHERE organization_id=%s AND name = ANY(%s)", (org_id, scope))}
    svc_entity = {r["canonical_name"]: r["id"] for r in conn.execute(
        "SELECT id, canonical_name FROM entities WHERE organization_id=%s AND entity_type='service'", (org_id,))}
    applies = defaultdict(set)
    for r in conn.execute("SELECT src_id, dst_id FROM edges WHERE organization_id=%s AND rel_type='applies_to'", (org_id,)):
        applies[r["src_id"]].add(r["dst_id"])
    scope_ids = {svc_entity[x] for x in scope if x in svc_entity}
    adr_body = {r["source_id"]: r["body"] for r in conn.execute("SELECT source_id, body FROM source_records WHERE organization_id=%s AND source_type='adr'", (org_id,))}
    rule_text: dict[str, str] = {}
    rule_meta: dict[str, dict] = {}
    decisions, guidance, risks = [], [], []
    for f in conn.execute("SELECT * FROM facts WHERE organization_id=%s AND status IN ('active','candidate','superseded') ORDER BY id", (org_id,)):
        if f["fact_type"] == "decision":
            if not applies.get(f["subject_id"]) or applies[f["subject_id"]] & scope_ids:
                eid = ev.add(f"fact:{f['id']}", "decision", f["summary"], f["source_url"], f["evidence_type"], f["status"])
                rule_text[eid] = adr_body.get(f["source_id"], f["summary"])
                rule_meta[eid] = {"kind": "decision", "adr": f["object_value"], "summary": f["summary"], "status": f["status"],
                                  "services": sorted(n for n, i in svc_entity.items() if i in applies.get(f["subject_id"], set()) & scope_ids)}
                decisions.append({"id": eid, "adr": f["object_value"], "status": f["status"], "summary": f["summary"], "text": rule_text[eid]})
        elif f["fact_type"] == "review_guidance" and f["status"] in ("active", "candidate") and (f["scope"] == "org" or f["repository_id"] in repo_ids):
            src = conn.execute("SELECT body, payload FROM source_records WHERE organization_id=%s AND source_type=%s AND source_id=%s",
                               (org_id, f["source_type"], f["source_id"])).fetchone() or {}
            eid = ev.add(f"fact:{f['id']}", "review_guidance", f["summary"], f["source_url"], f["evidence_type"], f["status"])
            rule_text[eid] = src.get("body") or f["summary"]
            who, when = (src.get("payload") or {}).get("author"), (src.get("payload") or {}).get("date")
            rule_meta[eid] = {"kind": "review", "summary": f["summary"], "status": f["status"], "who": who, "when": when,
                              "services": [repo_ids[f["repository_id"]]] if f["repository_id"] in repo_ids else []}
            guidance.append({"id": eid, "summary": f["summary"], "said_by": who, "date": when, "exact_words": rule_text[eid]})
        elif f["fact_type"] in ("ownership", "risk", "conflict") and f["status"] in ("active", "candidate") and \
                (f["repository_id"] in repo_ids or (f["fact_type"] == "conflict" and applies.get(f["subject_id"], set()) & scope_ids)):
            eid = ev.add(f"fact:{f['id']}", f["fact_type"], f["summary"], f["source_url"], f["evidence_type"], f["status"])
            risks.append({"id": eid, "type": f["fact_type"], "summary": f["summary"], "status": f["status"]})
    tickets = _open_tickets(conn, org_id, scope, ev)

    packet = {"question": question,
              "services": [{k: c[k] for k in ("service", "role", "relationship", "evidence")} for c in comps.values()],
              "decisions": decisions, "team_guidance": guidance, "risk_candidates": risks, "open_tickets": tickets,
              "retrieved_evidence": hit_items[:6]}
    try:
        raw = run_task(conn, org_id, provider, "change_impact", T.CHANGE_IMPACT["system"], packet, T.CHANGE_IMPACT["schema"])
    except LLMUnavailable as exc:
        return {**base, "status": "llm_required", "explanation": str(exc)}

    dropped: list[str] = []
    said = {}
    for a in raw.get("affected", []):
        c = comps.get(a.get("service"))
        ids = _valid(a.get("evidence"), ev)
        if not c or c["role"] == "changed" or not ids:
            dropped.append(f"affected {a.get('service')!r}: not a dependent in the graph, or no valid evidence")
            continue
        said[c["service"]] = {"what_could_break": a["what_could_break"].strip(), "evidence": ids}
    affected = []
    for c in comps.values():
        if c["role"] == "changed":
            continue
        j = said.get(c["service"])
        ids = list(dict.fromkeys(c["evidence"] + (j["evidence"] if j else [])))
        affected.append({"service": c["service"], "role": c["role"], "depth": c["depth"], "path": c.get("path"),
                         "relationship": c["relationship"], "what_could_break": j["what_could_break"] if j else None,
                         "label": "verified" if _label_for(ev, c["evidence"]) == "verified" else "inferred", "evidence": ids,
                         "judgment_label": "inferred" if j else None})
    rules = []
    for r in raw.get("rules", []):
        eid = r.get("evidence_id")
        if eid not in rule_text:
            dropped.append(f"rule {eid!r}: not a decision or reviewer statement in scope")
            continue
        if rule_meta[eid]["status"] == "superseded":
            dropped.append(f"rule {eid}: superseded, not guidance")
            continue
        if not occurs(r.get("quote", ""), rule_text[eid]):
            dropped.append(f"rule {eid}: quote not found in the source")
            continue
        rules.append({**rule_meta[eid], "id": eid, "why_it_matters": r["why_it_matters"].strip(), "quote": r["quote"].strip(),
                      "label": _label_for(ev, [eid]), "evidence": [eid]})
    out_risks = []
    for r in raw.get("risks", []):
        ids = _valid(r.get("evidence"), ev)
        if ids:
            out_risks.append({"type": r.get("type") or "risk", "summary": r["summary"].strip(), "label": _label_for(ev, ids), "evidence": ids})
        else:
            dropped.append(f"risk without valid evidence: {str(r.get('summary'))[:60]}")
    checks = []
    for c in raw.get("checks", []):
        ids = _valid(c.get("evidence"), ev)
        if ids:
            checks.append({"check": c["check"].strip(), "label": "proposed", "evidence": ids})
        else:
            dropped.append(f"check without valid evidence: {str(c.get('check'))[:60]}")

    nodes = [{"id": c["service"], "kind": {"changed": "changed", "caller": "caller", "relied_on": "relied_on"}[c["role"]]} for c in comps.values()]
    links = []
    for d in imp["dependents"] + imp["dependencies"]:
        for e in d["evidence"]:
            link = {"from": e["from"], "to": e["to"], "rel": "depends_on", "evidence_type": e["evidence_type"]}
            if link not in links:
                links.append(link)
    for r in rules:
        nodes.append({"id": r["id"], "kind": "decision" if r["kind"] == "decision" else "review", "label": r.get("adr") or "reviewer"})
        for s in r["services"] or seeds:
            links.append({"from": r["id"], "to": s, "rel": "governs"})
    used = {i for section in (affected, rules, out_risks, checks) for x in section for i in x["evidence"]}
    return {**base, "headline": {"text": raw["headline"].strip(), "key": highlight(raw.get("key", ""), raw["headline"])} if raw.get("headline") else None,
            "changed": [{"service": s, "reason": why.get(s, "")} for s in seeds], "affected": affected, "rules": rules, "risks": out_risks,
            "checks": checks, "open_tickets": tickets, "map": {"nodes": nodes, "links": links}, "dropped": dropped,
            "evidence": {i: ev.items[i] for i in used}}
