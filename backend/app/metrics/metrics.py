"""Usage and results numbers for the dashboard.

Three kinds of figure, never mixed:
  measured   counted or timed by the system or by a person with a stopwatch (event counts, response times, ratings, timed tasks);
  rated      a person's judgment of one answer (correct / not, resolved / not);
  estimate   arithmetic on an assumption the viewer typed in; it is labelled and never stored as a result.
A comparison with manual work is shown only when at least `MIN_PAIRS` tasks were timed both ways; before that the dashboard says
how many more are needed. No saving is claimed from anything else.
"""
from __future__ import annotations

import json
import statistics
from typing import Any

import psycopg

MIN_PAIRS = 5
REPEAT_TYPES = ("past_guidance", "decision_violation", "superseded_reference")


def record(conn: psycopg.Connection, org: int, uid: int | None, kind: str, duration_ms: int | None, detail: dict) -> int:
    row = conn.execute("INSERT INTO usage_events (organization_id, user_id, kind, duration_ms, detail) VALUES (%s,%s,%s,%s,%s::jsonb) "
                       "RETURNING id", (org, uid, kind, duration_ms, json.dumps(detail, default=str))).fetchone()
    return row["id"]


def ask_detail(out: dict) -> dict:
    return {"status": out.get("status"), "statements": len(out.get("answer") or []), "dropped": len(out.get("dropped") or []),
            "citations": len(out.get("citations") or [])}


def review_detail(out: dict, repo: str, number: int) -> dict:
    items = [{"repo": repo, "pr": number, "type": c["type"], "source": (c.get("earlier") or {}).get("id") or (c["evidence"] or [None])[0]}
             for c in out.get("comments", []) if c["type"] in REPEAT_TYPES]
    return {"status": out.get("status"), "repo": repo, "pr": number, "comments": len(out.get("comments", [])),
            "dropped": len(out.get("dropped", [])), "repeats": items}


def feedback(conn: psycopg.Connection, org: int, uid: int | None, event_id: int, resolved: bool, correct: str, onboarding: bool) -> bool:
    if conn.execute("SELECT 1 FROM usage_events WHERE id=%s AND organization_id=%s AND kind='ask'", (event_id, org)).fetchone() is None:
        return False
    conn.execute("DELETE FROM answer_feedback WHERE event_id=%s AND user_id IS NOT DISTINCT FROM %s", (event_id, uid))
    conn.execute("INSERT INTO answer_feedback (organization_id, event_id, user_id, resolved, correct, onboarding) VALUES (%s,%s,%s,%s,%s,%s)",
                 (org, event_id, uid, resolved, correct, onboarding))
    return True


def record_timed(conn: psycopg.Connection, org: int, uid: int | None, task: str, arm: str, seconds: float, found: bool) -> None:
    conn.execute("INSERT INTO timed_tasks (organization_id, user_id, task, arm, seconds, found) VALUES (%s,%s,%s,%s,%s,%s)",
                 (org, uid, task.strip()[:300], arm, seconds, found))


def _med(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 1) if xs else None


def timed_comparison(conn: psycopg.Connection, org: int) -> dict:
    rows = conn.execute("SELECT task, arm, seconds::float s, found FROM timed_tasks WHERE organization_id=%s", (org,)).fetchall()
    by: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        if r["found"]:  # a task not completed has no honest "time to find"; it is counted separately
            by.setdefault(r["task"], {"manual": [], "gitwhy": []})[r["arm"]].append(r["s"])
    pairs = [(statistics.median(v["manual"]), statistics.median(v["gitwhy"])) for v in by.values() if v["manual"] and v["gitwhy"]]
    out: dict[str, Any] = {"timed_tasks": len(rows), "not_found": sum(1 for r in rows if not r["found"]), "paired_tasks": len(pairs),
                           "needed_pairs": MIN_PAIRS, "manual_median_s": _med([r["s"] for r in rows if r["arm"] == "manual" and r["found"]]),
                           "gitwhy_median_s": _med([r["s"] for r in rows if r["arm"] == "gitwhy" and r["found"]]), "comparison": None}
    if len(pairs) >= MIN_PAIRS:
        diffs = [m - g for m, g in pairs]
        out["comparison"] = {"paired_tasks": len(pairs), "median_manual_s": _med([m for m, _ in pairs]),
                             "median_gitwhy_s": _med([g for _, g in pairs]), "median_difference_s": _med(diffs),
                             "faster_in": sum(1 for d in diffs if d > 0), "of": len(pairs)}
    return out


def summary(conn: psycopg.Connection, org: int, assumed_minutes: float | None = None) -> dict:
    ev = conn.execute("SELECT kind, duration_ms, detail FROM usage_events WHERE organization_id=%s", (org,)).fetchall()
    asks = [e for e in ev if e["kind"] == "ask"]
    answered = [e for e in asks if e["detail"].get("status") in ("answered", "partial")]
    shown = sum(e["detail"].get("statements", 0) for e in asks)
    dropped = sum(e["detail"].get("dropped", 0) for e in asks)
    repeats = {(r["repo"], r["pr"], r["source"]) for e in ev if e["kind"] == "review" for r in e["detail"].get("repeats", [])}
    fb = conn.execute("SELECT resolved, correct, onboarding FROM answer_feedback WHERE organization_id=%s", (org,)).fetchall()
    rated = [f for f in fb if f["correct"] != "unsure"]
    out: dict[str, Any] = {
        "measured": {
            "questions_asked": len(asks), "questions_answered": len(answered),
            "median_seconds_to_sourced_answer": _med([e["duration_ms"] / 1000 for e in answered if e["duration_ms"] is not None]),
            # a repeat of a question already judged is served from saved judgments in well under a second; first-time questions pay for the model
            "median_seconds_first_time_question": _med([e["duration_ms"] / 1000 for e in answered if e["detail"].get("live_calls")]),
            "first_time_questions": sum(1 for e in answered if e["detail"].get("live_calls")),
            "prs_reviewed": sum(1 for e in ev if e["kind"] == "review"), "repeated_issues_detected": len(repeats),
            "other": {k: sum(1 for e in ev if e["kind"] == k) for k in ("plan", "handover", "impact", "departure")},
            "citations": {"statements_shown": shown, "statements_removed_by_guard": dropped,
                          "note": "Every shown statement cites a source that exists and quotes are literal; the guard removed the rest."},
        },
        "rated_by_people": {
            "ratings": len(fb), "resolved": sum(1 for f in fb if f["resolved"]),
            "answers_correct": sum(1 for f in rated if f["correct"] == "yes"), "answers_incorrect": sum(1 for f in rated if f["correct"] == "no"),
            "correct_share": round(sum(1 for f in rated if f["correct"] == "yes") / len(rated), 3) if rated else None,
            "onboarding_questions_resolved": sum(1 for f in fb if f["onboarding"] and f["resolved"]),
        },
        "timed": timed_comparison(conn, org),
        "estimate": None,
    }
    if assumed_minutes is not None and assumed_minutes > 0:
        out["estimate"] = {"label": "Estimate, not a measurement", "assumed_minutes_saved_per_answer": assumed_minutes,
                           "hours": round(len(answered) * assumed_minutes / 60, 1),
                           "based_on": f"{len(answered)} answered questions × your assumption"}
    return out
