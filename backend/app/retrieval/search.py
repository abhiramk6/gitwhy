"""Hybrid retrieval: keyword (FTS + exact identifiers) + vector + graph expansion, fused with RRF.

Relevance is decided by rank fusion over independent signals, never by a single embedding score.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import psycopg

from ..models.provider import Provider
from .embed import _vec

RRF_K = 60
ID_PATTERN = re.compile(r"\b([A-Z]{2,5}-\d+)\b")
_SOURCE_TYPES = ("adr", "doc", "github_pr", "jira_issue", "file")


@dataclass
class Hit:
    kind: str            # "record" | "fact"
    id: int
    title: str
    snippet: str
    source_type: str
    source_id: str
    source_url: str | None
    evidence_type: str | None = None
    status: str | None = None
    repo: str | None = None
    score: float = 0.0
    signals: dict[str, int] = field(default_factory=dict)  # signal -> rank (1-based)

    @property
    def key(self) -> tuple[str, int]:
        return (self.kind, self.id)


def _identifiers(conn, org, original: str) -> list[tuple[str, int]]:
    """Records whose id exactly equals an identifier named in the raw query (ticket keys, ADR ids)."""
    out: list[tuple[str, int]] = []
    for ident in ID_PATTERN.findall(original):
        for r in conn.execute("SELECT id FROM source_records WHERE organization_id=%s AND source_id=%s "
                              "AND source_type = ANY(%s)", (org, ident, list(_SOURCE_TYPES))):
            out.append(("record", r["id"]))
    return list(dict.fromkeys(out))


def _keyword(conn, org, q: str, limit: int) -> list[tuple[str, int]]:
    ranked: list[tuple[str, int]] = []
    rows = conn.execute(
        "SELECT 'record' AS k, id, ts_rank_cd(search_tsv, query, 1) AS r FROM source_records, "
        "websearch_to_tsquery('english', %(q)s) query WHERE organization_id=%(o)s AND source_type = ANY(%(t)s) "
        "AND search_tsv @@ query UNION ALL "
        "SELECT 'fact', id, ts_rank_cd(search_tsv, query, 1) FROM facts, websearch_to_tsquery('english', %(q)s) query "
        "WHERE organization_id=%(o)s AND status IN ('active','candidate') AND search_tsv @@ query "
        "ORDER BY r DESC LIMIT %(n)s", {"q": q, "o": org, "t": list(_SOURCE_TYPES), "n": limit}).fetchall()
    ranked += [(r["k"], r["id"]) for r in rows]
    return list(dict.fromkeys(ranked))


def _or_query(q: str) -> str:
    """Natural-language questions rarely match every term; OR the content words for recall."""
    words = [w for w in re.findall(r"[A-Za-z0-9_+\-]{3,}", q.lower())]
    return " or ".join(dict.fromkeys(words))


def _vector(conn, org, provider: Provider, q: str, limit: int) -> list[tuple[tuple[str, int], float]]:
    v = _vec(provider.embed([q])[0])
    rows = conn.execute(
        "SELECT owner_table, owner_id, 1 - (embedding <=> %s::vector) AS sim FROM embeddings "
        "WHERE organization_id=%s AND model=%s ORDER BY embedding <=> %s::vector LIMIT %s",
        (v, org, provider.embed_model, v, limit)).fetchall()
    return [(("record" if r["owner_table"] == "source_records" else "fact", r["owner_id"]), float(r["sim"]))
            for r in rows]


def _graph(conn, org, seeds: list[tuple[str, int]], limit: int) -> list[tuple[str, int]]:
    """Facts/decisions attached to the services touched by the top seed hits."""
    if not seeds:
        return []
    rec_ids = [i for k, i in seeds if k == "record"][:5]
    fact_ids = [i for k, i in seeds if k == "fact"][:5]
    repos = {r["repository_id"] for r in conn.execute(
        "SELECT repository_id FROM source_records WHERE id = ANY(%s) AND repository_id IS NOT NULL", (rec_ids,))}
    repos |= {r["repository_id"] for r in conn.execute(
        "SELECT repository_id FROM facts WHERE id = ANY(%s) AND repository_id IS NOT NULL", (fact_ids,))}
    if not repos:
        return []
    rows = conn.execute(
        "SELECT f.id FROM facts f WHERE f.organization_id=%s AND f.status='active' AND "
        "(f.repository_id = ANY(%s) OR f.subject_id IN (SELECT ed.src_id FROM edges ed JOIN entities s "
        "ON s.id=ed.dst_id WHERE s.repository_id = ANY(%s) AND ed.rel_type='applies_to')) "
        "ORDER BY f.confidence DESC, f.id LIMIT %s", (org, list(repos), list(repos), limit)).fetchall()
    return [("fact", r["id"]) for r in rows]


def _hydrate(conn, keys: list[tuple[str, int]]) -> dict[tuple[str, int], Hit]:
    out: dict[tuple[str, int], Hit] = {}
    rec_ids = [i for k, i in keys if k == "record"]
    fact_ids = [i for k, i in keys if k == "fact"]
    for r in conn.execute("SELECT s.id, s.source_type, s.source_id, s.source_url, s.title, s.body, r.name AS repo "
                          "FROM source_records s LEFT JOIN repositories r ON r.id=s.repository_id "
                          "WHERE s.id = ANY(%s)", (rec_ids,)):
        out[("record", r["id"])] = Hit("record", r["id"], r["title"] or r["source_id"], (r["body"] or "")[:240],
                                       r["source_type"], r["source_id"], r["source_url"], repo=r["repo"])
    for r in conn.execute("SELECT f.id, f.fact_type, f.summary, f.source_type, f.source_id, f.source_url, "
                          "f.evidence_type, f.status, r.name AS repo FROM facts f "
                          "LEFT JOIN repositories r ON r.id=f.repository_id WHERE f.id = ANY(%s)", (fact_ids,)):
        out[("fact", r["id"])] = Hit("fact", r["id"], f"[{r['fact_type']}] {r['summary'][:80]}", r["summary"],
                                     r["source_type"], r["source_id"], r["source_url"], r["evidence_type"],
                                     r["status"], r["repo"])
    return out


def search(conn: psycopg.Connection, org_id: int, provider: Provider, query: str, k: int = 10,
           per_signal: int = 25) -> list[Hit]:
    ident = _identifiers(conn, org_id, query)
    kw = _keyword(conn, org_id, _or_query(query) or query, per_signal)
    vec_scored = _vector(conn, org_id, provider, query, per_signal)
    # Nearest-neighbour search always returns *something*. Without lexical evidence, only accept
    # vector matches that clear the provider's calibrated similarity floor.
    vec = [k for k, sim in vec_scored if (ident or kw) or sim >= provider.min_similarity]
    seeds = list(dict.fromkeys(ident + [x for pair in zip(kw, vec) for x in pair]))[:10]
    gr = _graph(conn, org_id, seeds, per_signal)
    scores: dict[tuple[str, int], float] = {}
    signals: dict[tuple[str, int], dict[str, int]] = {}
    for name, lst, weight in (("identifier", ident, 5.0), ("keyword", kw, 1.0), ("vector", vec, 1.0),
                              ("graph", gr, 0.5)):
        for rank, key in enumerate(lst, 1):
            scores[key] = scores.get(key, 0.0) + weight / (RRF_K + rank)
            signals.setdefault(key, {})[name] = rank
    top = sorted(scores, key=lambda x: (-scores[x], x))[:k]
    hyd = _hydrate(conn, top)
    hits = []
    for key in top:
        if key in hyd:
            h = hyd[key]
            h.score, h.signals = round(scores[key], 5), signals[key]
            hits.append(h)
    return hits
