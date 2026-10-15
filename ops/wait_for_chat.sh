#!/usr/bin/env bash
# Poll until the owner messages the bot, then save chat id and send a confirmation message.
set -uo pipefail
source "$HOME/.config/lore/token.env"
for i in $(seq 1 360); do   # ~30 min
  CHAT_ID=$(curl -sS --max-time 15 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates" 2>/dev/null | python3 -I -c 'import sys,json
try:
    d=json.load(sys.stdin)
    r=[u for u in d.get("result",[]) if "message" in u]
    print(r[-1]["message"]["chat"]["id"] if r else "")
except Exception:
    print("")')
  if [ -n "$CHAT_ID" ]; then
    umask 077
    printf 'TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\n' "$TELEGRAM_BOT_TOKEN" "$CHAT_ID" > "$HOME/.config/lore/telegram.env"
    /root/lore-intelligence/ops/notify.sh "✅ LORE agent connected. Sample message OK. I'll ping you here for blockers, approvals, hourly GCP cost digests and usage-limit warnings." && echo "CONNECTED chat_id=$CHAT_ID"
    exit 0
  fi
  sleep 5
done
echo "TIMEOUT: no message received from owner"; exit 1
