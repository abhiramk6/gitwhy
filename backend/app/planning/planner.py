"""Evidence-bound feature planner.

Pipeline: retrieve -> locate services -> bounded impact traversal -> collect constraints/risks/reuse ->
rule-built plan with an evidence registry -> optional model polish (guarded) -> persist.

Every claim carries a label (verified | inferred | proposed) and evidence ids that exist in the registry.
A model may reword, but it may not add claims: output with unknown evidence ids is discarded.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

import psycopg

from ..graph.impact import impact
from ..models.provider import Provider
from ..retrieval.search import search

PATH_RE = re.compile(r"/v\d+/[a-z][a-z\-]*")


class Evidence:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def add(self, eid: str, kind: str, label: str, url: str | None, evidence_type: str, status: str = "active") -> str:
        self.items.setdefault(eid, {"id": eid, "kind": kind, "label": label, "source": url,
                                    "evidence_type": evidence_type, "status": status})
        return eid


def _label(evidence_type: str, status: str) -> str:
    return "verified" if evidence_type in ("structural", "explicit") and status == "active" else "inferred"


def _primary_services(conn, org, request: str, hits) -> tuple[dict[str, float], dict[str, str]]:
    pts: Counter = Counter()
    why: dict[str, str] = {}
    # Only corroborated evidence earns anchor points: an identifier hit, or keyword AND vector agreement.
    # A single weak signal counts half; graph-expansion-only hits count nothing (they follow seeds, not the request).
    strong_hits = [h for h in hits if "identifier" in h.signals or ("keyword" in h.signals and "vector" in h.signals)]
    for h in hits[:12]:  # (a) repository of retrieved evidence
        if h.repo:
            w = 1.0 if h in strong_hits else 0.5 if ("keyword" in h.signals or "vector" in h.signals) else 0.0
            if w:
                pts[h.repo] += w
                why.setdefault(h.repo, f"retrieved evidence from {h.repo}")
    texts = request + " " + " ".join(h.snippet + " " + h.title for h in strong_hits[:8])
    eps = conn.execute("SELECT e.canonical_name, r.name AS repo FROM entities e JOIN repositories r ON r.id=e.repository_id "
                       "WHERE e.organization_id=%s AND e.entity_type='endpoint'", (org,)).fetchall()
    for path in set(PATH_RE.findall(texts)):  # (c) API path mentioned => owning service
        for ep in eps:
            if ep["canonical_name"].split(" ", 1)[1].startswith(path):
                pts[ep["repo"]] += 3
                why[ep["repo"]] = f"API path {path} is served by {ep['repo']}"
    proj = {r["k"]: r["repo"] for r in conn.execute(  # (b) ticket project -> service by implementing PRs
        "SELECT split_part(t.canonical_name,'-',1) AS k, s.canonical_name AS repo, count(*) n FROM entities t "
        "JOIN edges i ON i.src_id IS NOT NULL AND i.dst_id=t.id AND i.rel_type='implements' "
        "JOIN entities pr ON pr.id=i.src_id JOIN repositories rp ON rp.id=pr.repository_id "
        "JOIN entities s ON s.entity_type='service' AND s.canonical_name=rp.name AND s.organization_id=t.organization_id "
        "WHERE t.organization_id=%s AND t.entity_type='ticket' GROUP BY 1,2 ORDER BY n DESC", (org,))}
    seen_projects: set[str] = set()  # many tickets from one project are one piece of evidence, not many
    for h in strong_hits[:12]:
        key = h.source_id.split("-")[0]
        if h.source_type == "jira_issue" and key in proj and key not in seen_projects:
            seen_projects.add(key)
            pts[proj[key]] += 2
            why[proj[key]] = f"{h.source_id} belongs to the {key} project (implemented in {proj[key]})"
    names = [r["name"] for r in conn.execute("SELECT name FROM repositories WHERE organization_id=%s", (org,))]
    for name in names:  # a service named in the request is a grounded anchor
        if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", request.lower()):
            pts[name] += 3
            why[name] = f"{name} is named in the request"
    return pts, why


# A plan needs at least this much grounded evidence (named service, API path, ticket project, or several
# retrieved records from one repository). Weak lexical/vector matches alone must not produce a plan.
MIN_ANCHOR = 3
OWNERSHIP_CAP = 4


def create_plan(conn: psycopg.Connection, org_id: int, provider: Provider, request: str,
                depth: int = 3, persist: bool = True) -> dict:
    ev = Evidence()
    hits = search(conn, org_id, provider, request, k=12)
    pts, why = _primary_services(conn, org_id, request, hits)
    if not pts or max(pts.values()) < MIN_ANCHOR:
        return {"request": request, "status": "insufficient_evidence", "open_questions":
                ["No repository or service could be linked to this request. Name an API, ticket or component."]}
    top = max(pts.values())
    primary = sorted(s for s, p in pts.items() if p >= max(3, top * 0.6) and s != "platform-libs") or [pts.most_common(1)[0][0]]
    imp = impact(conn, org_id, primary, depth)
    libs = {"platform-libs"}
    deps = [d for d in imp["dependencies"] if d["service"] not in libs]
    dependents = [d for d in imp["dependents"] if d["service"] not in libs]
    affected_names = list(dict.fromkeys(primary + [d["service"] for d in deps] + [d["service"] for d in dependents]))
    all_services = affected_names + [d["service"] for d in imp["dependencies"] if d["service"] in libs]

    def edge_ev(path: dict) -> list[str]:
        return [ev.add(f"edge:{e['from']}->{e['to']}", "dependency", f"{e['from']} depends on {e['to']}",
                       e["source"], e["evidence_type"]) for e in path["evidence"]]

    components = []
    for s in primary:
        components.append({"service": s, "role": "primary", "reason": why.get(s, "primary match"), "label": "inferred",
                           "evidence": [ev.add(f"hit:{s}", "retrieval", why.get(s, "retrieved"), None, "inferred")]})
    for d in deps:
        components.append({"service": d["service"], "role": "downstream-dependency",
                           "reason": " -> ".join(d["path"]), "label": "verified", "evidence": edge_ev(d)})
    for d in dependents:
        components.append({"service": d["service"], "role": "upstream-consumer",
                           "reason": " -> ".join(reversed(d["path"])), "label": "verified", "evidence": edge_ev(d)})
    for d in imp["dependencies"]:
        if d["service"] in libs:
            components.append({"service": d["service"], "role": "shared-library", "reason": " -> ".join(d["path"]),
                               "label": "verified", "evidence": edge_ev(d)})
            break

    repo_ids = [r["id"] for r in conn.execute("SELECT id FROM repositories WHERE organization_id=%s AND name = ANY(%s)",
                                              (org_id, all_services))]
    facts = conn.execute("SELECT f.*, r.name AS repo FROM facts f LEFT JOIN repositories r ON r.id=f.repository_id "
                         "WHERE f.organization_id=%s AND f.status IN ('active','candidate','superseded') ORDER BY f.id",
                         (org_id,)).fetchall()
    svc_entity = {r["canonical_name"]: r["id"] for r in conn.execute(
        "SELECT id, canonical_name FROM entities WHERE organization_id=%s AND entity_type='service'", (org_id,))}
    applies = defaultdict(set)  # decision entity id -> services
    for r in conn.execute("SELECT src_id, dst_id FROM edges WHERE organization_id=%s AND rel_type='applies_to'", (org_id,)):
        applies[r["src_id"]].add(r["dst_id"])
    affected_ids = {svc_entity[s] for s in all_services if s in svc_entity}
    adr_ent = {r["canonical_name"]: r["id"] for r in conn.execute(
        "SELECT id, canonical_name FROM entities WHERE organization_id=%s AND entity_type='decision'", (org_id,))}

    def fact_ev(f) -> str:
        return ev.add(f"fact:{f['id']}", f["fact_type"], f["summary"][:100], f["source_url"], f["evidence_type"], f["status"])

    decisions, risks, reuse, questions, stale = [], [], [], [], []
    owner_facts: list = []
    for f in facts:
        lbl = _label(f["evidence_type"], f["status"])
        if f["fact_type"] == "decision":
            hit = bool(applies.get(f["subject_id"], set()) & affected_ids) or f["scope"] == "org" and not applies.get(f["subject_id"])
            if hit and f["status"] == "active":
                decisions.append({"adr": f["object_value"], "summary": f["summary"], "label": lbl, "evidence": [fact_ev(f)]})
            elif f["status"] == "superseded" and applies.get(f["subject_id"], set()) & affected_ids:
                stale.append(f)
        elif f["fact_type"] in ("risk", "override", "ownership", "conflict") and f["status"] in ("active", "candidate"):
            relevant = f["repository_id"] in repo_ids or any(s in f["summary"] for s in all_services)
            if f["fact_type"] == "risk" and f["predicate"] == "migration_blocks_feature":
                relevant = any(h.source_id == f["object_value"] or h.source_id in f["summary"] for h in hits) or \
                    any(k in request for k in re.findall(r"[A-Z]+-\d+", f["summary"]))
                relevant = relevant or any(h.snippet and f["object_value"] in h.snippet for h in hits)
            if f["fact_type"] == "conflict":  # relevant when any conflicting ADR applies to an affected service
                relevant = any(applies.get(adr_ent.get(a), set()) & affected_ids for a in f["object_value"].split("+"))
            if relevant and f["fact_type"] == "ownership":
                owner_facts.append(f)  # capped below: large codebases have many bus-factor facts
            elif relevant:
                item = {"type": f["fact_type"], "summary": f["summary"], "label": lbl, "evidence": [fact_ev(f)]}
                (questions if f["fact_type"] == "conflict" else risks).append(item)
        elif f["fact_type"] == "reuse" and f["status"] == "candidate":
            if any(s in f["object_value"] for s in all_services):
                reuse.append({"summary": f["summary"], "label": "inferred", "evidence": [fact_ev(f)]})

    # ownership risks: keep the most relevant few (file named in retrieval hits > primary service > confidence)
    hit_files = {h.source_id for h in hits}

    def _rank(f):
        return (f["object_value"] not in hit_files and not any(s in f["object_value"] for s in hit_files),
                f["repo"] not in primary, -float(f["confidence"]), f["id"])
    for f in sorted(owner_facts, key=_rank)[:OWNERSHIP_CAP]:
        risks.append({"type": "ownership", "summary": f["summary"], "label": _label(f["evidence_type"], f["status"]),
                      "evidence": [fact_ev(f)]})
    if len(owner_facts) > OWNERSHIP_CAP:
        questions.append({"type": "question", "summary": f"{len(owner_facts) - OWNERSHIP_CAP} further ownership/bus-factor facts apply to "
                                     "the affected services; see the Knowledge page.", "label": "proposed", "evidence": []})

    # stale references: affected code that cites a superseded decision
    superseded = {f["object_value"]: f for f in facts if f["fact_type"] == "decision" and f["status"] == "superseded"}
    for r in conn.execute("SELECT s.source_id, s.source_url, s.body FROM source_records s JOIN repositories rp ON rp.id=s.repository_id "
                          "WHERE s.organization_id=%s AND s.source_type='file' AND rp.name = ANY(%s)", (org_id, all_services)):
        for adr in set(re.findall(r"ADR-\d+", r["body"])):
            if adr in superseded:
                succ = conn.execute("SELECT object_value FROM facts WHERE id=%s", (superseded[adr]["superseded_by"],)).fetchone()
                e1 = ev.add(f"file:{r['source_id']}", "code", f"{r['source_id']} cites {adr}", r["source_url"], "structural")
                risks.append({"type": "stale_reference", "label": "verified", "evidence": [e1, fact_ev(superseded[adr])],
                              "summary": f"{r['source_id']} still follows superseded {adr}"
                                         + (f"; current decision is {succ['object_value']}." if succ else ".")})

    # tickets blocking the feature (explicit edges), for task ordering
    blockers = conn.execute(
        "SELECT DISTINCT b.canonical_name AS key, b.attributes->>'summary' AS summary, b.attributes->>'status' AS status "
        "FROM entities t JOIN edges e ON e.src_id=t.id AND e.rel_type='blocked_by' JOIN entities b ON b.id=e.dst_id "
        "WHERE t.organization_id=%s AND t.canonical_name = ANY(%s) AND b.attributes->>'status' <> 'Done'",
        (org_id, [h.source_id for h in hits if h.source_type == "jira_issue"])).fetchall()

    tasks: list[dict] = []

    def task(title, service, deps_, evidence, why_):
        t = {"id": f"T{len(tasks) + 1}", "title": title, "service": service, "depends_on": deps_,
             "label": "proposed", "evidence": evidence, "rationale": why_}
        tasks.append(t)
        return t["id"]

    pre: list[str] = []
    for b in blockers:
        eid = ev.add(f"ticket:{b['key']}", "ticket", f"{b['key']}: {b['summary']}", None, "explicit")
        pre.append(task(f"Confirm schedule and completion of {b['key']} ({b['summary']}) before dependent schema work",
                        None, [], [eid], f"{b['key']} is {b['status']} and blocks the requested feature."))
    order = [d["service"] for d in deps if d["depth"] == 1 and d["service"] not in primary] + primary + \
            [d["service"] for d in dependents]
    last_of: dict[str, str] = {}
    for s in dict.fromkeys(order):
        comp = next(c for c in components if c["service"] == s)
        role_txt = {"primary": "Implement the feature core",
                    "downstream-dependency": "Assess whether supporting changes are needed",
                    "upstream-consumer": "Verify and adapt the consumer"}.get(comp["role"], "Adjust")
        dep_ids = list(pre) + [last_of[x] for x in last_of if x != s and comp["role"] != "downstream-dependency"]
        last_of[s] = task(f"{role_txt} in {s} for: {request}", s, dep_ids, comp["evidence"], comp["reason"])
    for r_ in reuse:
        task("Reuse the shared implementation instead of duplicating it: " + r_["summary"], None, [], r_["evidence"],
             "Candidate duplicate detected; confirm before coding.")
    for rk in risks:
        if rk["type"] == "stale_reference":
            task("Do not extend superseded design: " + rk["summary"], None, [], rk["evidence"], "Follow the current ADR.")
    tests = [{"service": s, "check": f"Contract and regression tests for {s} changes", "label": "proposed"}
             for s in dict.fromkeys(order)]

    plan = {
        "request": request, "status": "draft", "provider": provider.name,
        "assumptions": ["Plan is derived from ingested evidence only; proposed items need human approval."],
        "affected_components": components, "decisions": decisions, "risks": risks, "reuse_candidates": reuse,
        "open_questions": questions + [{"type": "question", "label": "proposed", "evidence": [],
                                        "summary": "Confirm the feature's acceptance criteria and rollout order with the owning teams."}],
        "tasks": tasks, "tests": tests, "related_work": [
            {"id": h.source_id, "title": h.title, "url": h.source_url} for h in hits if h.source_type in ("jira_issue", "github_pr")][:6],
        "evidence": ev.items,
    }
    plan = _guard(provider, plan)
    if persist:
        conn.execute("INSERT INTO feature_plans (organization_id, request_text, plan, model) VALUES (%s,%s,%s::jsonb,%s)",
                     (org_id, request, json.dumps(plan), provider.name))
    return plan


def unsupported_claims(plan: dict) -> list[str]:
    """Claims whose evidence ids are missing from the registry, or non-proposed claims without evidence."""
    bad = []
    reg = plan.get("evidence", {})
    for section in ("affected_components", "decisions", "risks", "reuse_candidates", "tasks", "open_questions"):
        for item in plan.get(section, []):
            ids = item.get("evidence", [])
            if any(i not in reg for i in ids):
                bad.append(f"{section}: unknown evidence in {item.get('summary') or item.get('title') or item.get('service')}")
            if item.get("label") in ("verified", "inferred") and not ids:
                bad.append(f"{section}: {item.get('label')} claim without evidence")
    return bad


def _guard(provider: Provider, plan: dict) -> dict:
    """Let the model polish wording; reject its output if it introduces unsupported claims."""
    try:
        polished = provider.generate_json(
            "Rewrite task titles and summaries for clarity. Do not add, remove or relabel claims or evidence ids.", plan)
    except Exception:
        return plan
    return polished if isinstance(polished, dict) and not unsupported_claims(polished) \
        and len(polished.get("tasks", [])) == len(plan["tasks"]) else plan
