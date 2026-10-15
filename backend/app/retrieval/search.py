"""Hybrid retrieval with a model in the judgment seat.

Candidate generation (all deterministic database operations):
  exact lookup of tokens that are ticket keys / decision ids, full-text queries, and chunk-level vector search.
Fusion: reciprocal-rank fusion (a standard algorithm) with equal weights; no hand-tuned boosts or similarity floors.
Judgment (needs an LLM): the query is analysed into search queries/identifiers/an answer sketch, and the fused pool
is reranked by relevance. Without an LLM the system is honest about it: lexical search over the raw query only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import psycopg

from ..config import get_settings
from ..intelligence import tasks
from ..intelligence.judge import run_task
from ..models.provider import LLMUnavailable, Provider
from .embed import _vec

RRF_K = 60
_SOURCE_TYPES = ("adr", "doc", "github_pr", "jira_issue", "file")
_SPLIT = re.compile(r"[\s,;:()\[\]{}\"'<>?!]+")


@dataclass
class Hit:
    kind: str            # "record" | "fact"
    id: int
    title: str
    snippet: str         # the passage that matched (best chunk / highlighted fragment), not the document's prefix
    source_type: str
    source_id: str
    source_url: str | None
    evidence_type: str | None = None
    status: str | None = None
    repo: str | None = None
    score: float = 0.0
    signals: dict[str, int] = field(default_factory=dict)  # signal -> rank (1-based)
    relevance: int | None = None   # model grade 0-3 when a reranker ran
    reason: str | None = None

    @property
    def key(self) -> tuple[str, int]:
        return (self.kind, self.id)

    @property
    def ref(self) -> str:
        return f"{self.kind}:{self.id}"


def _exact(conn, org, query: str) -> list[tuple[str, int]]:
    """Tokens of the query that are, verbatim, a record id (ticket key, PR id) or a decision id."""
    toks = list(dict.fromkeys(t.strip(".") for t in _SPLIT.split(query) if t.strip(".")))
    if not toks:
        return []
    up = [t.upper() for t in toks]
    out = [("record", r["id"]) for r in conn.execute(
        "SELECT id FROM source_records WHERE organization_id=%s AND source_type = ANY(%s) AND "
        "(source_id = ANY(%s) OR upper(source_id) = ANY(%s)) ORDER BY id", (org, list(_SOURCE_TYPES), toks, up))]
    out += [("fact", r["id"]) for r in conn.execute(
        "SELECT id FROM facts WHERE organization_id=%s AND fact_type='decision' AND status <> 'rejected' AND "
        "upper(object_value) = ANY(%s) ORDER BY id", (org, up))]
    return out


def _keyword(conn, org, q: str, limit: int) -> list[tuple[str, int]]:
    rows = conn.execute(
        "SELECT 'record' AS k, id, ts_rank_cd(search_tsv, query, 1) AS r FROM source_records, "
        "websearch_to_tsquery('english', %(q)s) query WHERE organization_id=%(o)s AND source_type = ANY(%(t)s) "
        "AND search_tsv @@ query UNION ALL "
        "SELECT 'fact', id, ts_rank_cd(search_tsv, query, 1) FROM facts, websearch_to_tsquery('english', %(q)s) query "
        "WHERE organization_id=%(o)s AND status IN ('active','candidate') AND search_tsv @@ query "
        "ORDER BY r DESC LIMIT %(n)s", {"q": q, "o": org, "t": list(_SOURCE_TYPES), "n": limit}).fetchall()
    return list(dict.fromkeys((r["k"], r["id"]) for r in rows))


def _keyword_ranked(conn, org, q: str, limit: int) -> list[tuple[str, int]]:
    """Records matching every query word first, then records matching any (query relaxation). Stop words are the
    database text-search configuration's job, not ours."""
    words = list(dict.fromkeys(re.findall(r"[A-Za-z0-9_+\-]{2,}", q)))
    both = _keyword(conn, org, q, limit)
    anyx = _keyword(conn, org, " or ".join(words), limit) if len(words) > 1 else []
    return list(dict.fromkeys(both + anyx))[:limit]


def _vector(conn, org, provider: Provider, text: str, limit: int) -> tuple[list[tuple[str, int]], dict]:
    """Best chunk per owner, nearest first. Returns ranked keys and {key: (chunk_start, chunk_end)}."""
    v = _vec(provider.embed([text], query=True)[0])
    rows = conn.execute(
        "SELECT owner_table, owner_id, chunk_start, chunk_end FROM embeddings WHERE organization_id=%s AND model=%s "
        "ORDER BY embedding <=> %s::vector LIMIT %s", (org, provider.embed_model, v, limit * 3)).fetchall()
    ranked, spans = [], {}
    for r in rows:
        key = ("record" if r["owner_table"] == "source_records" else "fact", r["owner_id"])
        if key not in spans:
            ranked.append(key)
            spans[key] = (r["chunk_start"], r["chunk_end"])
    return ranked[:limit], spans


