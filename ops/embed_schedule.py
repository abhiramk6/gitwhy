#!/usr/bin/env python3
"""One embedding pass per free-tier quota day for the OSS demo corpus. NOT a retry loop:
 - each pass runs once; a pass that errors (anything but 'done', 'budget reached' or 'quota exhausted') stops the schedule
   and notifies, it is never retried;
 - between passes it sleeps until the API's own reset time (quota_state) or the next UTC midnight, +5 min.
Env: DATABASE_URL, GEMINI_API_KEY (+ ~/.config/lore/telegram.env for notify.sh). Model = gemini-embedding-001.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "gemini-embedding-001"
ENV = {**os.environ, "PROVIDER": "gemini", "EMBED_MODEL": MODEL, "ORG_SLUG": "oss-pallets"}
PY = str(ROOT / "backend/.venv/bin/python")


def notify(msg: str) -> None:
    subprocess.run([str(ROOT / "ops/notify.sh"), msg], check=False, capture_output=True)
    print(msg, flush=True)


def psql(sql: str) -> str:
    return subprocess.run(["psql", ENV["DATABASE_URL"], "-Atc", sql], capture_output=True, text=True).stdout.strip()


def next_wake() -> datetime:
    now = datetime.now(timezone.utc)
    until = psql(f"select exhausted_until from quota_state where model='{MODEL}' and exhausted_until > now()")
    if until:
        return datetime.fromisoformat(until).astimezone(timezone.utc) + timedelta(minutes=5)
    used = int(psql(f"select coalesce(sum(items),0) from embed_usage where model='{MODEL}' and kind='index' "
                    "and day=(now() at time zone 'utc')::date") or 0)
    budget = int(ENV.get("EMBED_DAILY_BUDGET", "900"))
    if used < budget:
        return now
    return (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)


def main() -> int:
    last_cov = None
    while True:
        wake = next_wake()
        while datetime.now(timezone.utc) < wake:
            time.sleep(60)
        r = subprocess.run([PY, "-m", "app.retrieval.embed"], cwd=ROOT / "backend", env=ENV, capture_output=True, text=True)
        if r.returncode not in (0, 3):
            notify(f"Embedding pass FAILED (exit {r.returncode}); schedule stopped, no retry.\n{r.stderr[-400:]}")
            return 1
        res = json.loads(r.stdout.strip().splitlines()[-1])
        cov = res["coverage_text"]
        if cov != last_cov:
            notify(f"OSS embedding coverage ({MODEL}): {cov}\nthis pass: {res['embedded']} items, "
                   f"{res['pending']} pending, today {res['used_today_index']}/{ENV.get('EMBED_DAILY_BUDGET', '900')} "
                   f"index items. stopped: {res['stopped'] or 'complete'}")
            last_cov = cov
        if res["pending"] == 0 and not res["stopped"]:
            notify("OSS embeddings COMPLETE. B (real run) may start once prompts are frozen.")
            return 0


if __name__ == "__main__":
    sys.exit(main())
