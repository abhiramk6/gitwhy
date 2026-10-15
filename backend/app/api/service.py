"""Query/command functions shared by the REST routes and the MCP tools (single implementation each)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

import psycopg

from ..graph.impact import impact
from ..models.provider import Provider
from ..planning.planner import create_plan, unsupported_claims
from ..config import get_settings
from ..retrieval.search import search_with_meta

ALERT_TYPES = ("ownership", "risk", "override", "conflict", "reuse")


def overview(conn: psycopg.Connection, org: int) -> dict:
    q = lambda sql, *a: conn.execute(sql, a).fetchall()  # noqa: E731
    repos = q("SELECT r.name, r.language, (SELECT count(*) FROM source_records s WHERE s.repository_id=r.id "
              "AND s.source_type='github_commit') AS commits, (SELECT count(*) FROM source_records s WHERE "
              "s.repository_id=r.id AND s.source_type='github_pr') AS prs FROM repositories r "
              "WHERE r.organization_id=%s ORDER BY r.name", org)
    alerts = q("SELECT f.id, f.fact_type, f.status, f.evidence_type, f.confidence, f.summary, f.source_url, "
               "f.source_type, f.source_id, r.name AS repo FROM facts f LEFT JOIN repositories r ON r.id=f.repository_id "
               "WHERE f.organization_id=%s AND f.fact_type = ANY(%s) AND f.status IN ('active','candidate') "
               "ORDER BY f.fact_type, f.id", org, list(ALERT_TYPES))
    for a in alerts:
        a["label"] = "verified" if a["evidence_type"] in ("structural", "explicit") and a["status"] == "active" else "inferred"
    return {
        "organization": conn.execute("SELECT slug, name, is_synthetic FROM organizations WHERE id=%s", (org,)).fetchone(),
        "repositories": repos,
        "counts": {
            "source_records": {r["source_type"]: r["n"] for r in q(
                "SELECT source_type, count(*) n FROM source_records WHERE organization_id=%s GROUP BY 1", org)},
            "entities": {r["entity_type"]: r["n"] for r in q(
                "SELECT entity_type, count(*) n FROM entities WHERE organization_id=%s GROUP BY 1", org)},
            "facts": {f"{r['fact_type']}:{r['status']}": r["n"] for r in q(
                "SELECT fact_type, status, count(*) n FROM facts WHERE organization_id=%s GROUP BY 1,2", org)},
        },
        "alerts": alerts,
        "intelligence": {
            "provider": get_settings().provider,
            "llm_configured": get_settings().provider != "offline",
            "cached_judgments": q("SELECT count(*) n FROM llm_judgments WHERE organization_id=%s", org)[0]["n"],
            "embedded_chunks": q("SELECT count(*) n FROM embeddings WHERE organization_id=%s", org)[0]["n"],
        },
        "ingestion": ingestion_runs(conn, org, 5),
    }


def ingestion_runs(conn, org: int, limit: int = 20) -> list[dict]:
    return conn.execute("SELECT id, source, mode, status, started_at, finished_at, records_seen, records_new, "
                        "records_changed, error FROM ingestion_runs WHERE organization_id=%s ORDER BY id DESC LIMIT %s",
                        (org, limit)).fetchall()


GRAPH_NODE_TYPES = ("service", "decision", "person", "package", "endpoint")
GRAPH_REL_TYPES = ("depends_on", "applies_to", "owns", "supersedes", "calls_http", "defined_in")


def graph(conn, org: int, types: list[str] | None = None, rels: list[str] | None = None) -> dict:
    types = [t for t in (types or GRAPH_NODE_TYPES) if t in GRAPH_NODE_TYPES] or list(GRAPH_NODE_TYPES)
    rels = [r for r in (rels or GRAPH_REL_TYPES) if r in GRAPH_REL_TYPES] or list(GRAPH_REL_TYPES)
    nodes = conn.execute("SELECT e.id, e.entity_type AS type, e.canonical_name AS name, r.name AS repo, e.attributes "
                         "FROM entities e LEFT JOIN repositories r ON r.id=e.repository_id "
                         "WHERE e.organization_id=%s AND e.entity_type = ANY(%s) ORDER BY e.entity_type, e.canonical_name",
                         (org, types)).fetchall()
    ids = [n["id"] for n in nodes]
    edges = conn.execute("SELECT id, src_id AS src, dst_id AS dst, rel_type AS rel, evidence_type, status, confidence, "
                         "source_ref AS source FROM edges WHERE organization_id=%s AND rel_type = ANY(%s) "
                         "AND src_id = ANY(%s) AND dst_id = ANY(%s) ORDER BY id", (org, rels, ids, ids)).fetchall()
    for e in edges:
        e["label"] = "verified" if e["evidence_type"] in ("structural", "explicit") and e["status"] == "active" else "inferred"
    return {"nodes": nodes, "edges": edges}


def entity_detail(conn, org: int, entity_id: int) -> dict | None:
    e = conn.execute("SELECT e.id, e.entity_type AS type, e.canonical_name AS name, e.aliases, e.attributes, "
                     "r.name AS repo FROM entities e LEFT JOIN repositories r ON r.id=e.repository_id "
                     "WHERE e.id=%s AND e.organization_id=%s", (entity_id, org)).fetchone()
    if not e:
        return None
    edge_sql = ("SELECT ed.id, ed.rel_type AS rel, ed.evidence_type, ed.status, ed.confidence, ed.source_ref AS source, "
                "o.id AS other_id, o.canonical_name AS other, o.entity_type AS other_type FROM edges ed "
                "JOIN entities o ON o.id = ed.{other} WHERE ed.{me} = %s AND ed.organization_id=%s ORDER BY ed.rel_type, o.canonical_name")
    e["outbound"] = conn.execute(edge_sql.format(other="dst_id", me="src_id"), (entity_id, org)).fetchall()
    e["inbound"] = conn.execute(edge_sql.format(other="src_id", me="dst_id"), (entity_id, org)).fetchall()
    e["facts"] = conn.execute("SELECT id, fact_type, status, evidence_type, confidence, summary, source_url, source_type, "
                              "source_id FROM facts WHERE organization_id=%s AND subject_id=%s ORDER BY id",
                              (org, entity_id)).fetchall()
    return e


def knowledge(conn, org: int, status: str | None = None, fact_type: str | None = None) -> list[dict]:
    rows = conn.execute(
        "SELECT f.id, f.fact_type, f.predicate, f.object_value, f.summary, f.scope, f.evidence_type, f.status, f.confidence, "
        "f.source_type, f.source_id, f.source_url, f.superseded_by, f.valid_from, f.valid_until, f.observed_at, f.author, "
        "r.name AS repo FROM facts f LEFT JOIN repositories r ON r.id=f.repository_id WHERE f.organization_id=%s "
        "AND (%s::text IS NULL OR f.status=%s) AND (%s::text IS NULL OR f.fact_type=%s) ORDER BY f.fact_type, f.id",
        (org, status, status, fact_type, fact_type)).fetchall()
    for r in rows:
        r["label"] = "verified" if r["evidence_type"] in ("structural", "explicit") and r["status"] == "active" else "inferred"
    return rows


def set_fact_status(conn, org: int, fact_id: int, status: str) -> dict | None:
    return conn.execute("UPDATE facts SET status=%s, updated_at=now() WHERE id=%s AND organization_id=%s "
                        "RETURNING id, status", (status, fact_id, org)).fetchone()


def remember(conn, org: int, text: str, author: str, scope: str = "org", repo: str | None = None) -> dict:
    sid = hashlib.sha1(f"{author}|{scope}|{repo}|{text}".encode()).hexdigest()
    repo_id = None
    if repo:
        r = conn.execute("SELECT id FROM repositories WHERE organization_id=%s AND name=%s", (org, repo)).fetchone()
        repo_id = r["id"] if r else None
    row = conn.execute(
        "INSERT INTO facts (organization_id, repository_id, fact_type, predicate, object_value, summary, scope, "
        "evidence_type, status, confidence, source_type, source_id, author) VALUES (%s,%s,'memory','remembered',%s,%s,%s,"
        "'explicit','candidate',0.5,'remember',%s,%s) ON CONFLICT (organization_id, fact_type, predicate, object_value, "
        "source_type, source_id) DO NOTHING RETURNING id", (org, repo_id, sid, text, scope, sid, author)).fetchone()
    return {"id": row["id"] if row else None, "created": bool(row), "status": "candidate"}


def override(conn, org: int, rule: str, reason: str, author: str, temporary: bool = True,
             approver: str | None = None, repo: str | None = None, valid_until: str | None = None) -> dict:
    sid = hashlib.sha1(f"{author}|{rule}|{repo}|{reason}".encode()).hexdigest()[:12]
    repo_id = None
    if repo:
        r = conn.execute("SELECT id FROM repositories WHERE organization_id=%s AND name=%s", (org, repo)).fetchone()
        repo_id = r["id"] if r else None
    kind = "temporary" if temporary else "permanent"
    summary = f"{author} overrides {rule} ({kind}): {reason}" + (f" [approved by {approver}]" if approver else " [no approver recorded]")
    row = conn.execute(
        "INSERT INTO facts (organization_id, repository_id, fact_type, predicate, object_value, summary, scope, "
        "evidence_type, status, confidence, source_type, source_id, author, valid_until) VALUES (%s,%s,'override',"
        "'overrides',%s,%s,%s,'explicit',%s,%s,'override_command',%s,%s,%s) ON CONFLICT (organization_id, fact_type, "
        "predicate, object_value, source_type, source_id) DO NOTHING RETURNING id",
        (org, repo_id, rule, summary, "repo" if repo else "org", "active" if approver else "candidate",
         0.9 if approver else 0.5, sid, author, valid_until)).fetchone()
    return {"id": row["id"] if row else None, "created": bool(row), "status": "active" if approver else "candidate"}


def do_search(conn, org: int, provider: Provider, q: str, k: int = 10) -> dict:
    hits, meta = search_with_meta(conn, org, provider, q, k=k)
    return {"mode": meta["mode"], "semantic": meta["semantic"], "analysis": meta["analysis"],
            "hits": [asdict(h) | {"key": list(h.key)} for h in hits]}


def make_plan(conn, org: int, provider: Provider, request: str, depth: int = 3) -> dict:
    plan = create_plan(conn, org, provider, request, depth=depth, persist=False)
    plan["unsupported_claims"] = unsupported_claims(plan) if plan.get("status") == "draft" else []
    if plan.get("status") == "llm_required":  # nothing to persist: no plan was produced
        return {"id": None, "plan_status": "unavailable", "created_at": None, **plan}
    row = conn.execute("INSERT INTO feature_plans (organization_id, request_text, plan, model) VALUES (%s,%s,%s::jsonb,%s) "
                       "RETURNING id, status, created_at", (org, request, json.dumps(plan), provider.name)).fetchone()
    return {"id": row["id"], "plan_status": row["status"], "created_at": row["created_at"], **plan}


def get_plan(conn, org: int, plan_id: int) -> dict | None:
    r = conn.execute("SELECT id, status AS plan_status, created_at, plan FROM feature_plans WHERE id=%s AND organization_id=%s",
                     (plan_id, org)).fetchone()
    return None if not r else {"id": r["id"], "plan_status": r["plan_status"], "created_at": r["created_at"], **r["plan"]}


def list_plans(conn, org: int) -> list[dict]:
    return conn.execute("SELECT id, request_text, status, model, created_at FROM feature_plans WHERE organization_id=%s "
                        "ORDER BY id DESC LIMIT 50", (org,)).fetchall()


def approve_plan(conn, org: int, plan_id: int, status: str) -> dict | None:
    return conn.execute("UPDATE feature_plans SET status=%s, updated_at=now() WHERE id=%s AND organization_id=%s "
                        "RETURNING id, status", (status, plan_id, org)).fetchone()


def dependencies(conn, org: int, services: list[str], depth: int = 3) -> dict:
    return impact(conn, org, services, depth)
