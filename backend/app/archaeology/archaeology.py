"""Code archaeology and style profiles, computed from ingested sources (no model).

trail():   for a file, the chain that explains it: commits that touched it, the pull requests that changed it, the human
           discussion on those PRs, tickets they implement, and decisions the file or PRs mention.
profile(): code comments, docstrings and function style extracted from the file with the Python parser/tokenizer.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize

import psycopg

ADR_REF = re.compile(r"ADR-\d+")   # nominates mentions; the record itself is shown, no judgment is made here


def profile(text: str) -> dict:
    """Comments, docstrings and function style of one Python file. Non-Python or unparsable files return empty lists."""
    out = {"comments": [], "functions": [], "classes": [], "module_doc": None, "style": {}}
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return out
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT and not tok.string.startswith("#!"):
                out["comments"].append({"line": tok.start[0], "text": tok.string.lstrip("# ").rstrip()})
    except (tokenize.TokenError, IndentationError):
        pass
    out["module_doc"] = ast.get_docstring(tree)
    fn_nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for n in fn_nodes:
        args = [a for a in n.args.args + n.args.kwonlyargs if a.arg not in ("self", "cls")]
        doc = ast.get_docstring(n)
        out["functions"].append({
            "name": n.name, "line": n.lineno, "async": isinstance(n, ast.AsyncFunctionDef),
            "args": len(args), "annotated_args": sum(1 for a in args if a.annotation is not None),
            "returns_annotated": n.returns is not None, "doc": (doc or "").split("\n")[0] or None,
            "decorators": [ast.unparse(d) for d in n.decorator_list], "lines": (n.end_lineno or n.lineno) - n.lineno + 1})
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef):
            out["classes"].append({"name": n.name, "line": n.lineno, "doc": (ast.get_docstring(n) or "").split("\n")[0] or None,
                                   "bases": [ast.unparse(b) for b in n.bases]})
    fs = out["functions"]
    total_args = sum(f["args"] for f in fs)
    out["style"] = {
        "functions": len(fs), "classes": len(out["classes"]), "comment_lines": len(out["comments"]),
        "args_annotated": sum(f["annotated_args"] for f in fs), "args_total": total_args,
        "returns_annotated": sum(1 for f in fs if f["returns_annotated"]),
        "with_docstring": sum(1 for f in fs if f["doc"]),
        "snake_case": sum(1 for f in fs if re.fullmatch(r"_{0,2}[a-z0-9]+(_[a-z0-9]+)*_{0,2}", f["name"])),
        "async": sum(1 for f in fs if f["async"]), "lines": text.count("\n") + 1}
    return out


def trail(conn: psycopg.Connection, org: int, repo: str, path: str) -> dict | None:
    rec = conn.execute("SELECT id, source_id, title, body, source_url FROM source_records WHERE organization_id=%s AND "
                       "source_type='file' AND source_id=%s", (org, f"{repo}:{path}")).fetchone()
    if not rec:
        return None
    events = []
    for r in conn.execute("SELECT id, source_id, title, source_url, payload FROM source_records WHERE organization_id=%s "
                          "AND source_type='github_commit'", (org,)):
        p = r["payload"]
        if p.get("repo") == repo and path in p.get("files", []):
            events.append({"when": p.get("date"), "kind": "commit", "id": f"record:{r['id']}", "title": p.get("message"),
                           "who": p.get("author"), "url": r["source_url"], "ref": r["source_id"][:10]})
    prs = {}
    for r in conn.execute("SELECT id, source_id, title, body, source_url, payload FROM source_records WHERE organization_id=%s "
                          "AND source_type='github_pr'", (org,)):
        p = r["payload"]
        if p.get("repo") == repo and path in p.get("files", []):
            prs[r["source_id"]] = r
            events.append({"when": p.get("merged_at"), "kind": "pull_request", "id": f"record:{r['id']}", "title": r["title"],
                           "who": p.get("author"), "url": r["source_url"], "ref": r["source_id"], "body": r["body"]})
    tickets = {}
    for pr in prs.values():
        for k in pr["payload"].get("linked_tickets", []):
            tickets[k] = pr["source_id"]
    for k, via in tickets.items():
        t = conn.execute("SELECT id, title, source_url, payload FROM source_records WHERE organization_id=%s AND "
                         "source_type='jira_issue' AND source_id=%s", (org, k)).fetchone()
        if t:
            events.append({"when": t["payload"].get("updated"), "kind": "ticket", "id": f"record:{t['id']}", "title": t["title"],
                           "who": t["payload"].get("assignee"), "url": t["source_url"], "ref": k, "via": via})
    if prs:
        for r in conn.execute("SELECT id, source_id, title, body, source_url, payload FROM source_records WHERE "
                              "organization_id=%s AND source_type='github_comment'", (org,)):
            p = r["payload"]
            if f"{p.get('repo')}#{p.get('number')}" in prs:
                events.append({"when": p.get("date"), "kind": "discussion", "id": f"record:{r['id']}", "title": r["title"],
                               "who": p.get("author"), "url": r["source_url"], "ref": f"{p['repo']}#{p['number']}",
                               "body": r["body"], "path": p.get("path"), "via": f"{p['repo']}#{p['number']}"})
    mentioned = set(ADR_REF.findall(rec["body"] or "")) | {a for pr in prs.values() for a in ADR_REF.findall(pr["body"] or "")}
    for adr in sorted(mentioned):
        d = conn.execute("SELECT s.id, s.title, s.source_url, (SELECT f.status FROM facts f WHERE f.organization_id=s.organization_id "
                         "AND f.fact_type='decision' AND f.source_type='adr' AND f.source_id=s.source_id LIMIT 1) AS status "
                         "FROM source_records s WHERE s.organization_id=%s AND s.source_type='adr' AND s.source_id=%s",
                         (org, adr)).fetchone()
        if d:
            events.append({"when": None, "kind": "decision", "id": f"record:{d['id']}", "title": d["title"], "who": None,
                           "url": d["source_url"], "ref": adr, "status": d["status"]})
    events.sort(key=lambda e: (e["when"] is None, e["when"] or "", e["kind"]))
    return {"repo": repo, "path": path, "url": rec["source_url"], "profile": profile(rec["body"] or ""), "events": events}


def explain(conn: psycopg.Connection, org: int, provider, repo: str, path: str) -> dict | None:
    """A model-written account of why the file looks the way it does, over its own trail. Every point must cite trail items."""
    from ..intelligence import tasks as T
    from ..intelligence.guards import exact, highlight
    from ..intelligence.judge import run_task
    from ..models.provider import LLMUnavailable

    t = trail(conn, org, repo, path)
    if t is None:
        return None
    if not provider.has_llm:
        return {"status": "llm_required", "trail": t, "note": "The explanation needs a language model; the history is shown without one."}
    items = {e["id"]: e for e in t["events"]}
    payload = {"file": f"{repo}/{path}", "style": t["profile"]["style"],
               "comments_in_code": [c["text"] for c in t["profile"]["comments"][:12]],
               "history": [{"id": e["id"], "kind": e["kind"], "date": e["when"], "who": e["who"], "title": e["title"],
                            "status": e.get("status"), "text": (e.get("body") or "")[:900]} for e in t["events"][-40:]]}
    try:
        res = run_task(conn, org, provider, "trace_explain", T.TRACE_EXPLAIN["system"], payload, T.TRACE_EXPLAIN["schema"])
    except LLMUnavailable as exc:
        return {"status": "llm_required", "trail": t, "note": str(exc)}

    def clean(seg):
        ids = [i for i in dict.fromkeys(seg.get("cites") or []) if i in items]
        text = (seg.get("text") or "").strip()
        return {"text": text, "cites": ids, "key": highlight(seg.get("key", ""), text)} if text and ids else None

    head = clean(res.get("headline") or {})
    points = [p for p in (clean(x) for x in res.get("points", [])) if p]
    return {"status": "ok" if head or points else "insufficient", "headline": head, "points": points, "trail": t}
