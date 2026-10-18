#!/usr/bin/env python3
"""Telegram alert at every 5% of the GCP credit, from the budget's Pub/Sub messages.

Google publishes the budget's spend a few times a day; this pulls them, works out the percentage itself and
messages once per 5% step crossed. State lives in ~/.config/gitwhy/budget_state.json.
Usage: ops/budget_watch.py [--dry] [--loop SECONDS]
"""
import base64, json, subprocess, sys, time
from pathlib import Path

PROJECT = "gen-lang-client-0791700770"
SUB = "gitwhy-budget-pull"
STATE = Path.home() / ".config/gitwhy/budget_state.json"
NOTIFY = Path(__file__).with_name("notify.sh")
STEP = 5


def pull() -> list[dict]:
    r = subprocess.run(["gcloud", "pubsub", "subscriptions", "pull", SUB, "--project", PROJECT, "--limit", "50",
                        "--auto-ack", "--format=json"], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300])
    out = []
    for m in json.loads(r.stdout or "[]"):
        data = m["message"]["data"]
        out.append(json.loads(base64.b64decode(data)))
    return out


def check(dry: bool) -> None:
    state = json.loads(STATE.read_text()) if STATE.exists() else {"sent": 0, "period": ""}
    for m in pull():
        spent, cap = float(m.get("costAmount", 0)), float(m.get("budgetAmount", 0))
        period = m.get("costIntervalStart", "")
        if period != state["period"]:
            state = {"sent": 0, "period": period}
        if cap <= 0:
            continue
        pct = int(spent / cap * 100 // STEP * STEP)
        if pct > state["sent"] and pct >= STEP:
            text = f"GCP credit: {pct}% used (about {spent:,.0f} of {cap:,.0f} {m.get('currencyCode', '')})."
            if pct >= 100:
                text += " Stop paid resources now."
            print(text)
            if not dry:
                subprocess.run([str(NOTIFY), text], check=False)
            state["sent"] = pct
    STATE.parent.mkdir(parents=True, exist_ok=True)
    if not dry:
        STATE.write_text(json.dumps(state))


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    every = int(sys.argv[sys.argv.index("--loop") + 1]) if "--loop" in sys.argv else 0
    while True:
        try:
            check(dry)
        except Exception as e:  # keep looping; a single bad pull must not end the watcher
            print("budget_watch:", e, file=sys.stderr)
        if not every:
            break
        time.sleep(every)
