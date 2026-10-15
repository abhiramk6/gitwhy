"""Embed admitted content by chunk, once per (owner, chunk, model); unchanged chunks are never re-embedded.

Every chunk of every admitted record is embedded (no prefix truncation). Commits are not admitted: their value is
in the PR/issue that explains them. With a provider that has no semantic embeddings nothing is embedded at all.
"""
from __future__ import annotations

import hashlib

import psycopg

from ..models.provider import Provider
from .chunk import chunk_spans

EMBED_SOURCE_TYPES = ("adr", "doc", "github_pr", "jira_issue", "file")
BATCH = 64


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def embed_org(conn: psycopg.Connection, org_id: int, provider: Provider) -> dict:
    if not provider.semantic_embeddings:
        return {"candidates": 0, "embedded": 0, "cached": 0, "skipped": "provider has no semantic embeddings"}
    want: dict[tuple[str, int, int], tuple[str, int, int, str]] = {}  # (table,id,chunk) -> (hash,start,end,text)
    for r in conn.execute("SELECT id, title, body FROM source_records WHERE organization_id=%s AND source_type = ANY(%s)",
                          (org_id, list(EMBED_SOURCE_TYPES))):
        body = r["body"] or ""
        for ci, (s, e) in enumerate(chunk_spans(body)):
            text = f"{r['title'] or ''}\n{body[s:e]}"
            want[("source_records", r["id"], ci)] = (hashlib.sha256(text.encode()).hexdigest(), s, e, text)
    for r in conn.execute("SELECT id, predicate, summary FROM facts WHERE organization_id=%s "
                          "AND status IN ('active','candidate')", (org_id,)):
        text = f"{r['predicate']}: {r['summary']}"
        want[("facts", r["id"], 0)] = (hashlib.sha256(text.encode()).hexdigest(), 0, len(text), text)
    have = {(r["owner_table"], r["owner_id"], r["chunk_index"]): r["content_hash"] for r in conn.execute(
        "SELECT owner_table, owner_id, chunk_index, content_hash FROM embeddings WHERE organization_id=%s AND model=%s",
        (org_id, provider.embed_model))}
    stale = [k for k in have if k not in want]
    for t, i, c in stale:
        conn.execute("DELETE FROM embeddings WHERE organization_id=%s AND model=%s AND owner_table=%s AND owner_id=%s "
                     "AND chunk_index=%s", (org_id, provider.embed_model, t, i, c))
    todo = [(k, v) for k, v in want.items() if have.get(k) != v[0]]
    for b in range(0, len(todo), BATCH):
        part = todo[b:b + BATCH]
        vecs = provider.embed([v[3] for _, v in part])
        for ((t, i, c), (h, s, e, _x)), vec in zip(part, vecs):
            conn.execute(
                "INSERT INTO embeddings (organization_id, owner_table, owner_id, chunk_index, chunk_start, chunk_end,"
                " content_hash, model, embedding) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::vector) "
                "ON CONFLICT (owner_table, owner_id, model, chunk_index) DO UPDATE SET content_hash=EXCLUDED.content_hash,"
                " chunk_start=EXCLUDED.chunk_start, chunk_end=EXCLUDED.chunk_end, embedding=EXCLUDED.embedding",
                (org_id, t, i, c, s, e, h, provider.embed_model, _vec(vec)))
        conn.commit()  # progress survives an interrupted run; unchanged chunks are skipped on the next one
    return {"candidates": len(want), "embedded": len(todo), "cached": len(want) - len(todo), "removed": len(stale)}
