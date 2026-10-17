#!/usr/bin/env python3
"""Hourly status to the Telegram group: at most 5 short lines, or one line if nothing changed.

Runs as its own process (tmux window gitwhy:hourly), independent of any agent session, so it keeps firing while the
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
_VENV_PY = ROOT / "backend/.venv/bin/python"
if _VENV_PY.exists() and Path(sys.prefix).resolve() != (ROOT / "backend/.venv").resolve():
    os.execv(str(_VENV_PY), [str(_VENV_PY), *sys.argv])   # started with the system python: re-run under the venv that has psycopg
sys.path.insert(0, str(ROOT / "backend"))
STATE = Path.home() / ".config/gitwhy/hourly_state.json"
MODEL = "voyage-4-large"   # OSS corpus embedding model (Voyage AI); the Gemini embedding plan was abandoned 2026-10-16
INTERVAL = int(os.environ.get("HOURLY_INTERVAL_S", "3600"))


def git(*a: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()


def waiting_on_owner() -> list[str]:
    txt = (ROOT / "DECISIONS.md").read_text() if (ROOT / "DECISIONS.md").exists() else ""
    sec = txt.split("## Waiting on owner", 1)[-1].split("\n## ", 1)[0] if "## Waiting on owner" in txt else ""
    lines = [l.strip() for l in sec.splitlines() if l.strip()]
    return [] if not lines or lines[0].startswith("_none") else lines


def _up(cmd: list[str]) -> bool:
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip() == "active"


def snapshot() -> dict:
    import urllib.request

    from app.db import connect
    from app.retrieval.embed import tier_coverage

    orgs = []
    with connect() as c:
        for o in c.execute("SELECT id, slug FROM organizations WHERE status='ready' ORDER BY id").fetchall():
            rows = tier_coverage(c, o["id"], MODEL)
            wanted = sum(r["wanted"] for r in rows)
            stored = sum(r["stored"] for r in rows)
            if wanted and stored:   # only orgs that have a search index (orgs onboarded without one are not listed)
                orgs.append((o["slug"], stored, wanted))
        q = c.execute("SELECT exhausted_until, note FROM quota_state WHERE model=%s", (MODEL,)).fetchone()
    wins = subprocess.run(["tmux", "list-windows", "-t", "gitwhy", "-F", "#{window_name}"], capture_output=True, text=True).stdout.split()
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/api/meta", timeout=10) as r:
            site = r.status
    except Exception:
        site = 0
    until = q["exhausted_until"] if q and q["exhausted_until"] > datetime.now(timezone.utc) else None
    return {"orgs": [list(o) for o in orgs], "stored": sum(o[1] for o in orgs), "wanted": sum(o[2] for o in orgs),
            "alive": any(w.startswith(("voyage", "embed")) for w in wins), "site": site,
            "services": _up(["systemctl", "is-active", "gitwhy"]) and _up(["systemctl", "is-active", "caddy"]),
            "until": until.strftime("%b %d %H:%M UTC") if until else None, "note": (q or {}).get("note"), "head": git("rev-parse", "HEAD"),
            "next": (ROOT / "ops/NEXT.txt").read_text().strip() if (ROOT / "ops/NEXT.txt").exists() else "",
            "waiting": waiting_on_owner()}


def _cut(text: str, n: int = 150) -> str:
    text = " ".join(text.replace("**", "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def compose(cur: dict, prev: dict | None) -> str:
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    health = (f"site {'up' if cur['site'] == 200 else 'DOWN (HTTP %s)' % cur['site']}, services {'active' if cur['services'] else 'NOT ACTIVE'}"
              + (", embedding pass running" if cur["alive"] else "") + (f", embedding limit until {cur['until']}" if cur["until"] else ""))
    index = ", ".join(f"{slug} {a}/{b}" for slug, a, b in cur["orgs"]) or "no orgs indexed"
    wait = _cut("; ".join(w.lstrip("- ").split(" — ")[0].split(":")[0] for w in cur["waiting"][:3]), 150) if cur["waiting"] else "nothing"
    if prev and all(cur[k] == prev.get(k) for k in ("stored", "head", "next", "waiting", "alive", "site", "services")):
        return _cut(f"{now} — No change. {health}. Search index {index}. Waiting on you: {wait}.", 300)
    new = git("log", "--format=%s", f"{prev['head']}..HEAD") if prev and prev.get("head") else ""
    done = [l for l in new.splitlines() if l][:2]
    lines = [f"{now} — {health}.",
             f"Search index: {index}.",
             "Done since last update: " + ("; ".join(_cut(d, 70) for d in done) if done else "no new commits") + ".",
             f"Waiting on you: {wait}.",
             f"Next: {_cut(cur['next'].splitlines()[0] if cur['next'] else 'continue current work', 150).rstrip('.')}."]
    return "\n".join(lines)


def main() -> int:
    once = "--once" in sys.argv
    last_error = None
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
            last_error = None
        except Exception as exc:  # never die silently: say so once per distinct error and keep the schedule
            err = f"hourly update failed to compose: {type(exc).__name__}: {str(exc)[:120]}"
            if "--dry" in sys.argv:
                print(err)
            elif err != last_error:
                subprocess.run([str(ROOT / "ops/notify.sh"), err], capture_output=True)
            last_error = err
        if once:
            return 0
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
