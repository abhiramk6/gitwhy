"""Ask: a question about the organization, answered from retrieved evidence with a citation on every statement.

Retrieval is the shared hybrid search (model query analysis + rerank). The model writes the answer as statements, each
citing evidence ids; the guard drops any statement without a valid citation, so nothing is asserted that has no source.
Trust labels and statuses on citations come from the stored evidence, never from the model.
"""
from __future__ import annotations

import json

import psycopg

from ..intelligence import tasks as T
from ..intelligence.judge import run_task
from ..models.provider import LLMUnavailable, Provider
from ..retrieval.search import Hit, search_with_meta

K = 12


def _label(h: Hit) -> str:
    if h.kind == "fact":
        return "verified" if h.evidence_type in ("structural", "explicit") and h.status == "active" else "inferred"
    return "superseded" if h.status == "superseded" else "source"


def _who_when(conn, org: int, rec_ids: list[int]) -> dict[int, dict]:
    out = {}
    for r in conn.execute("SELECT id, source_type, payload FROM source_records WHERE organization_id=%s AND id = ANY(%s)",
                          (org, rec_ids)):
        p = r["payload"] or {}
        out[r["id"]] = {"author": p.get("author") or p.get("assignee"),
                        "date": p.get("date") or p.get("merged_at") or p.get("updated") or p.get("created_at"),
                        "path": p.get("path"), "kind": p.get("kind")}
    return out


def _citation(h: Hit, meta: dict) -> dict:
    return {"id": h.ref, "label": _label(h), "status": h.status, "source_type": h.source_type, "source_id": h.source_id,
            "title": h.title, "url": h.source_url, "repo": h.repo, "excerpt": h.snippet[:1200], **meta}


def ask(conn: psycopg.Connection, org: int, provider: Provider, question: str,
        history: list[dict] | None = None) -> dict:
    history = (history or [])[-6:]
    query = question if not history else f"{history[-1].get('question', '')} {question}".strip()
    try:
        hits, smeta = search_with_meta(conn, org, provider, query, K)
    except LLMUnavailable:
        hits, smeta = [], {}
    if not provider.has_llm:
        return {"status": "llm_required", "question": question, "answer": [], "citations": [], "retrieval": smeta,
                "note": "Asking needs a model; configure PROVIDER=gemini or vertex."}
    who = _who_when(conn, org, [h.id for h in hits if h.kind == "record"])
    cites = {h.ref: _citation(h, who.get(h.id, {}) if h.kind == "record" else {}) for h in hits}
    if not cites:
        return {"status": "insufficient", "question": question, "answer": [], "citations": [], "retrieval": smeta,
                "note": "Nothing in the organization's sources matched this question."}
    payload = {"question": question,
               "earlier_turns": [{"question": t.get("question"), "answer": t.get("text")} for t in history],
               "evidence": [{"id": c["id"], "type": c["source_type"], "status": c["status"], "title": c["title"],
                             "author": c.get("author"), "date": c.get("date"), "path": c.get("path"),
                             "text": c["excerpt"]} for c in cites.values()]}
    try:
        res = run_task(conn, org, provider, "ask", T.ASK["system"], payload, T.ASK["schema"])
    except LLMUnavailable as exc:
        return {"status": "llm_required", "question": question, "answer": [], "citations": [], "retrieval": smeta,
                "note": str(exc)}
    answer, used = [], []
    for seg in res["answer"]:
        ids = [i for i in dict.fromkeys(seg.get("cites") or []) if i in cites]
        if not seg["text"].strip() or not ids:
            continue                       # no valid source => the statement is not shown
        answer.append({"text": seg["text"].strip(), "cites": ids})
        used += [i for i in ids if i not in used]
    status = "answered" if answer and res["sufficient"] else ("partial" if answer else "insufficient")
    return {"status": status, "question": question, "answer": answer,
            "citations": [cites[i] for i in used], "follow_ups": res["follow_ups"][:3], "retrieval": smeta,
            "considered": len(cites)}
