#!/usr/bin/env bash
# Emit one line per new message from the paired owner chat. Ignores every other chat.
# Offset persisted in ~/.config/lore/tg_offset so messages are never emitted twice.
set -uo pipefail
source "$HOME/.config/lore/telegram.env"
OFF_FILE="$HOME/.config/lore/tg_offset"
[ -f "$OFF_FILE" ] || echo 0 > "$OFF_FILE"
while true; do
  OFF=$(cat "$OFF_FILE")
  RESP=$(curl -sS --max-time 40 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates?timeout=25&offset=${OFF}" 2>/dev/null || true)
  [ -z "$RESP" ] && { sleep 5; continue; }
  TELEGRAM_CHAT_ID="$TELEGRAM_CHAT_ID" OFF_FILE="$OFF_FILE" python3 -I -c '
import sys, json, os
try:
    d = json.loads(sys.stdin.read())
except Exception:
    sys.exit(0)
owner = str(os.environ["TELEGRAM_CHAT_ID"])
mx = None
for u in d.get("result", []):
    mx = u["update_id"]
    m = u.get("message") or {}
    if str(m.get("chat", {}).get("id")) != owner:
        continue
    t = m.get("text") or "[non-text message]"
    print("TELEGRAM_FROM_OWNER: " + t.replace("\n", " \\n "), flush=True)
if mx is not None:
    open(os.environ["OFF_FILE"], "w").write(str(mx + 1))
' <<<"$RESP"
  sleep 2
done
