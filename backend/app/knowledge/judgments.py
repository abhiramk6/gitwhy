"""Model judgments used while building the knowledge graph: decision conflicts, pull-request compliance, reuse.

Each judgment is nominated by structure (which decisions apply, which classes exist) and decided by the model.
Guards: ids must come from the candidate set; quotes must literally occur in the source text, otherwise the
finding is discarded. Results are stored as `inferred`/`candidate` unless the source itself states the fact.
"""
from __future__ import annotations

import ast
import re

from ..intelligence import tasks as T
from ..intelligence.judge import run_task
from ..models.provider import LLMUnavailable


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _quoted(quote: str, text: str) -> bool:
    return bool(_norm(quote)) and _norm(quote) in _norm(text)


def decision_conflicts(conn, org, provider, adrs: dict[str, dict], batch: int) -> list[dict]:
    """adrs: {adr: {"status","title","body","scope"}}. Returns validated conflict findings."""
    active = sorted(a for a, m in adrs.items() if m["status"] == "accepted")
    pairs = [(a, b) for i, a in enumerate(active) for b in active[i + 1:]]
    out = []
    for i in range(0, len(pairs), batch * 3):
        chunk = pairs[i:i + batch * 3]
        payload = {"pairs": [{"a": a, "b": b, "a_text": adrs[a]["body"], "b_text": adrs[b]["body"],
                              "a_scope": adrs[a]["scope"], "b_scope": adrs[b]["scope"]} for a, b in chunk]}
        res = run_task(conn, org, provider, "decision_pairs", T.DECISION_PAIRS["system"], payload,
                       T.DECISION_PAIRS["schema"])
        allowed = set(chunk)
        for p in res["pairs"]:
            key = tuple(sorted((p["a"], p["b"])))
            if key not in allowed or p["relation"] not in ("conflict", "supersedes"):
                continue
            if p["relation"] == "conflict" and not (_quoted(p["quote_a"], adrs[p["a"]]["body"]) and
                                                    _quoted(p["quote_b"], adrs[p["b"]]["body"])):
                continue  # the model must point at real sentences
            out.append({**p, "pair": key})
    return out


def pr_compliance(conn, org, provider, prs: list[dict], decisions: dict[str, dict], batch: int) -> list[dict]:
    """prs: [{id, repo, title, body, files}]; decisions: active decisions {adr: {title, body, scope}}."""
    out = []
    for i in range(0, len(prs), batch):
        part = prs[i:i + batch]
        payload = {"pull_requests": part, "decisions": [{"adr": a, "title": d["title"], "text": d["body"],
                                                         "scope": d["scope"]} for a, d in sorted(decisions.items())]}
        res = run_task(conn, org, provider, "pr_compliance", T.PR_COMPLIANCE["system"], payload,
                       T.PR_COMPLIANCE["schema"])
        by_id = {p["id"]: p for p in part}
        for f in res["findings"]:
            pr = by_id.get(f["pr"])
            if not pr or f["adr"] not in decisions or f["verdict"] != "violates":
                continue
            recorded = bool(f["override_recorded"]) and _quoted(f["override_quote"], pr["body"])
            out.append({"pr": f["pr"], "adr": f["adr"], "reason": f["reason"], "override": recorded,
                        "quote": f["override_quote"] if recorded else ""})
    return out


def review_guidance(conn, org, provider, comments: list[dict], batch: int) -> list[dict]:
    """comments: [{id, repo, pr, author, date, path, text}]. Returns guidance the model found, kept only when the id is
    a candidate and the quote literally occurs in that comment (otherwise discarded)."""
    out = []
    for i in range(0, len(comments), batch * 3):
        part = comments[i:i + batch * 3]
        res = run_task(conn, org, provider, "review_guidance", T.REVIEW_GUIDANCE["system"], {"comments": part},
                       T.REVIEW_GUIDANCE["schema"])
        by_id = {c["id"]: c for c in part}
        for g in res["guidance"]:
            c = by_id.get(g["id"])
            if not c or g["scope"] not in ("org", "repo") or not _quoted(g["quote"], c["text"]):
                continue
            out.append({**g, "comment": c})
    return out


def class_signatures(files) -> list[dict]:
    out = []
    for rec in files:
        try:
            tree = ast.parse(rec["body"])
        except (SyntaxError, ValueError, RecursionError):
            continue
        repo = rec["source_id"].split(":", 1)[0]
        for n in ast.walk(tree):
            if isinstance(n, ast.ClassDef):
                ms = sorted(m.name for m in n.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and not m.name.startswith("_"))
                if ms:
                    out.append({"id": f"{rec['source_id']}::{n.name}", "repo": repo, "methods": ms,
                                "doc": (ast.get_docstring(n) or "").split("\n\n")[0]})
    return out


def reuse_pairs(conn, org, provider, files, max_chars: int) -> list[dict]:
    sigs = class_signatures(files)
    import json
    if len(json.dumps(sigs)) <= max_chars:
        batches = [sigs]
    else:  # too big for one prompt: compare repositories pairwise
        repos = sorted({s["repo"] for s in sigs})
        batches = [[s for s in sigs if s["repo"] in (a, b)] for i, a in enumerate(repos) for b in repos[i + 1:]]
    out, ids = [], {s["id"]: s["repo"] for s in sigs}
    for b in batches:
        if len({s["repo"] for s in b}) < 2:
            continue
        res = run_task(conn, org, provider, "reuse_pairs", T.REUSE_PAIRS["system"], {"classes": b},
                       T.REUSE_PAIRS["schema"])
        for p in res["pairs"]:
            if p["existing"] in ids and p["duplicate"] in ids and ids[p["existing"]] != ids[p["duplicate"]]:
                out.append(p)
    return out


__all__ = ["decision_conflicts", "pr_compliance", "reuse_pairs", "LLMUnavailable"]
