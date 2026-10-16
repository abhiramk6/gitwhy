"""Evidence-bound feature planner with a model making the judgments.

Pipeline
  1. retrieve   hybrid search (+ model query analysis and rerank when an LLM is configured)
  2. select     model chooses the primary services from the catalog, citing evidence (or says "insufficient")
  3. traverse   deterministic bounded impact walk over structural dependency edges
  4. gather     deterministic candidate decisions / risks / blockers for the affected services (graph facts)
  5. judge      model decides relevance, writes request-specific tasks, tests and questions, citing evidence ids
  6. guard      every cited id must exist; unknown services/decisions are dropped; the model never sets labels

Trust labels are derived from the cited evidence itself (structural/explicit + active => verified), never from
the model. Without an LLM the planner returns status `llm_required` instead of improvising a plan from rules.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

import psycopg

from ..config import get_settings
from ..graph.impact import impact
from ..intelligence import tasks as T
from ..intelligence.judge import run_task
from ..models.provider import LLMUnavailable, Provider
from ..retrieval.chunk import chunk_spans
from ..retrieval.search import search_with_meta

ADR_REF = re.compile(r"ADR-\d+")  # nominates candidate stale references; the model judges them


class Evidence:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def add(self, eid: str, kind: str, label: str, url: str | None, evidence_type: str, status: str = "active") -> str:
        self.items.setdefault(eid, {"id": eid, "kind": kind, "label": label, "source": url,
                                    "evidence_type": evidence_type, "status": status})
        return eid


def _label(evidence_type: str, status: str) -> str:
    return "verified" if evidence_type in ("structural", "explicit") and status == "active" else "inferred"


def _label_for(ev: Evidence, ids: list[str]) -> str:
    """verified only when every cited item is structural/explicit and active; otherwise inferred."""
    return "verified" if ids and all(_label(ev.items[i]["evidence_type"], ev.items[i]["status"]) == "verified"
                                     for i in ids) else "inferred"


def _valid(ids, ev: Evidence) -> list[str]:
    return [i for i in dict.fromkeys(ids or []) if i in ev.items]


def _catalog(conn, org: int) -> list[dict]:
    out = []
    for r in conn.execute("SELECT r.name, (SELECT s.body FROM source_records s WHERE s.repository_id=r.id AND "
                          "s.source_type='doc' AND upper(split_part(s.source_id, ':', 2)) LIKE 'README%%' "
                          "ORDER BY length(s.body) DESC LIMIT 1) AS readme FROM repositories r "
                          "WHERE r.organization_id=%s ORDER BY r.name", (org,)):
        body = r["readme"] or ""
        first = chunk_spans(body)[0]
        out.append({"name": r["name"], "description": body[first[0]:first[1]].strip()})
    return out


def _budget(items: list[dict], limit: int) -> tuple[list[dict], int]:
    kept, used = [], 0
    for it in items:
        size = len(json.dumps(it, ensure_ascii=False))
        if used + size > limit and kept:
            break
        kept.append(it)
        used += size
    return kept, len(items) - len(kept)


def create_plan(conn: psycopg.Connection, org_id: int, provider: Provider, request: str,
                depth: int = 3, persist: bool = True) -> dict:
    s = get_settings()
    ev = Evidence()
    hits, meta = search_with_meta(conn, org_id, provider, request, k=15)
    related = [{"id": h.source_id, "title": h.title, "url": h.source_url} for h in hits
               if h.source_type in ("jira_issue", "github_pr")]
    hit_items = []
    for h in hits:
        eid = ev.add(f"hit:{h.ref}", "retrieval", h.title, h.source_url, "inferred" if h.kind == "record" else
                     (h.evidence_type or "inferred"), "active")
        hit_items.append({"id": eid, "type": h.source_type, "repo": h.repo, "title": h.title, "status": h.status,
                          "passage": h.snippet})
    hit_items, omitted_hits = _budget(hit_items, s.evidence_budget_chars // 3)
    catalog = _catalog(conn, org_id)
    names = {c["name"] for c in catalog}

    try:
        sel = run_task(conn, org_id, provider, "select_services", T.SELECT_SERVICES["system"],
                       {"request": request, "services": catalog, "evidence": hit_items}, T.SELECT_SERVICES["schema"])
    except LLMUnavailable as exc:
        return {"request": request, "status": "llm_required", "related_work": related, "search_mode": meta["mode"],
                "open_questions": [{"type": "question", "label": "proposed", "evidence": [], "summary":
                                    f"Planning requires the LLM layer. {exc}"}]}
    primary_sel = [p for p in sel["primary_services"] if p["service"] in names]
    if sel["insufficient_evidence"] or not primary_sel:
        return {"request": request, "status": "insufficient_evidence", "search_mode": meta["mode"],
                "open_questions": [{"type": "question", "label": "proposed", "evidence": [],
                                    "summary": sel.get("explanation") or
                                    "No service could be linked to this request. Name a component, API or ticket."}]}
    primary = list(dict.fromkeys(p["service"] for p in primary_sel))
    why = {p["service"]: (p["reason"], _valid(p["evidence"], ev)) for p in primary_sel}

    # ---- deterministic structural traversal
    imp = impact(conn, org_id, primary, depth)

    def edge_ev(path: dict) -> list[str]:
        return [ev.add(f"edge:{e['from']}->{e['to']}", "dependency", f"{e['from']} depends on {e['to']}",
                       e["source"], e["evidence_type"]) for e in path["evidence"]]

    components: dict[str, dict] = {}
    for sv in primary:
        reason, eids = why[sv]
        components[sv] = {"service": sv, "role": "primary", "reason": reason, "label": "inferred",
                          "evidence": eids or [ev.add(f"hit:service:{sv}", "retrieval", reason, None, "inferred")]}
    for d in imp["dependencies"]:
        components.setdefault(d["service"], {"service": d["service"], "role": "downstream-dependency",
                                             "reason": " -> ".join(d["path"]), "label": "verified",
                                             "evidence": edge_ev(d)})
    for d in imp["dependents"]:
        components.setdefault(d["service"], {"service": d["service"], "role": "upstream-consumer",
                                             "reason": " -> ".join(reversed(d["path"])), "label": "verified",
                                             "evidence": edge_ev(d)})
    affected = set(components)

    # ---- candidate knowledge (graph-scoped, no relevance judgments)
    repo_ids = [r["id"] for r in conn.execute("SELECT id FROM repositories WHERE organization_id=%s AND name = ANY(%s)",
                                              (org_id, list(affected)))]
    svc_entity = {r["canonical_name"]: r["id"] for r in conn.execute(
        "SELECT id, canonical_name FROM entities WHERE organization_id=%s AND entity_type='service'", (org_id,))}
    applies = defaultdict(set)
    for r in conn.execute("SELECT src_id, dst_id FROM edges WHERE organization_id=%s AND rel_type='applies_to'", (org_id,)):
        applies[r["src_id"]].add(r["dst_id"])
    affected_ids = {svc_entity[x] for x in affected if x in svc_entity}
    hit_fact_ids = {h.id for h in hits if h.kind == "fact"}
    adr_body = {r["source_id"]: r["body"] for r in conn.execute(
        "SELECT source_id, body FROM source_records WHERE organization_id=%s AND source_type='adr'", (org_id,))}

    cand_decisions, cand_risks, cand_reuse, cand_conflicts = {}, {}, {}, {}
    for f in conn.execute("SELECT f.*, r.name AS repo FROM facts f LEFT JOIN repositories r ON r.id=f.repository_id "
                          "WHERE f.organization_id=%s AND f.status IN ('active','candidate','superseded') ORDER BY f.id",
                          (org_id,)):
        scoped = bool(applies.get(f["subject_id"], set()) & affected_ids)
        in_repo = f["repository_id"] in repo_ids
        if f["fact_type"] == "decision":
            if scoped or not applies.get(f["subject_id"]) or f["id"] in hit_fact_ids:
                eid = ev.add(f"fact:{f['id']}", "decision", f["summary"], f["source_url"], f["evidence_type"], f["status"])
                cand_decisions[f["object_value"]] = {"id": eid, "adr": f["object_value"], "status": f["status"],
                                                     "summary": f["summary"],
                                                     "text": adr_body.get(f["source_id"], f["summary"])}
        elif f["fact_type"] == "conflict":
            if scoped or f["id"] in hit_fact_ids:
                eid = ev.add(f"fact:{f['id']}", "conflict", f["summary"], f["source_url"], f["evidence_type"], f["status"])
                cand_conflicts[eid] = {"id": eid, "summary": f["summary"], "status": f["status"]}
        elif f["fact_type"] == "reuse":
            if in_repo or f["id"] in hit_fact_ids:
                eid = ev.add(f"fact:{f['id']}", "reuse", f["summary"], f["source_url"], f["evidence_type"], f["status"])
                cand_reuse[eid] = {"id": eid, "summary": f["summary"], "status": f["status"]}
        elif f["status"] in ("active", "candidate"):
            if in_repo or f["id"] in hit_fact_ids:
                eid = ev.add(f"fact:{f['id']}", f["fact_type"], f["summary"], f["source_url"], f["evidence_type"], f["status"])
                cand_risks[eid] = {"id": eid, "type": f["fact_type"], "summary": f["summary"], "status": f["status"],
                                   "evidence_type": f["evidence_type"]}
    # tickets that block tickets the request touches (structural edges)
    for b in conn.execute(
            "SELECT DISTINCT b.canonical_name AS key, b.attributes->>'summary' AS summary, b.attributes->>'status' AS status, "
            "t.canonical_name AS blocked FROM entities t JOIN edges e ON e.src_id=t.id AND e.rel_type='blocked_by' "
            "JOIN entities b ON b.id=e.dst_id WHERE t.organization_id=%s AND t.canonical_name = ANY(%s) "
            "AND b.attributes->>'status' <> 'Done'",
            (org_id, [h.source_id for h in hits if h.source_type == "jira_issue"])):
        eid = ev.add(f"ticket:{b['key']}", "ticket", f"{b['key']}: {b['summary']}", None, "explicit")
        cand_risks[eid] = {"id": eid, "type": "blocker", "status": "active", "evidence_type": "explicit",
                           "summary": f"{b['key']} ({b['summary']}) is {b['status']} and blocks {b['blocked']}."}
    # code in affected services that mentions a superseded decision id (candidate for a stale-reference judgment)
    gone = {a for a, d in cand_decisions.items() if d["status"] == "superseded"}
    stale = []
    if gone:
        for r in conn.execute("SELECT s.source_id, s.source_url, s.body FROM source_records s JOIN repositories rp "
                              "ON rp.id=s.repository_id WHERE s.organization_id=%s AND s.source_type='file' "
                              "AND rp.name = ANY(%s)", (org_id, list(affected))):
            for line in r["body"].splitlines():
                for adr in set(ADR_REF.findall(line)) & gone:
                    eid = ev.add(f"file:{r['source_id']}", "code", f"{r['source_id']} cites {adr}", r["source_url"],
                                 "structural")
                    stale.append({"id": eid, "file": r["source_id"], "cites": adr, "line": line.strip()})

    comp_items = [{"service": c["service"], "role": c["role"], "relationship": c["reason"], "evidence": c["evidence"]}
                  for c in components.values()]
    packet = {"request": request, "components": comp_items,
              "decisions": list(cand_decisions.values()), "risk_candidates": list(cand_risks.values()),
              "reuse_candidates": list(cand_reuse.values()), "conflicts": list(cand_conflicts.values()),
              "code_citing_superseded_decisions": stale,
              "retrieved_evidence": hit_items}
    # fit the prompt budget by shedding the lowest-ranked retrieved passages first
    while len(json.dumps(packet, ensure_ascii=False)) > s.evidence_budget_chars and len(packet["retrieved_evidence"]) > 1:
        packet["retrieved_evidence"].pop()
        omitted_hits += 1
    raw = run_task(conn, org_id, provider, "plan", T.PLAN["system"], packet, T.PLAN["schema"])

    # ---- guard: validate every model claim against the evidence registry and the candidate sets
    dropped: list[str] = []
    out_components = []
    judged = {c["service"]: c for c in raw.get("components", []) if c.get("service") in affected}
    for c in components.values():
        j = judged.get(c["service"])
        item = dict(c)
        if j:
            item["needs_change"] = j.get("needs_change")
            item["reason"] = j.get("reason") or c["reason"]
            item["evidence"] = list(dict.fromkeys(c["evidence"] + _valid(j.get("evidence"), ev)))
        out_components.append(item)
    for c in raw.get("components", []):
        if c.get("service") not in affected:
            dropped.append(f"component {c.get('service')!r} is not in scope")

    decisions = []
    for d in raw.get("decisions", []):
        cand = cand_decisions.get(d.get("adr"))
        ids = _valid(d.get("evidence"), ev)
        if not cand:
            dropped.append(f"decision {d.get('adr')!r} is not a candidate")
            continue
        if cand["status"] != "active":
            dropped.append(f"decision {d['adr']} is {cand['status']}, not guidance")
            continue
        ids = list(dict.fromkeys(ids + [cand["id"]]))
        decisions.append({"adr": d["adr"], "summary": cand["summary"], "guidance": d.get("guidance"),
                          "label": _label_for(ev, ids), "evidence": ids})

    risks = []
    known_types = {"risk", "override", "ownership", "conflict", "blocker", "stale_reference", "other"}
    for r in raw.get("risks", []):
        ids = _valid(r.get("evidence"), ev)
        if not ids:
            dropped.append(f"risk without valid evidence: {str(r.get('summary'))[:60]}")
            continue
        risks.append({"type": r.get("type") if r.get("type") in known_types else "other", "summary": r["summary"],
                      "label": _label_for(ev, ids), "evidence": ids})
    reuse = []
    for r in raw.get("reuse", []):
        ids = _valid(r.get("evidence"), ev)
        if ids:
            reuse.append({"summary": r["summary"], "label": "inferred", "evidence": ids})
        else:
            dropped.append(f"reuse claim without valid evidence: {str(r.get('summary'))[:60]}")

    task_ids: set[str] = set()
    tasks_out = []
    for t in raw.get("tasks", []):
        tid = t.get("id") or f"T{len(tasks_out) + 1}"
        if tid in task_ids:
            continue
        deps = [d for d in t.get("depends_on", []) if d in task_ids]  # forward/unknown references are dropped
        task_ids.add(tid)
        tasks_out.append({"id": tid, "title": t["title"],
                          "service": t["service"] if t.get("service") in affected else None,
                          "depends_on": deps, "label": "proposed", "evidence": _valid(t.get("evidence"), ev),
                          "rationale": t.get("rationale", "")})
    tests = [{"service": x["service"] if x.get("service") in affected else None, "check": x["check"],
              "label": "proposed", "evidence": _valid(x.get("evidence"), ev)} for x in raw.get("tests", [])]
    criteria = []
    for a in raw.get("acceptance_criteria", []):
        ids = _valid(a.get("evidence"), ev)
        if a.get("task") not in task_ids or not (a.get("criterion") or "").strip():
            dropped.append(f"acceptance criterion for unknown task {a.get('task')!r}")
            continue
        criteria.append({"task": a["task"], "criterion": a["criterion"].strip(), "label": "proposed", "evidence": ids})
    questions = [{"type": "question", "summary": q["question"], "label": "proposed",
                  "evidence": _valid(q.get("evidence"), ev)} for q in raw.get("open_questions", [])]
    for c in cand_conflicts.values():  # an active conflict touching the scope is never silently dropped
        if not any(c["id"] in q["evidence"] for q in questions) and not any(c["id"] in r["evidence"] for r in risks):
            questions.append({"type": "conflict", "summary": c["summary"], "label": "inferred", "evidence": [c["id"]]})

    assumptions = ["Plan is derived from ingested evidence only; proposed items need human approval."]
    if omitted_hits:
        assumptions.append(f"{omitted_hits} lower-ranked retrieved sources were left out to fit the evidence budget.")
    if dropped:
        assumptions.append(f"{len(dropped)} model claim(s) were discarded by the evidence guard.")
    plan = {
        "request": request, "status": "draft", "provider": provider.name, "search_mode": meta["mode"],
        "assumptions": assumptions, "affected_components": out_components, "decisions": decisions, "risks": risks,
        "reuse_candidates": reuse, "open_questions": questions, "tasks": tasks_out, "tests": tests,
        "acceptance_criteria": criteria,
        "related_work": related, "evidence": ev.items, "dropped_claims": dropped,
    }
    if persist:
        conn.execute("INSERT INTO feature_plans (organization_id, request_text, plan, model) VALUES (%s,%s,%s::jsonb,%s)",
                     (org_id, request, json.dumps(plan), provider.name))
    return plan


def unsupported_claims(plan: dict) -> list[str]:
    """Claims whose evidence ids are missing from the registry, or non-proposed claims without evidence."""
    bad = []
    reg = plan.get("evidence", {})
    for section in ("affected_components", "decisions", "risks", "reuse_candidates", "tasks", "open_questions", "acceptance_criteria"):
        for item in plan.get(section, []):
            ids = item.get("evidence", [])
            if any(i not in reg for i in ids):
                bad.append(f"{section}: unknown evidence in {item.get('summary') or item.get('title') or item.get('service')}")
            if item.get("label") in ("verified", "inferred") and not ids:
                bad.append(f"{section}: {item.get('label')} claim without evidence")
    return bad
