"""Embed admitted content by chunk, once per (owner, chunk, model); unchanged chunks are never re-embedded.

Every chunk of every admitted record is embedded (no prefix truncation). Commits are not admitted: their value is
in the PR/issue that explains them. With a provider that has no semantic embeddings nothing is embedded at all.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import psycopg

from ..config import get_settings
from ..models.provider import Provider, QuotaExhausted
from .chunk import chunk_spans

EMBED_SOURCE_TYPES = ("adr", "doc", "github_pr", "jira_issue", "file")
BATCH = 64
# Embedding priority: the team's decisions and the tickets/PRs that explain them come before prose docs and code.
TIERS = ("adr", "fact", "jira_issue", "github_pr", "doc", "file")
TIER_LABEL = {"adr": "ADRs", "fact": "facts", "jira_issue": "issues", "github_pr": "PRs", "doc": "docs", "file": "code"}


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def wanted_chunks(conn: psycopg.Connection, org_id: int) -> dict[tuple[str, int, int], tuple[str, int, int, str]]:
    """Every chunk that must have a vector: (table, id, chunk_index) -> (content_hash, start, end, text).
    Single source of truth for embed_org and for reconcile()."""
    want: dict[tuple[str, int, int], tuple[str, int, int, str]] = {}
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
    return want


def reconcile(conn: psycopg.Connection, org_id: int, model: str) -> dict:
    """Compare wanted chunks with stored vectors of `model`. Nothing is silently missing: every difference is listed
    with its reason."""
    want = wanted_chunks(conn, org_id)
    have = {(r["owner_table"], r["owner_id"], r["chunk_index"]): r["content_hash"] for r in conn.execute(
        "SELECT owner_table, owner_id, chunk_index, content_hash FROM embeddings WHERE organization_id=%s AND model=%s",
        (org_id, model))}
    return {"wanted": len(want), "stored": len(have),
            "missing": sorted(k for k in want if k not in have),
            "stale_content": sorted(k for k in want if k in have and have[k] != want[k][0]),
            "orphaned": sorted(k for k in have if k not in want),
            "title_only_empty_body": sum(1 for k, v in want.items() if k[0] == "source_records" and v[2] == 0)}


def chunk_tiers(conn: psycopg.Connection, org_id: int) -> dict[tuple[str, int, int], str]:
    """Tier of every wanted chunk (adr/fact/jira_issue/github_pr/doc/file)."""
    kind = {r["id"]: r["source_type"] for r in conn.execute(
        "SELECT id, source_type FROM source_records WHERE organization_id=%s", (org_id,))}
    return {k: ("fact" if k[0] == "facts" else kind.get(k[1], "file")) for k in wanted_chunks(conn, org_id)}


def tier_coverage(conn: psycopg.Connection, org_id: int, model: str) -> list[dict]:
    """Per tier: chunks wanted vs stored (current content) for `model`, in priority order."""
    want = wanted_chunks(conn, org_id)
    tiers = chunk_tiers(conn, org_id)
    have = {(r["owner_table"], r["owner_id"], r["chunk_index"]): r["content_hash"] for r in conn.execute(
        "SELECT owner_table, owner_id, chunk_index, content_hash FROM embeddings WHERE organization_id=%s AND model=%s",
        (org_id, model))}
    out = []
    for t in TIERS:
        keys = [k for k, tier in tiers.items() if tier == t]
        out.append({"tier": t, "label": TIER_LABEL[t], "wanted": len(keys),
                    "stored": sum(1 for k in keys if have.get(k) == want[k][0])})
    return out


def coverage_text(rows: list[dict]) -> str:
    return " · ".join(f"{r['label']} {r['stored']}/{r['wanted']}" for r in rows) + \
        f" · total {sum(r['stored'] for r in rows)}/{sum(r['wanted'] for r in rows)}"


def used_today(conn: psycopg.Connection, model: str, kind: str = "index") -> int:
    r = conn.execute("SELECT items FROM embed_usage WHERE day = (now() AT TIME ZONE 'UTC')::date AND model=%s AND kind=%s",
                     (model, kind)).fetchone()
    return r["items"] if r else 0


def record_usage(conn: psycopg.Connection, model: str, kind: str, items: int) -> None:
    conn.execute("INSERT INTO embed_usage (day, model, kind, items) VALUES ((now() AT TIME ZONE 'UTC')::date, %s, %s, %s) "
                 "ON CONFLICT (day, model, kind) DO UPDATE SET items = embed_usage.items + EXCLUDED.items",
                 (model, kind, items))


CHARS_PER_TOKEN = 3.0  # same over-estimate the provider uses for request sizing


def est_spend_tokens(conn: psycopg.Connection, model: str) -> int:
    r = conn.execute("SELECT est_tokens FROM embed_spend WHERE model=%s", (model,)).fetchone()
    return int(r["est_tokens"]) if r else 0


def record_spend(conn: psycopg.Connection, model: str, tokens: int) -> None:
    conn.execute("INSERT INTO embed_spend (model, est_tokens) VALUES (%s, %s) ON CONFLICT (model) DO UPDATE SET "
                 "est_tokens = embed_spend.est_tokens + EXCLUDED.est_tokens, updated_at = now()", (model, tokens))


def exhausted_until(conn: psycopg.Connection, model: str):
    r = conn.execute("SELECT exhausted_until FROM quota_state WHERE model=%s AND exhausted_until > now()", (model,)).fetchone()
    return r["exhausted_until"] if r else None


def embed_org(conn: psycopg.Connection, org_id: int, provider: Provider, budget: int | None = None,
              max_usd: float | None = None, price_per_mtok: float = 0.15) -> dict:
    """Embed missing/changed chunks in tier order. `budget` caps items sent in this call (None = unlimited). Stops
    cleanly on budget, a hard quota or (paid mode) the dollar cap `max_usd`; never loops or retries on its own. Progress commits per batch."""
    if not provider.semantic_embeddings:
        return {"candidates": 0, "embedded": 0, "cached": 0, "skipped": "provider has no semantic embeddings"}
    want = wanted_chunks(conn, org_id)
    have = {(r["owner_table"], r["owner_id"], r["chunk_index"]): r["content_hash"] for r in conn.execute(
        "SELECT owner_table, owner_id, chunk_index, content_hash FROM embeddings WHERE organization_id=%s AND model=%s",
        (org_id, provider.embed_model))}
    stale = [k for k in have if k not in want]
    for t, i, c in stale:
        conn.execute("DELETE FROM embeddings WHERE organization_id=%s AND model=%s AND owner_table=%s AND owner_id=%s "
                     "AND chunk_index=%s", (org_id, provider.embed_model, t, i, c))
    tiers = chunk_tiers(conn, org_id)
    order = {t: i for i, t in enumerate(TIERS)}
    todo = sorted(((k, v) for k, v in want.items() if have.get(k) != v[0]),
                  key=lambda kv: (order[tiers[kv[0]]], kv[0]))
    stopped, sent = None, 0
    until = exhausted_until(conn, provider.embed_model)
    if until is not None:
        todo_run, stopped = [], f"quota exhausted until {until.isoformat(timespec='seconds')}"
    else:
        todo_run = todo
    for b in range(0, len(todo_run), BATCH):
        part = todo_run[b:b + BATCH]
        if budget is not None:
            room = budget - sent
            if room <= 0:
                stopped = f"daily budget of {budget} items reached"
                break
            part = part[:room]
        if max_usd is not None:
            est = int(sum(len(v[3]) for _, v in part) / CHARS_PER_TOKEN) + 1
            if (est_spend_tokens(conn, provider.embed_model) + est) * price_per_mtok / 1e6 > max_usd:
                stopped = f"spend cap ${max_usd:.2f} reached (estimated)"
                break
        try:
            vecs = provider.embed([v[3] for _, v in part])
        except QuotaExhausted as exc:
            conn.execute("INSERT INTO quota_state (model, exhausted_until, note) VALUES (%s, now() + make_interval(secs => %s), %s) "
                         "ON CONFLICT (model) DO UPDATE SET exhausted_until=EXCLUDED.exhausted_until, note=EXCLUDED.note, "
                         "updated_at=now()", (provider.embed_model, exc.retry_after_s, str(exc)[:200]))
            conn.commit()
            stopped = f"hard quota hit: {exc}"
            break
        for ((t, i, c), (h, s, e, _x)), vec in zip(part, vecs):
            conn.execute(
                "INSERT INTO embeddings (organization_id, owner_table, owner_id, chunk_index, chunk_start, chunk_end,"
                " content_hash, model, embedding) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::vector) "
                "ON CONFLICT (owner_table, owner_id, model, chunk_index) DO UPDATE SET content_hash=EXCLUDED.content_hash,"
                " chunk_start=EXCLUDED.chunk_start, chunk_end=EXCLUDED.chunk_end, embedding=EXCLUDED.embedding",
                (org_id, t, i, c, s, e, h, provider.embed_model, _vec(vec)))
        sent += len(part)
        record_usage(conn, provider.embed_model, "index", len(part))  # only items the API accepted
        if max_usd is not None:
            record_spend(conn, provider.embed_model, int(sum(len(v[3]) for _, v in part) / CHARS_PER_TOKEN) + 1)
        conn.commit()  # progress survives an interrupted run; unchanged chunks are skipped on the next one
        if budget is not None and sent >= budget and sent < len(todo_run):
            stopped = f"daily budget of {budget} items reached"
            break
    return {"candidates": len(want), "embedded": sent, "pending": len(todo) - sent, "cached": len(want) - len(todo),
            "removed": len(stale), "stopped": stopped, "coverage": tier_coverage(conn, org_id, provider.embed_model)}


def main() -> int:
    """One pass, no retries: `python -m app.retrieval.embed [--budget N]` (org from ORG_SLUG, model from env)."""
    import argparse
    import json

    from ..db import connect
    from ..models.provider import make_provider

    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=None, help="max items this pass (default: daily budget remaining)")
    a = ap.parse_args()
    s = get_settings()
    prov = make_provider(s)
    with connect() as conn:
        org = conn.execute("SELECT id FROM organizations WHERE slug=%s", (s.org_slug,)).fetchone()["id"]
        if s.embed_paid:  # no item cap on the paid tier; the dollar cap is the guard
            budget = a.budget
            res = embed_org(conn, org, prov, budget=budget, max_usd=s.embed_max_usd, price_per_mtok=s.embed_price_per_mtok)
            res["est_spend_usd"] = round(est_spend_tokens(conn, prov.embed_model) * s.embed_price_per_mtok / 1e6, 4)
            res["spend_cap_usd"] = s.embed_max_usd
        else:
            budget = a.budget if a.budget is not None else max(0, s.embed_daily_budget - used_today(conn, prov.embed_model))
            res = embed_org(conn, org, prov, budget=budget)
        res["budget_this_pass"] = budget
        res["coverage_text"] = coverage_text(res["coverage"])
        res["used_today_index"] = used_today(conn, prov.embed_model)
        if (res["stopped"] or "").startswith("hard quota") and budget is not None and res["used_today_index"] < budget:
            # The API cap was hit before our own ledger predicted it: record it for the owner, stop for the day.
            note = (f"cap hit EARLY: API refused after {res['used_today_index']} accepted index items today "
                    f"(ledger budget {budget}); embedding stopped for the day")
            conn.execute("UPDATE quota_state SET note=%s WHERE model=%s", (note, prov.embed_model))
            conn.commit()
            from datetime import datetime, timezone
            root = Path(__file__).resolve().parents[3]
            with (root / "DECISIONS.md").open("a") as fh:
                fh.write(f"- {datetime.now(timezone.utc):%Y-%m-%d %H:%M} — EMBEDDING CAP EARLY: {note}.\n")
            res["early_cap"] = note
    print(json.dumps(res, default=str))
    return 3 if (res["stopped"] or "").startswith(("hard quota", "quota exhausted")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
