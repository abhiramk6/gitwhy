#!/usr/bin/env bash
# Pings the Telegram group if the agent has made no visible progress for a while
# (usage limit hit, waiting on the owner, or stuck). Run in its own tmux window.
# "Progress" = a new git commit or a change to ops/STATE.md.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(dirname "$HERE")"
STALE_MIN="${STALE_MIN:-90}"; INTERVAL="${INTERVAL:-300}"
warned=0
while true; do
  last=$(cd "$REPO" && git log -1 --format=%ct 2>/dev/null || echo 0)
  st=$(stat -c %Y "$REPO/ops/STATE.md" 2>/dev/null || echo 0)
  newest=$(( last > st ? last : st ))
  age=$(( ( $(date +%s) - newest ) / 60 ))
  if [ "$age" -ge "$STALE_MIN" ] && [ "$warned" = 0 ]; then
    "$HERE/notify.sh" "⏳ No progress for ${age} min (no commit / STATE change). Possible causes: usage limit, waiting on you, or stuck. Say 'status' here or check: tmux attach -t gitwhy" || true
    warned=1
  elif [ "$age" -lt "$STALE_MIN" ]; then
    warned=0
  fi
  sleep "$INTERVAL"
done
