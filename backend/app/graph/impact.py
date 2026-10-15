"""Bounded impact traversal over `depends_on` edges using a recursive CTE.

Returns, for every reachable service, the shortest path and the evidence (type + source) of each edge on it.
Traversal is deterministic; no model call is involved.
"""
from __future__ import annotations

import psycopg

_WALK = """
WITH RECURSIVE walk AS (
  SELECT e.id AS node, 0 AS depth, ARRAY[e.id] AS path, ARRAY[]::bigint[] AS edge_ids
  FROM entities e
  WHERE e.organization_id = %(org)s AND e.entity_type = 'service' AND e.canonical_name = ANY(%(seeds)s)
  UNION ALL
  SELECT ed.{nxt}, w.depth + 1, w.path || ed.{nxt}, w.edge_ids || ed.id
  FROM walk w
  JOIN edges ed ON ed.{cur} = w.node
   AND ed.organization_id = %(org)s AND ed.rel_type = 'depends_on' AND ed.status = 'active'
  WHERE w.depth < %(depth)s AND NOT (ed.{nxt} = ANY(w.path))
)
SELECT DISTINCT ON (node) node, depth, path, edge_ids FROM walk WHERE depth > 0 ORDER BY node, depth, path
"""


def _walk(conn: psycopg.Connection, org_id: int, seeds: list[str], depth: int, direction: str) -> list[dict]:
    cur, nxt = ("src_id", "dst_id") if direction == "dependencies" else ("dst_id", "src_id")
    rows = conn.execute(_WALK.format(cur=cur, nxt=nxt), {"org": org_id, "seeds": seeds, "depth": depth}).fetchall()
    ids = {i for r in rows for i in r["path"]}
    names = {r["id"]: r["canonical_name"] for r in conn.execute(
        "SELECT id, canonical_name FROM entities WHERE id = ANY(%s)", (list(ids),))} if ids else {}
    edge_ids = {i for r in rows for i in r["edge_ids"]}
    edges = {r["id"]: r for r in conn.execute(
        "SELECT ed.id, s.canonical_name AS src, d.canonical_name AS dst, ed.evidence_type, ed.confidence, "
        "ed.source_ref FROM edges ed JOIN entities s ON s.id=ed.src_id JOIN entities d ON d.id=ed.dst_id "
        "WHERE ed.id = ANY(%s)", (list(edge_ids),))} if edge_ids else {}
    out = []
    for r in sorted(rows, key=lambda x: (x["depth"], names[x["node"]])):
        out.append({
            "service": names[r["node"]], "depth": r["depth"],
            "path": [names[i] for i in r["path"]],
            "evidence": [{"from": edges[e]["src"], "to": edges[e]["dst"], "evidence_type": edges[e]["evidence_type"],
                          "confidence": edges[e]["confidence"], "source": edges[e]["source_ref"]} for e in r["edge_ids"]],
        })
    return out


def impact(conn: psycopg.Connection, org_id: int, seeds: list[str], depth: int = 3) -> dict:
    """`dependencies`: services the seeds call (changes may be required). `dependents`: services that call
    the seeds (may break). Both are bounded by `depth` (max 5)."""
    depth = max(1, min(depth, 5))
    return {"seeds": seeds,
            "dependencies": _walk(conn, org_id, seeds, depth, "dependencies"),
            "dependents": _walk(conn, org_id, seeds, depth, "dependents")}
