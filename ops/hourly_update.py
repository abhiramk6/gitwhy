#!/usr/bin/env python3
"""Hourly status to the Telegram group: at most 5 short lines, or one line if nothing changed.

Runs as its own process (tmux window lore:hourly), independent of any agent session, so it keeps firing while the
session is idle or its usage limit is hit. It does not survive a host reboot. Everything is read mechanically:
  - coverage and quota state from the database, scheduler liveness from its pid file,
  - commits since the last update from git, owner-pending items from DECISIONS.md ('## Waiting on owner'),
  - the 'next' line from ops/NEXT.txt (maintained by the agent at milestones).
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
STATE = Path.home() / ".config/lore/hourly_state.json"
SCHED_PID = Path(os.environ.get("EMBED_SCHEDULE_PID", "/tmp/agent-0/-root-lore-intelligence/"
                 "b5139bff-47bc-4e91-ab42-99c5942473ed/scratchpad/embed_schedule.pid"))
MODEL = "voyage-4-large"   # OSS corpus embedding model (Voyage AI); the Gemini embedding plan was abandoned 2026-10-16
INTERVAL = int(os.environ.get("HOURLY_INTERVAL_S", "3600"))


def git(*a: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()


def waiting_on_owner() -> list[str]:
    txt = (ROOT / "DECISIONS.md").read_text() if (ROOT / "DECISIONS.md").exists() else ""
    sec = txt.split("## Waiting on owner", 1)[-1].split("\n## ", 1)[0] if "## Waiting on owner" in txt else ""
    lines = [l.strip() for l in sec.splitlines() if l.strip()]
    return [] if not lines or lines[0].startswith("_none") else lines


def snapshot() -> dict:
    from app.db import connect
    from app.retrieval.embed import coverage_text, tier_coverage

    with connect() as c:
        org = c.execute("SELECT id FROM organizations WHERE slug='oss-pallets'").fetchone()["id"]
        rows = tier_coverage(c, org, MODEL)
        q = c.execute("SELECT exhausted_until, note FROM quota_state WHERE model=%s", (MODEL,)).fetchone()
        used = c.execute("SELECT coalesce(sum(items),0) n FROM embed_usage WHERE model=%s AND kind='index' "
                         "AND day=(now() AT TIME ZONE 'utc')::date", (MODEL,)).fetchone()["n"]
    wins = subprocess.run(["tmux", "list-windows", "-t", "lore", "-F", "#{window_name}"], capture_output=True, text=True).stdout.split()
    alive = "voyage" in wins            # the Voyage pass runs in tmux window lore:voyage
    stored, wanted = sum(r["stored"] for r in rows), sum(r["wanted"] for r in rows)
    until = q["exhausted_until"] if q and q["exhausted_until"] > datetime.now(timezone.utc) else None
    return {"stored": stored, "wanted": wanted, "tiers": coverage_text(rows), "alive": alive,
            "until": until.strftime("%b %d %H:%M UTC") if until else None, "used_today": used,
            "note": (q or {}).get("note"), "head": git("rev-parse", "HEAD"),
            "next": (ROOT / "ops/NEXT.txt").read_text().strip() if (ROOT / "ops/NEXT.txt").exists() else "",
            "waiting": waiting_on_owner()}


def compose(cur: dict, prev: dict | None) -> str:
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    state = ("Voyage embedding pass " + ("running" if cur["alive"] else "not running")
             + (f", waiting until {cur['until']}" if cur["until"] else ""))
    if prev and all(cur[k] == prev.get(k) for k in ("stored", "head", "next", "waiting", "note", "alive")):
        extra = f" Waiting on you: {'; '.join(cur['waiting'])}" if cur["waiting"] else ""
        return f"{now} — No change since last update. Coverage {cur['stored']} of {cur['wanted']} chunks; {state}.{extra}"
    new = git("log", "--format=%s", f"{prev['head']}..HEAD") if prev and prev.get("head") else ""
    done = [l for l in new.splitlines() if l][:2]
    lines = [f"{now} — Running: {state}.",
             f"Coverage: {cur['stored']} of {cur['wanted']} chunks ({cur['tiers']}).",
             "Done since last update: " + ("; ".join(d[:70] for d in done) if done else "no new commits") + ".",
             "Blocked / waiting on you: " + ("; ".join(cur["waiting"]) if cur["waiting"] else "nothing")
             + (f"; NOTE: {cur['note']}" if cur["note"] and "EARLY" in cur["note"].upper() else "") + ".",
             f"Next: {(cur['next'] or 'continue current work').rstrip('.')}."]
    return "\n".join(lines)


def main() -> int:
    once = "--once" in sys.argv
    while True:
        try:
            prev = json.loads(STATE.read_text()) if STATE.exists() else None
            cur = snapshot()
            msg = compose(cur, prev)
            if "--dry" in sys.argv:
                print(msg)
            else:
                subprocess.run([str(ROOT / "ops/notify.sh"), msg], capture_output=True)
                STATE.write_text(json.dumps(cur))
        except Exception as exc:  # never die silently: say so once and keep the schedule
            subprocess.run([str(ROOT / "ops/notify.sh"), f"hourly update failed to compose: {type(exc).__name__}: {str(exc)[:120]}"],
                           capture_output=True)
        if once:
            return 0
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
