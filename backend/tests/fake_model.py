"""A scripted stand-in for a *correct* model, used to test wiring, guards and persistence.

It encodes the Northwind fixture's ground truth in the responders below. That is acceptable only because this
is a test double: nothing in app/ may contain this logic. Real model quality is measured with scripts/evaluate.py
against a live provider.
"""
import re

from app.models.testing import ScriptedProvider


def _header(text: str, key: str) -> str:
    m = re.search(rf"^{key}:\s*(.+)$", text, re.M | re.I)
    return m.group(1).strip() if m else ""


def query_analysis(p):
    return {"intent": "lookup", "search_queries": [p["question"]], "identifiers": [], "answer_sketch": p["question"]}


def rerank(p):
    return {"ranked": [{"id": c["id"], "relevance": 2, "reason": "candidate"} for c in p["candidates"]]}


def decision_pairs(p):
    out = []
    for x in p["pairs"]:
        ta, tb = _header(x["a_text"], "Topic"), _header(x["b_text"], "Topic")
        same = ta and ta == tb and x["a_scope"] != x["b_scope"]
        out.append({"a": x["a"], "b": x["b"], "relation": "conflict" if same else "unrelated",
                    "reason": f"both define the '{ta}' convention for different scopes",
                    "quote_a": f"Topic: {ta}" if same else "", "quote_b": f"Topic: {tb}" if same else ""})
    return {"pairs": out}


def pr_compliance(p):
    out = []
    for pr in p["pull_requests"]:
        if "requests" in pr["body"].lower() or "Override: ADR-004" in pr["body"]:
            ov = re.search(r"^Override:.*$", pr["body"], re.M)
            out.append({"pr": pr["id"], "adr": "ADR-004", "verdict": "violates", "override_recorded": bool(ov),
                        "override_quote": ov.group(0) if ov else "", "reason": "uses raw requests"})
    return {"findings": out}


def reuse_pairs(p):
    names = {c["id"]: c for c in p["classes"]}
    a = next((i for i in names if i.endswith("::IdempotencyStore")), None)
    b = next((i for i in names if i.endswith("::DedupeStore")), None)
    return {"pairs": [{"existing": a, "duplicate": b, "reason": "same interface"}] if a and b else []}


def make_select(choose=None):
    def select_services(p):
        names = [s["name"] for s in p["services"]]
        picked = choose(p) if choose else [n for n in names if n in p["request"]]
        if not picked:
            return {"primary_services": [], "insufficient_evidence": True, "explanation": "no service matches"}
        ev = [e["id"] for e in p["evidence"]][:1]
        return {"primary_services": [{"service": s, "reason": f"{s} is the target", "evidence": ev} for s in picked],
                "insufficient_evidence": False, "explanation": ""}
    return select_services


def plan(p):
    comps = [{"service": c["service"], "needs_change": "yes" if c["role"] == "primary" else "unknown",
              "reason": c["relationship"], "evidence": c["evidence"]} for c in p["components"]]
    decisions = [{"adr": d["adr"], "guidance": d["summary"], "evidence": [d["id"]]} for d in p["decisions"]
                 if d["status"] == "active"]
    risks = [{"type": r["type"], "summary": r["summary"], "evidence": [r["id"]]} for r in p["risk_candidates"]]
    risks += [{"type": "stale_reference", "summary": f"{s['file']} still follows {s['cites']}", "evidence": [s["id"]]}
              for s in p["code_citing_superseded_decisions"]]
    reuse = [{"summary": r["summary"], "evidence": [r["id"]]} for r in p["reuse_candidates"]]
    tasks = [{"id": f"T{i + 1}", "title": f"Change {c['service']} for: {p['request']}", "service": c["service"],
              "depends_on": [f"T{i}"] if i else [], "rationale": c["reason"], "evidence": c["evidence"]}
             for i, c in enumerate(comps)]
    return {"components": comps, "decisions": decisions, "risks": risks, "reuse": reuse, "tasks": tasks,
            "tests": [{"service": c["service"], "check": f"test {c['service']}", "evidence": c["evidence"]} for c in comps],
            "open_questions": [{"question": "Confirm acceptance criteria.", "evidence": []}]}


def ideal_provider(choose=None, semantic=False, **overrides) -> ScriptedProvider:
    r = {"query_analysis": query_analysis, "rerank": rerank, "decision_pairs": decision_pairs,
         "pr_compliance": pr_compliance, "reuse_pairs": reuse_pairs, "review_guidance": lambda p: {"guidance": []}, "select_services": make_select(choose),
         "plan": plan}
    r.update(overrides)
    return ScriptedProvider(r, semantic=semantic)
