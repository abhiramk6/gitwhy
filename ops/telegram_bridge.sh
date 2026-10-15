#!/usr/bin/env bash
# Runs independently of any agent session (in tmux window lore:bridge).
# Long-polls Telegram; for each message sent by the OWNER's user id (DM or paired group) it types
# the text into the agent pane (lore:agent) as a normal user prompt. Everyone else is ignored.
set -uo pipefail
source "$HOME/.config/lore/telegram.env"
PANE="${LORE_AGENT_PANE:-lore:agent}"
OFF_FILE="$HOME/.config/lore/tg_offset"
[ -f "$OFF_FILE" ] || echo 0 > "$OFF_FILE"
while true; do
  OFF=$(cat "$OFF_FILE")
  RESP=$(curl -sS --max-time 40 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates?timeout=25&offset=${OFF}" 2>/dev/null || true)
  [ -z "$RESP" ] && { sleep 5; continue; }
  OWNER_ID="$TELEGRAM_CHAT_ID" GROUP_ID="${TELEGRAM_GROUP_CHAT_ID:-}" OFF_FILE="$OFF_FILE" python3 -I -c '
import sys, json, os
try: d = json.loads(sys.stdin.read())
except Exception: sys.exit(0)
owner = os.environ["OWNER_ID"]; group = os.environ.get("GROUP_ID", "")
mx = None
for u in d.get("result", []):
    mx = u["update_id"]
    m = u.get("message") or {}
    cid = str((m.get("chat") or {}).get("id", ""))
    if cid not in (owner, group) or str((m.get("from") or {}).get("id", "")) != owner:
        continue
    t = m.get("text")
    if t: print(json.dumps(t), flush=True)
if mx is not None: open(os.environ["OFF_FILE"], "w").write(str(mx + 1))
' <<<"$RESP" | while IFS= read -r line; do
    TEXT=$(python3 -I -c 'import sys,json; print(json.loads(sys.stdin.read()))' <<<"$line")
    printf '[Telegram from owner] %s' "$TEXT" | tmux load-buffer -b tgmsg - \
      && tmux paste-buffer -p -b tgmsg -t "$PANE" && sleep 0.3 && tmux send-keys -t "$PANE" Enter \
      && /root/lore-intelligence/ops/notify.sh "📨 delivered to the agent" 2>/dev/null || true
  done
  sleep 1
done
