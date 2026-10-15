#!/usr/bin/env bash
# One-time helper: after you send any message to your bot, run this with the token
# to print your chat id and write ~/.config/lore/telegram.env.
# Usage: ops/get_chat_id.sh <BOT_TOKEN>
set -euo pipefail
TOKEN="${1:?bot token required}"
RESP=$(curl -sS --max-time 15 "https://api.telegram.org/bot${TOKEN}/getUpdates")
CHAT_ID=$(python3 -I -c 'import sys,json
d=json.load(sys.stdin)
r=[u for u in d.get("result",[]) if "message" in u]
print(r[-1]["message"]["chat"]["id"] if r else "")' <<<"$RESP")
[ -n "$CHAT_ID" ] || { echo "No messages found. Send any message to your bot first, then rerun." >&2; exit 1; }
mkdir -p "$HOME/.config/lore"
umask 077
printf 'TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\n' "$TOKEN" "$CHAT_ID" > "$HOME/.config/lore/telegram.env"
echo "Saved. chat_id=$CHAT_ID"
