"""Embed admitted content once per (owner, model); unchanged content is never re-embedded.

Admission: commits are NOT embedded (low durable value, high volume). Rejected/superseded facts are skipped.
"""
from __future__ import annotations

import hashlib

import psycopg

from ..models.provider import Provider

EMBED_SOURCE_TYPES = ("adr", "doc", "github_pr", "jira_issue", "file")


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def embed_org(conn: psycopg.Connection, org_id: int, provider: Provider) -> dict:
    items: list[tuple[str, int, str]] = []
    for r in conn.execute("SELECT id, source_type, title, body FROM source_records WHERE organization_id=%s "
                          "AND source_type = ANY(%s)", (org_id, list(EMBED_SOURCE_TYPES))):
        items.append(("source_records", r["id"], f"{r['title'] or ''}\n{(r['body'] or '')[:2000]}"))
    for r in conn.execute("SELECT id, predicate, summary FROM facts WHERE organization_id=%s "
                          "AND status IN ('active','candidate')", (org_id,)):
        items.append(("facts", r["id"], f"{r['predicate']}: {r['summary']}"))
    have = {(r["owner_table"], r["owner_id"]): r["content_hash"] for r in conn.execute(
        "SELECT owner_table, owner_id, content_hash FROM embeddings WHERE organization_id=%s AND model=%s",
        (org_id, provider.embed_model))}
    todo = [(t, i, x, hashlib.sha256(x.encode()).hexdigest()) for t, i, x in items]
    todo = [it for it in todo if have.get((it[0], it[1])) != it[3]]
    stats = {"candidates": len(items), "embedded": len(todo), "cached": len(items) - len(todo)}
    if todo:
        vecs = provider.embed([x for _, _, x, _ in todo])
        for (t, i, _x, h), v in zip(todo, vecs):
            conn.execute(
                "INSERT INTO embeddings (organization_id, owner_table, owner_id, content_hash, model, embedding) "
                "VALUES (%s,%s,%s,%s,%s,%s::vector) ON CONFLICT (owner_table, owner_id, model) "
                "DO UPDATE SET content_hash=EXCLUDED.content_hash, embedding=EXCLUDED.embedding",
                (org_id, t, i, h, provider.embed_model, _vec(v)))
    return stats
