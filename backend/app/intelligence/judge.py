"""Run one model judgment: cached, replayable, and never silently invented.

Every judgment is keyed by (organization, task, hash(system+payload), model). With demo_mode a cached answer is
replayed without calling the model, so demos are repeatable and a deployment can serve answers with the model off.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

import psycopg

from ..models.provider import LLMUnavailable, Provider


@dataclass
class Meter:
    """What a process actually asked of the model layer: live calls, answers replayed from the judgment cache
    (with the model that originally produced each), and judgments that could not be made. Reports print this so a
    cached answer is never presented as a fresh model call, and a skipped judgment is never presented as a pass."""
    live: int = 0
    replayed: int = 0
    unavailable: int = 0
    replay_models: dict[str, int] = field(default_factory=dict)
    by_task: dict[str, dict[str, int]] = field(default_factory=dict)

    def snapshot(self) -> dict:
        return {"live": self.live, "replayed": self.replayed, "unavailable": self.unavailable,
                "replay_models": dict(self.replay_models),
                "by_task": {k: dict(v) for k, v in self.by_task.items()}}

    def _bump(self, task: str, kind: str) -> None:
        self.by_task.setdefault(task, {"live": 0, "replayed": 0, "unavailable": 0})[kind] += 1

    def reset(self) -> None:
        self.live = self.replayed = self.unavailable = 0
        self.replay_models.clear()
        self.by_task.clear()


meter = Meter()


def delta(before: dict, after: dict) -> dict:
    return {k: after[k] - before[k] for k in ("live", "replayed", "unavailable")}


def input_hash(task: str, system: str, user: str) -> str:
    return hashlib.sha256("\x1f".join((task, system, user)).encode()).hexdigest()


def run_task(conn: psycopg.Connection, org: int, provider: Provider, task: str, system: str, payload: dict,
             schema: dict) -> dict:
    user = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    key = input_hash(task, system, user)
    models = list(getattr(provider, "models", None) or [provider.name])
    # With a live model only answers from its own model chain count; with none, replay the newest from any model.
    row = conn.execute("SELECT output, model FROM llm_judgments WHERE organization_id=%s AND task=%s AND input_hash=%s "
                       "AND (model = ANY(%s) OR NOT %s) ORDER BY id DESC LIMIT 1",
                       (org, task, key, models, provider.has_llm)).fetchone()
    if row:
        meter.replayed += 1
        meter._bump(task, "replayed")
        meter.replay_models[row["model"]] = meter.replay_models.get(row["model"], 0) + 1
        return row["output"]
    if not provider.has_llm:
        meter.unavailable += 1
        meter._bump(task, "unavailable")
        raise LLMUnavailable(f"task '{task}' needs an LLM and no cached judgment exists")
    out = provider.generate_json(f"[task:{task}]\n{system}", user, schema)
    meter.live += 1
    meter._bump(task, "live")
    model = getattr(provider, "last_model", None) or provider.name
    conn.execute("INSERT INTO llm_judgments (organization_id, task, input_hash, model, output) VALUES (%s,%s,%s,%s,%s::jsonb) "
                 "ON CONFLICT (organization_id, task, input_hash, model) DO NOTHING",
                 (org, task, key, model, json.dumps(out)))
    if getattr(provider, "usage", None) is not None:
        conn.commit()  # a paid model answer is never lost to a later failure in the same job
    return out
