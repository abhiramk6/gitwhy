"""Derive the entity/edge graph and curated facts from ingested source_records.

Deterministic only (AST + parsed ADR/Jira/PR metadata). Every edge/fact carries provenance and an
evidence_type: `structural` (parsed from code), `explicit` (stated in a document/ticket), or `inferred`.
Inferred claims are stored as `candidate` and must never be displayed as verified.
Idempotent: every write is an upsert on a natural key.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

import psycopg

from ..config import get_settings
from ..models.provider import LLMUnavailable
from . import judgments

URL_HOST = re.compile(r"https?://([A-Za-z0-9][A-Za-z0-9.-]*)")  # first DNS label naming a known service = HTTP call


@dataclass
class BuildStats:
    entities: int = 0
    edges: int = 0
    facts: int = 0
    retired: int = 0
    by_fact_type: dict[str, int] = field(default_factory=dict)
    judgments: dict[str, object] = field(default_factory=dict)


class Builder:
    def __init__(self, conn: psycopg.Connection, org_id: int):
        self.c, self.org = conn, org_id
        self.ent: dict[tuple[str, str], int] = {}
        self.stats = BuildStats()
        self.fact_ids: set[int] = set()
        self.repo_id = {r["name"]: r["id"] for r in conn.execute(
            "SELECT id, name FROM repositories WHERE organization_id=%s", (org_id,))}

    # ---- primitives
    def entity(self, etype: str, name: str, repo: str | None = None, **attrs) -> int:
        key = (etype, name)
        if key in self.ent:
            return self.ent[key]
        row = self.c.execute(
            "INSERT INTO entities (organization_id, repository_id, entity_type, canonical_name, attributes) "
            "VALUES (%s,%s,%s,%s,%s::jsonb) ON CONFLICT (organization_id, entity_type, canonical_name) "
            "DO UPDATE SET attributes = EXCLUDED.attributes, updated_at = now() RETURNING id",
            (self.org, self.repo_id.get(repo), etype, name, json.dumps(attrs, sort_keys=True))).fetchone()
        self.ent[key] = row["id"]
        self.stats.entities += 1
        return row["id"]

    def edge(self, src: int, dst: int, rel: str, evidence: str, ref: str, confidence: float = 1.0,
             status: str = "active", source_record_id: int | None = None) -> None:
        if src == dst:
            return
        self.c.execute(
            "INSERT INTO edges (organization_id, src_id, dst_id, rel_type, evidence_type, status, confidence,"
            " source_ref, source_record_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (organization_id, src_id, dst_id, rel_type, evidence_type) DO UPDATE SET "
            " source_ref=EXCLUDED.source_ref, status=EXCLUDED.status, confidence=EXCLUDED.confidence, updated_at=now()",
            (self.org, src, dst, rel, evidence, status, confidence, ref, source_record_id))
        self.stats.edges += 1

    def fact(self, ftype: str, predicate: str, obj: str, summary: str, evidence: str, status: str,
             stype: str, sid: str, surl: str | None, confidence: float, subject: int | None = None,
             repo: str | None = None, scope: str = "org", valid_from: str | None = None) -> int:
        row = self.c.execute(
            "INSERT INTO facts (organization_id, repository_id, subject_id, fact_type, predicate, object_value,"
            " summary, scope, evidence_type, status, confidence, source_type, source_id, source_url, valid_from)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (organization_id, fact_type, predicate, object_value, source_type, source_id) "
            "DO UPDATE SET summary=EXCLUDED.summary, status=EXCLUDED.status, confidence=EXCLUDED.confidence,"
            " updated_at=now() RETURNING id",
            (self.org, self.repo_id.get(repo), subject, ftype, predicate, obj, summary, scope, evidence, status,
             confidence, stype, sid, surl, valid_from)).fetchone()
        self.fact_ids.add(row["id"])
        self.stats.facts += 1
        self.stats.by_fact_type[ftype] = self.stats.by_fact_type.get(ftype, 0) + 1
        return row["id"]


def _records(c, org, stype):
    return c.execute("SELECT * FROM source_records WHERE organization_id=%s AND source_type=%s ORDER BY source_id",
                     (org, stype)).fetchall()


def _meta(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z-]+):\s*(.+)$", line)
        if m:
            out[m.group(1).lower()] = m.group(2).strip()
    return out


STDLIB = set(sys.stdlib_module_names) | {"__future__"}


def _parse(body: str):
    try:
        return ast.parse(body)
    except (SyntaxError, ValueError, RecursionError):
        return None  # real-world sources: skip files that are not valid Python 3


def node_is_relative(node) -> bool:
    return isinstance(node, ast.ImportFrom) and bool(node.level)


def _layout(path: str) -> tuple[str, str] | None:
    """(top-level package, source prefix) for a file path; handles `pkg/...` and `src/pkg/...` layouts."""
    parts = path.split("/")
    if parts[0] == "src" and len(parts) > 2:
        return parts[1], "src/"
    if len(parts) > 1 and parts[0] not in ("tests", "docs", "src"):
        return parts[0], ""
    return None


def build(conn: psycopg.Connection, org_id: int, provider=None) -> BuildStats:
    b = Builder(conn, org_id)
    files = _records(conn, org_id, "file")
    repo_of = {r["source_id"]: r["source_id"].split(":", 1)[0] for r in files}

    # packages: top-level import name => (owning repo, source prefix)
    pkg_repo: dict[str, tuple[str, str]] = {}
    for sid in repo_of:
        repo, path = sid.split(":", 1)
        lay = _layout(path)
        if lay:
            pkg_repo.setdefault(lay[0], (repo, lay[1]))

    svc = {r: b.entity("service", r, r) for r in b.repo_id}
    mod: dict[str, int] = {}
    for rec in files:
        repo, path = rec["source_id"].split(":", 1)
        if path.startswith("tests/") or path.endswith("__init__.py"):
            continue
        mod[rec["source_id"]] = b.entity("module", rec["source_id"], repo, path=path)
        b.edge(mod[rec["source_id"]], svc[repo], "part_of", "structural", rec["source_url"] or path,
               source_record_id=rec["id"])

    # ---- code structure: imports, HTTP calls, endpoints
    for rec in files:
        sid = rec["source_id"]
        if sid not in mod:
            continue
        repo, path = sid.split(":", 1)
        tree = _parse(rec["body"])
        if tree is None:
            continue
        lay = _layout(path)
        prefix = lay[1] if lay else ""
        pkgparts = (path[len(prefix):] if path.startswith(prefix) else path).split("/")[:-1]
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import: resolve against this file's package
                    base = pkgparts[:max(len(pkgparts) - (node.level - 1), 0)]
                    mod_t = ".".join(base + ([node.module] if node.module else []))
                    targets = [mod_t] if node.module else []
                    targets += [f"{mod_t}.{a.name}".lstrip(".") for a in node.names]
                elif node.module:
                    targets = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            for t in targets:
                top = t.split(".")[0]
                target_repo, tprefix = pkg_repo.get(top, (None, ""))
                cand = tprefix + t.replace(".", "/") + ".py"
                if target_repo and f"{target_repo}:{cand}" in mod:
                    if f"{target_repo}:{cand}" != sid:
                        b.edge(mod[sid], mod[f"{target_repo}:{cand}"], "imports", "structural",
                               f"{sid}:{getattr(node, 'lineno', 0)}", source_record_id=rec["id"])
                    if target_repo != repo:
                        b.edge(svc[repo], svc[target_repo], "depends_on", "structural",
                               f"{sid} imports {t}", source_record_id=rec["id"])
                elif target_repo and target_repo != repo and "." not in t.lstrip("."):
                    b.edge(svc[repo], svc[target_repo], "depends_on", "structural",
                           f"{sid} imports {t}", source_record_id=rec["id"])
                elif not target_repo and top not in STDLIB and top and not node_is_relative(node):
                    pkg = b.entity("package", top)
                    b.edge(mod[sid], pkg, "imports_external", "structural", f"{sid}:{getattr(node, 'lineno', 0)}",
                           source_record_id=rec["id"])
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.args \
                            and isinstance(dec.args[0], ast.Constant) and dec.func.attr in {"get", "post", "put", "delete"}:
                        ep = b.entity("endpoint", f"{dec.func.attr.upper()} {dec.args[0].value}", repo)
                        b.edge(ep, mod[sid], "defined_in", "structural", f"{sid}:{node.lineno}",
                               source_record_id=rec["id"])
        for host in sorted({h.split(".")[0] for h in URL_HOST.findall(rec["body"])}):
            if host in svc and host != repo:
                b.edge(mod[sid], svc[host], "calls_http", "structural", sid, source_record_id=rec["id"])
                b.edge(svc[repo], svc[host], "depends_on", "structural", f"{sid} calls {host}",
                       source_record_id=rec["id"])

    # ---- people / ownership (explicit: CODEOWNERS)
    for rec in _records(conn, org_id, "doc"):
        repo, path = rec["source_id"].split(":", 1)
        if path.endswith("CODEOWNERS"):
            for owner in re.findall(r"@([\w.]+)", rec["body"]):
                b.edge(b.entity("person", owner), svc[repo], "owns", "explicit", rec["source_url"] or path,
                       source_record_id=rec["id"])
    # CODEOWNERS isn't a .py/.md; ingestion tags it as `doc` already.

    # ---- ADRs => decisions (header parsing). Repos may restate an ADR; the most complete copy is authoritative.
    by_adr: dict[str, list] = {}
    for rec in _records(conn, org_id, "adr"):
        m = re.search(r"(ADR-\d+)", rec["source_id"])
        if m:
            by_adr.setdefault(m.group(1), []).append(rec)
    decisions: dict[str, int] = {}
    adr_meta: dict[str, dict] = {}
    for adr, recs in sorted(by_adr.items()):
        rec = max(recs, key=lambda r: (len(r["body"]), r["source_id"]))
        meta = _meta(rec["body"])
        adr_meta[adr] = {**meta, "rec": rec}
        decisions[adr] = b.entity("decision", adr, rec["source_id"].split(":")[0], title=rec["title"],
                                  status=meta.get("status"), topic=meta.get("topic"))
        status = {"accepted": "active", "superseded": "superseded"}.get(meta.get("status", ""), "candidate")
        b.fact("decision", "decision_recorded", adr, rec["title"].split(":", 1)[-1].strip(), "explicit", status,
               "adr", rec["source_id"], rec["source_url"], 1.0, subject=decisions[adr],
               repo=rec["source_id"].split(":")[0], valid_from=meta.get("date"))
        for scope in re.split(r"[,\s]+", meta.get("scope", "")):
            if scope in svc:
                b.edge(decisions[adr], svc[scope], "applies_to", "explicit", rec["source_url"] or adr,
                       source_record_id=rec["id"])
    for adr, meta in adr_meta.items():
        if meta.get("supersedes") in decisions:
            b.edge(decisions[adr], decisions[meta["supersedes"]], "supersedes", "explicit",
                   meta["rec"]["source_url"] or adr, source_record_id=meta["rec"]["id"])
        if meta.get("status") == "superseded" and meta.get("superseded-by") in decisions:
            conn.execute("UPDATE facts SET superseded_by = (SELECT id FROM facts WHERE organization_id=%s AND "
                         "fact_type='decision' AND object_value=%s LIMIT 1) WHERE organization_id=%s AND "
                         "fact_type='decision' AND object_value=%s",
                         (org_id, meta["superseded-by"], org_id, adr))

    # ---- tickets: explicit link edges; an open ticket that blocks another is a structural fact
    tickets: dict[str, int] = {}
    for rec in _records(conn, org_id, "jira_issue"):
        t = rec["payload"]
        tickets[t["key"]] = b.entity("ticket", t["key"], None, summary=t["summary"], status=t["status"])
        if t.get("assignee"):
            b.edge(b.entity("person", t["assignee"]), tickets[t["key"]], "assigned_to", "explicit",
                   rec["source_url"] or t["key"], source_record_id=rec["id"])
    for rec in _records(conn, org_id, "jira_issue"):
        t = rec["payload"]
        for l in t.get("links", []):
            if l["key"] in tickets:
                rel = {"blocked-by": "blocked_by", "blocks": "blocks", "relates-to": "relates_to"}[l["type"]]
                b.edge(tickets[t["key"]], tickets[l["key"]], rel, "explicit", rec["source_url"] or t["key"],
                       source_record_id=rec["id"])
        blocked = [x["key"] for x in t.get("links", []) if x["type"] == "blocks" and x["key"] in tickets]
        if blocked and t["status"] != "Done":
            b.fact("risk", "open_blocker", t["key"],
                   f"{t['key']} ({t['summary']}) is {t['status']} and blocks {', '.join(blocked)}.",
                   "explicit", "active", "jira_issue", t["key"], rec["source_url"], 0.9, subject=tickets[t["key"]])

    # ---- PRs: structural modifies / explicit implements edges
    prs: list[dict] = []
    for rec in _records(conn, org_id, "github_pr"):
        p = rec["payload"]
        pr = b.entity("pull_request", rec["source_id"], p["repo"], title=p["title"])
        for f in p["files"]:
            mid = mod.get(f"{p['repo']}:{f}")
            if mid:
                b.edge(pr, mid, "modifies", "structural", rec["source_url"] or rec["source_id"],
                       source_record_id=rec["id"])
        for k in p["linked_tickets"]:
            if k in tickets:
                b.edge(pr, tickets[k], "implements", "explicit", rec["source_url"] or rec["source_id"],
                       source_record_id=rec["id"])
        prs.append({"id": rec["source_id"], "repo": p["repo"], "title": p["title"], "body": p["body"],
                    "files": p["files"], "_entity": pr, "_rec": rec})

    # ---- model judgments (conflicts, compliance, reuse): skipped, and reported as skipped, without an LLM
    if provider is not None:
        _judge(conn, org_id, provider, b, svc, decisions, adr_meta, prs, files, mod)

    # ---- ownership statistics from commit history (computed numbers; thresholds are settings)
    cfg = get_settings()
    ref = conn.execute("SELECT max(payload->>'date') AS d FROM source_records WHERE organization_id=%s "
                       "AND source_type='github_commit'", (org_id,)).fetchone()["d"]
    per_file: dict[tuple[str, str], Counter] = {}
    last_by_person: dict[tuple[str, str], str] = {}
    for rec in _records(conn, org_id, "github_commit"):
        cm = rec["payload"]
        for f in cm["files"]:
            per_file.setdefault((cm["repo"], f), Counter())[cm["author"]] += 1
        k = (cm["repo"], cm["author"])
        last_by_person[k] = max(last_by_person.get(k, ""), cm["date"])
    for (repo, f), cnt in sorted(per_file.items()):
        tot = sum(cnt.values())
        author, n = cnt.most_common(1)[0]
        if tot >= cfg.ownership_min_commits and n / tot >= cfg.ownership_min_share and f"{repo}:{f}" in mod:
            b.fact("ownership", "single_dominant_contributor", f"{repo}:{f}",
                   f"{author} authored {n}/{tot} commits ({n / tot:.0%}) to {repo}/{f}; bus-factor risk.",
                   "structural", "active", "github_commit", f"{repo}:{f}", None, 0.95,
                   subject=mod[f"{repo}:{f}"], repo=repo, scope="repo")
    pr_last = defaultdict(str)
    for p_ in prs:
        a = p_["_rec"]["payload"].get("author")
        pr_last[a] = max(pr_last[a], p_["_rec"]["payload"].get("merged_at", ""))
    for rec in _records(conn, org_id, "doc"):
        repo, path = rec["source_id"].split(":", 1)
        if path.endswith("CODEOWNERS"):
            for owner in re.findall(r"@([\w.]+)", rec["body"]):
                last = max([v for (r, a), v in last_by_person.items() if a == owner] + [pr_last.get(owner, "")])
                if ref and last:
                    idle = (date.fromisoformat(ref) - date.fromisoformat(last)).days
                    if idle > cfg.dormant_days:
                        b.fact("ownership", "dormant_owner", f"{owner}@{repo}",
                               f"{owner} owns {repo} (CODEOWNERS) but has no activity since {last} ({idle} days).",
                               "structural", "active", "doc", rec["source_id"], rec["source_url"], 0.9,
                               subject=b.entity("person", owner), repo=repo, scope="repo")
    # ---- retire derived facts that are no longer supported by current evidence (stale-fact control).
    # User-authored facts (/remember, /override => author set) are never auto-retired.
    ids = sorted(b.fact_ids)
    b.stats.retired = conn.execute(
        "UPDATE facts SET status='rejected', updated_at=now() WHERE organization_id=%s AND author IS NULL "
        "AND status IN ('active','candidate') AND NOT (id = ANY(%s))", (org_id, ids)).rowcount
    return b.stats


def _judge(conn, org, provider, b: "Builder", svc, decisions, adr_meta, prs, files, mod) -> None:
    cfg = get_settings()
    st = b.stats.judgments

    def guarded(name, fn):
        try:
            fn()
        except LLMUnavailable as exc:
            st[name] = f"skipped: {exc}"

    def conflicts():
        adrs = {a: {"status": m.get("status"), "title": m["rec"]["title"], "body": m["rec"]["body"],
                    "scope": m.get("scope", "")} for a, m in adr_meta.items()}
        n = 0
        for f in judgments.decision_conflicts(conn, org, provider, adrs, cfg.judge_batch_size):
            a, c = f["pair"]
            url = adr_meta[a]["rec"]["source_url"]
            if f["relation"] == "conflict":
                b.fact("conflict", "conflicting_decisions", f"{a}+{c}", f"{a} and {c} conflict: {f['reason']}",
                       "inferred", "candidate", "adr", f"{a},{c}", url, 0.8, subject=decisions[a])
            else:
                b.fact("decision_relation", "suggested_supersession", f"{f['a']}>{f['b']}",
                       f"{f['a']} appears to supersede {f['b']}: {f['reason']}", "inferred", "candidate", "adr",
                       f"{f['a']},{f['b']}", url, 0.7, subject=decisions.get(f["a"]))
            n += 1
        st["decision_findings"] = n

    def compliance():
        active = {a: {"title": m["rec"]["title"], "body": m["rec"]["body"], "scope": m.get("scope", "")}
                  for a, m in adr_meta.items() if m.get("status") == "accepted"}
        if not active or not prs:
            return
        by_id = {p["id"]: p for p in prs}
        plain = [{k: v for k, v in p.items() if not k.startswith("_")} for p in prs]
        n = 0
        for f in judgments.pr_compliance(conn, org, provider, plain, active, cfg.judge_batch_size):
            p = by_id[f["pr"]]
            payload = p["_rec"]["payload"]
            if f["override"]:
                b.fact("override", "overrides_decision", f"{f['adr']}@{f['pr']}",
                       f"{f['pr']} overrides {f['adr']}: {f['quote']}", "explicit", "active", "github_pr", f["pr"],
                       p["_rec"]["source_url"], 1.0, subject=p["_entity"], repo=p["repo"], scope="repo",
                       valid_from=payload.get("merged_at"))
            else:
                b.fact("risk", "unrecorded_standard_bypass", f"{f['adr']}@{f['pr']}",
                       f"{f['pr']} appears to violate {f['adr']} with no recorded override: {f['reason']}",
                       "inferred", "candidate", "github_pr", f["pr"], p["_rec"]["source_url"], 0.7,
                       subject=p["_entity"], repo=p["repo"], scope="repo")
            n += 1
        st["pr_findings"] = n

    def reuse():
        n = 0
        for p in judgments.reuse_pairs(conn, org, provider, files, max_chars=150_000):
            fa = p["existing"].split("::")[0]
            b.fact("reuse", "duplicate_implementation", f"{p['existing']} ~ {p['duplicate']}",
                   f"{p['duplicate']} appears to re-implement {p['existing']}: {p['reason']}", "inferred",
                   "candidate", "file", fa, None, 0.7, subject=mod.get(fa),
                   repo=p["duplicate"].split(":", 1)[0])
            n += 1
        st["reuse_findings"] = n

    guarded("decision_conflicts", conflicts)
    guarded("pr_compliance", compliance)
    guarded("reuse", reuse)
