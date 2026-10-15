"""Dev-case scoring against the three-bucket lists (eval/oss_dev_lists.json).

Decisions : required missing -> FAIL; excluded present -> FAIL; anything else present -> UNLISTED (reported for review).
Risks     : subject matches excluded_subjects -> FAIL; matches allowed_subjects -> ok; otherwise UNLISTED (review).
Reuse     : component in allowed_reuse_components -> ok; otherwise UNLISTED (review).
Exclusions win over allowances (fnmatch globs; '*' crosses '/'). Counts only; no percentages.
"""
from __future__ import annotations

import re
from fnmatch import fnmatchcase

_PATH = re.compile(r"\b([A-Za-z0-9_.-]+)/((?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9]+)\b")


def subjects_of(item: dict, evidence: dict, repos: set[str]) -> set[str]:
    """repo:path subjects an item is about, from its cited evidence ids and evidence text."""
    out: set[str] = set()
    for eid in item.get("evidence", []):
        if eid.startswith("file:"):
            out.add(eid[5:])
        e = evidence.get(eid) or {}
        for m in _PATH.finditer(f"{e.get('label', '')} {item.get('summary', '')}"):
            repo, path = m.group(1), m.group(2)
            if repo in repos:
                out.add(f"{repo}:{path}")
        src = e.get("source") or ""
        m = re.search(r"/([\w.-]+)/blob/[^/]+/(.+)$", src)
        if m and m.group(1) in repos:
            out.add(f"{m.group(1)}:{m.group(2)}")
    return out


def _match(subject: str, entries: list[dict]) -> dict | None:
    return next((e for e in entries if fnmatchcase(subject, e["glob"])), None)


def score_plan(plan: dict, case: dict, repos: set[str]) -> dict:
    ev = plan.get("evidence", {})
    adrs = [d["adr"] for d in plan.get("decisions", [])]
    req, exc = set(case.get("required_decisions", [])), set(case.get("excluded_decisions", []))
    res = {"decisions_missing": sorted(req - set(adrs)), "decisions_excluded_present": sorted(exc & set(adrs)),
           "decisions_unlisted": sorted(set(adrs) - req - exc),
           "risks_ok": 0, "risks_excluded": [], "risks_unlisted": [], "reuse_ok": 0, "reuse_unlisted": []}
    for r in plan.get("risks", []):
        subs = subjects_of(r, ev, repos)
        bad = [s for s in subs if _match(s, case.get("excluded_subjects", []))]
        if bad:
            res["risks_excluded"].append({"summary": r["summary"][:110], "subject": bad[0]})
        elif any(_match(s, case.get("allowed_subjects", [])) for s in subs):
            res["risks_ok"] += 1
        else:
            res["risks_unlisted"].append({"summary": r["summary"][:110], "subjects": sorted(subs)[:3]})
    allowed = {a["name"] for a in case.get("allowed_reuse_components", [])}
    for r in plan.get("reuse_candidates", []):
        named = {n for n in repos if re.search(rf"\b{re.escape(n)}\b", r["summary"])}
        if named and named <= allowed:
            res["reuse_ok"] += 1
        else:
            res["reuse_unlisted"].append({"summary": r["summary"][:110], "components": sorted(named)})
    res["fail"] = bool(res["decisions_missing"] or res["decisions_excluded_present"] or res["risks_excluded"])
    return res
