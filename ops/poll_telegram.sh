#!/usr/bin/env bash
# Emit one line per new message from the owner (user id TELEGRAM_CHAT_ID) in the owner DM or in the
# paired group (TELEGRAM_GROUP_CHAT_ID, optional). Messages from any other sender are never emitted
# (group members may chat, but only the owner's user id can instruct/approve).
# Unknown chats are reported by id+title ONLY (no content) so the owner can confirm pairing from the DM.
set -uo pipefail
source "$HOME/.config/gitwhy/telegram.env"
OFF_FILE="$HOME/.config/gitwhy/tg_offset"
[ -f "$OFF_FILE" ] || echo 0 > "$OFF_FILE"
while true; do
  OFF=$(cat "$OFF_FILE")
  RESP=$(curl -sS --max-time 40 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates?timeout=25&offset=${OFF}" 2>/dev/null || true)
  [ -z "$RESP" ] && { sleep 5; continue; }
  OWNER_ID="$TELEGRAM_CHAT_ID" GROUP_ID="${TELEGRAM_GROUP_CHAT_ID:-}" OFF_FILE="$OFF_FILE" python3 -I -c '
import sys, json, os
try:
    d = json.loads(sys.stdin.read())
except Exception:
    sys.exit(0)
owner = os.environ["OWNER_ID"]; group = os.environ.get("GROUP_ID", "")
mx = None
for u in d.get("result", []):
    mx = u["update_id"]
    m = u.get("message") or {}
    mcm = u.get("my_chat_member") or {}
    chat = m.get("chat") or mcm.get("chat") or {}
    cid = str(chat.get("id", ""))
    if not cid:
        continue
    sender = str((m.get("from") or mcm.get("from") or {}).get("id", ""))
    allowed_chat = cid == owner or (group and cid == group)
    if allowed_chat and m:
        if sender == owner:
            t = m.get("text") or "[non-text message]"
            print("TELEGRAM_FROM_OWNER[chat=%s]: %s" % (cid, t.replace("\n", " \\n ")), flush=True)
        # non-owner senders in the paired group are intentionally ignored
    elif not allowed_chat:
        print("TELEGRAM_UNPAIRED_CHAT id=%s type=%s title=%s sender_is_owner=%s" %
              (cid, chat.get("type"), chat.get("title"), sender == owner), flush=True)
if mx is not None:
    open(os.environ["OFF_FILE"], "w").write(str(mx + 1))
' <<<"$RESP"
  sleep 2
done