def _hydrate(conn, org, keys: list[tuple[str, int]], spans: dict, headline_q: str) -> dict[tuple[str, int], Hit]:
    out: dict[tuple[str, int], Hit] = {}
    rec_ids = [i for k, i in keys if k == "record"]
    fact_ids = [i for k, i in keys if k == "fact"]
    for r in conn.execute(
            "SELECT s.id, s.source_type, s.source_id, s.source_url, s.title, s.body, r.name AS repo, "
            "ts_headline('english', s.body, websearch_to_tsquery('english', %s), "
            "'MaxFragments=2,MaxWords=60,MinWords=20,StartSel=,StopSel=') AS head, "
            "(SELECT f.status FROM facts f WHERE f.organization_id=s.organization_id AND f.fact_type='decision' "
            " AND f.source_type='adr' AND f.source_id=s.source_id LIMIT 1) AS decision_status "
            "FROM source_records s LEFT JOIN repositories r ON r.id=s.repository_id WHERE s.id = ANY(%s)",
            (headline_q, rec_ids)):
        span = spans.get(("record", r["id"]))
        body = r["body"] or ""
        passage = body[span[0]:span[1]] if span and span[1] else (r["head"] or body)
        out[("record", r["id"])] = Hit("record", r["id"], r["title"] or r["source_id"], passage.strip(),
                                       r["source_type"], r["source_id"], r["source_url"], repo=r["repo"],
                                       status=r["decision_status"])
    for r in conn.execute("SELECT f.id, f.fact_type, f.summary, f.source_type, f.source_id, f.source_url, "
                          "f.evidence_type, f.status, r.name AS repo FROM facts f "
                          "LEFT JOIN repositories r ON r.id=f.repository_id WHERE f.id = ANY(%s)", (fact_ids,)):
        out[("fact", r["id"])] = Hit("fact", r["id"], f"[{r['fact_type']}] {r['summary']}", r["summary"],
                                     r["source_type"], r["source_id"], r["source_url"], r["evidence_type"],
                                     r["status"], r["repo"])
    return out


def search_with_meta(conn: psycopg.Connection, org_id: int, provider: Provider, query: str, k: int = 10,
                     per_signal: int = 40) -> tuple[list[Hit], dict]:
    s = get_settings()
    meta: dict = {"mode": "lexical", "analysis": None, "semantic": bool(provider.semantic_embeddings)}
    analysis = None
    try:
        analysis = run_task(conn, org_id, provider, "query_analysis", tasks.QUERY_ANALYSIS["system"],
                            {"question": query}, tasks.QUERY_ANALYSIS["schema"])
        meta.update(mode="llm", analysis=analysis)
    except LLMUnavailable:
        pass
    queries = list(dict.fromkeys([query] + (analysis["search_queries"] if analysis else [])))
    exact = _exact(conn, org_id, " ".join([query] + (analysis["identifiers"] if analysis else [])))
    kw_lists = [_keyword_ranked(conn, org_id, q, per_signal) for q in queries]
    vec, spans = [], {}
    if provider.semantic_embeddings:
        vec, spans = _vector(conn, org_id, provider, (analysis or {}).get("answer_sketch") or query, per_signal)
    scores: dict[tuple[str, int], float] = {}
    sig: dict[tuple[str, int], dict[str, int]] = {}
    lists = [("identifier", exact)] + [(f"keyword{'' if n == 0 else n + 1}", lst) for n, lst in enumerate(kw_lists)] \
        + [("vector", vec)]
    for name, lst in lists:
        for rank, key in enumerate(lst, 1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            sig.setdefault(key, {})[name] = rank
    # An explicitly named record (ticket key, decision id) is the answer to "show me X": pin it ahead of fused results.
    pinned = list(dict.fromkeys(exact))
    rest = [x for x in sorted(scores, key=lambda x: (-scores[x], x)) if x not in set(pinned)]
    pool = (pinned + rest)[:max(k, s.rerank_pool)]
    hyd = _hydrate(conn, org_id, pool, spans, queries[-1] if len(queries) > 1 else query)
    hits = []
    for key in pool:
        if key in hyd:
            h = hyd[key]
            h.score, h.signals = round(scores[key], 5), sig[key]
            hits.append(h)
    if analysis and hits:
        try:
            graded = run_task(conn, org_id, provider, "rerank", tasks.RERANK["system"], {
                "query": query, "candidates": [{"id": h.ref, "type": h.source_type, "title": h.title,
                                                "status": h.status, "passage": h.snippet} for h in hits]},
                tasks.RERANK["schema"])
            grade = {g["id"]: g for g in graded["ranked"] if g.get("id") in {h.ref for h in hits}}
            for h in hits:
                g = grade.get(h.ref)
                h.relevance, h.reason = (int(g["relevance"]), g["reason"]) if g else (None, None)
            meta["dropped_irrelevant"] = sum(1 for h in hits if h.relevance == 0)
            pin = {h.key for h in hits if h.key in set(pinned)}
            hits = sorted((h for h in hits if h.relevance != 0 or h.key in pin),
                          key=lambda h: (h.key not in pin, -(h.relevance or 0), -h.score, h.id))
            meta["mode"] = "llm+rerank"
        except LLMUnavailable:
            pass
    return hits[:k], meta


def search(conn: psycopg.Connection, org_id: int, provider: Provider, query: str, k: int = 10,
           per_signal: int = 40) -> list[Hit]:
    return search_with_meta(conn, org_id, provider, query, k, per_signal)[0]
