"""Minimal MCP server (JSON-RPC 2.0 over HTTP POST, tools capability only).

Seven bounded tools; every result is JSON text containing source references, evidence_type and status
so a coding agent can show provenance. Auth: same shared demo token as write endpoints.
"""
from __future__ import annotations

from typing import Any, Callable

import psycopg
from fastapi import APIRouter, Depends, Response
from fastapi.encoders import jsonable_encoder

from ..api import service
from ..api.deps import get_conn, get_org_id, get_provider, require_write
from ..models.provider import Provider

PROTOCOL_VERSION = "2025-03-26"
router = APIRouter()


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


S = {"type": "string"}
TOOLS: dict[str, dict] = {
    "search_context": {"description": "Hybrid (keyword+vector+graph) search over organizational evidence and knowledge.",
                       "inputSchema": _obj({"query": S, "limit": {"type": "integer", "minimum": 1, "maximum": 25}}, ["query"])},
    "get_repo_overview": {"description": "Repositories, counts and active alerts (ownership, risk, override, conflict, reuse).",
                          "inputSchema": _obj({})},
    "get_dependencies": {"description": "Bounded dependency/dependent traversal for services, with per-edge evidence.",
                         "inputSchema": _obj({"services": {"type": "array", "items": S}, "depth": {"type": "integer", "minimum": 1, "maximum": 5}},
                                             ["services"])},
    "get_decisions": {"description": "Architectural decisions with status (active/superseded) and provenance.",
                      "inputSchema": _obj({"status": S})},
    "analyze_feature_impact": {"description": "Impact radius and risks for a feature request, without generating tasks.",
                               "inputSchema": _obj({"request": S, "depth": {"type": "integer", "minimum": 1, "maximum": 5}}, ["request"])},
    "create_feature_plan": {"description": "Evidence-backed feature plan: components, decisions, risks, tasks, tests, open questions.",
                            "inputSchema": _obj({"request": S, "depth": {"type": "integer", "minimum": 1, "maximum": 5}}, ["request"])},
    "record_memory_candidate": {"description": "Record a candidate organizational fact (not active until curated).",
                                "inputSchema": _obj({"text": S, "author": S, "scope": {"enum": ["org", "repo", "team"]}, "repo": S},
                                                    ["text", "author"])},
}


def _call(name: str, a: dict, conn: psycopg.Connection, org: int, provider: Provider) -> Any:
    if name == "search_context":
        return service.do_search(conn, org, provider, a["query"], int(a.get("limit", 8)))
    if name == "get_repo_overview":
        o = service.overview(conn, org)
        return {k: o[k] for k in ("repositories", "counts", "alerts")}
    if name == "get_dependencies":
        return service.dependencies(conn, org, list(a["services"]), int(a.get("depth", 3)))
    if name == "get_decisions":
        return service.knowledge(conn, org, a.get("status"), "decision")
    if name == "analyze_feature_impact":
        p = service.make_plan(conn, org, provider, a["request"], int(a.get("depth", 3)))
        return {k: p.get(k) for k in ("id", "affected_components", "risks", "decisions", "reuse_candidates",
                                      "open_questions", "evidence", "status")}
    if name == "create_feature_plan":
        return service.make_plan(conn, org, provider, a["request"], int(a.get("depth", 3)))
    if name == "record_memory_candidate":
        return service.remember(conn, org, a["text"], a["author"], a.get("scope", "org"), a.get("repo"))
    raise KeyError(name)


def _err(id_: Any, code: int, msg: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": msg}}


@router.post("/mcp", dependencies=[Depends(require_write)])
def mcp(msg: dict, response: Response, conn: psycopg.Connection = Depends(get_conn),
        org: int = Depends(get_org_id), provider: Provider = Depends(get_provider)):
    id_, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if id_ is None:  # notification
        response.status_code = 202
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": id_, "result": {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
            "serverInfo": {"name": "gitwhy", "version": "0.1.0"}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": id_, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": id_, "result": {"tools": [{"name": n, **t} for n, t in TOOLS.items()]}}
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in TOOLS:
            return _err(id_, -32602, f"unknown tool: {name}")
        missing = [r for r in TOOLS[name]["inputSchema"]["required"] if r not in args]
        if missing:
            return _err(id_, -32602, f"missing arguments: {', '.join(missing)}")
        try:
            out = _call(name, args, conn, org, provider)
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": id_, "result": {"isError": True, "content": [
                {"type": "text", "text": f"tool failed: {type(exc).__name__}"}]}}
        import json
        return {"jsonrpc": "2.0", "id": id_, "result": {"content": [
            {"type": "text", "text": json.dumps(jsonable_encoder(out))}]}}
    return _err(id_, -32601, f"method not found: {method}")
