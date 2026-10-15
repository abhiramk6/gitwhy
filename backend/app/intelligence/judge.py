"""Run one model judgment: cached, replayable, and never silently invented.

Every judgment is keyed by (organization, task, hash(system+payload), model). With demo_mode a cached answer is
replayed without calling the model, so demos are repeatable and a deployment can serve answers with the model off.
"""
from __future__ import annotations

import hashlib
import json

import psycopg

from ..models.provider import LLMUnavailable, Provider


def input_hash(task: str, system: str, user: str) -> str:
    return hashlib.sha256("\x1f".join((task, system, user)).encode()).hexdigest()


def run_task(conn: psycopg.Connection, org: int, provider: Provider, task: str, system: str, payload: dict,
             schema: dict) -> dict:
    user = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    key = input_hash(task, system, user)
    models = list(getattr(provider, "models", None) or [provider.name])
    # With a live model only answers from its own model chain count; with none, replay the newest from any model.
    row = conn.execute("SELECT output FROM llm_judgments WHERE organization_id=%s AND task=%s AND input_hash=%s "
                       "AND (model = ANY(%s) OR NOT %s) ORDER BY id DESC LIMIT 1",
                       (org, task, key, models, provider.has_llm)).fetchone()
    if row:
        return row["output"]
    if not provider.has_llm:
        raise LLMUnavailable(f"task '{task}' needs an LLM and no cached judgment exists")
    out = provider.generate_json(f"[task:{task}]\n{system}", user, schema)
    model = getattr(provider, "last_model", None) or provider.name
    conn.execute("INSERT INTO llm_judgments (organization_id, task, input_hash, model, output) VALUES (%s,%s,%s,%s,%s::jsonb) "
                 "ON CONFLICT (organization_id, task, input_hash, model) DO NOTHING",
                 (org, task, key, model, json.dumps(out)))
    return out
