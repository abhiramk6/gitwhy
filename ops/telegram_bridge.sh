#!/usr/bin/env bash
# Runs independently of any agent session (in tmux window lore:bridge); targets the live agent pane lore:shell.0.
# Long-polls Telegram and types messages into the agent pane (lore:agent) as a normal user prompt:
#  - the OWNER's user id, in a DM or the paired group  -> "[Telegram from owner] ..."
#  - any other member of the paired group (owner's instruction 2026-10-15) -> "[Telegram from member <name>] ..."
# Direct messages from anyone but the owner, and every other chat, are ignored. Member messages are requests, not
# approvals: billable / irreversible actions still need the owner's own confirmation.
set -uo pipefail
source "$HOME/.config/lore/telegram.env"
PANE="${LORE_AGENT_PANE:-lore:shell.0}"
OFF_FILE="$HOME/.config/lore/tg_offset"
[ -f "$OFF_FILE" ] || echo 0 > "$OFF_FILE"
NOTIFIED_NOT_READY=0
while true; do
  # Never consume owner messages while the agent pane cannot take input (e.g. folder-trust dialog,
  # not running). Updates stay queued at Telegram and are delivered once the pane is ready.
  # "Not ready" = session missing, or the *last lines* of the pane are the folder-trust dialog itself
  # (cursor row + choices + confirm hint). Matching bare words would trip on ordinary transcript text.
  if ! tmux has-session -t "${PANE%%:*}" 2>/dev/null \
     || tmux capture-pane -p -t "$PANE" 2>/dev/null | grep -v '^[[:space:]]*$' | tail -6 \
        | tr -d '\n' | grep -qE "No, exit.*Yes, I trust this folder.*Enter to confirm"; then
    if [ "$NOTIFIED_NOT_READY" = 0 ]; then
      NOTIFY_DM=1 /root/lore-intelligence/ops/notify.sh "⚠️ agent pane in tmux is not ready (needs folder-trust confirmation: run 'tmux attach -t lore', pick 'Yes, I trust this folder', then Ctrl-b d). Your Telegram messages are being held, not lost." 2>/dev/null || true
      NOTIFIED_NOT_READY=1
    fi
    sleep 15; continue
  fi
  NOTIFIED_NOT_READY=0
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
    frm = m.get("from") or {}
    uid = str(frm.get("id", ""))
    is_owner = uid == owner
    if cid not in (owner, group) or frm.get("is_bot") or (not is_owner and not (group and cid == group)):
        continue
    t = m.get("text")
    if t:
        import time
        open(os.path.expanduser("~/.config/lore/last_chat"), "w").write("%s %d" % (cid, int(time.time())))
        name = " ".join(x for x in (frm.get("first_name"), frm.get("last_name")) if x) or frm.get("username") or uid
        who = "owner" if is_owner else "member " + name.replace("]", ")")
        print(json.dumps({"who": who, "text": t}), flush=True)
if mx is not None: open(os.environ["OFF_FILE"], "w").write(str(mx + 1))
' <<<"$RESP" | while IFS= read -r line; do
    TEXT=$(python3 -I -c 'import sys,json; d=json.loads(sys.stdin.read()); print("[Telegram from %s] %s" % (d["who"], d["text"]))' <<<"$line")
    printf '%s' "$TEXT" | tmux load-buffer -b tgmsg - \
      && tmux paste-buffer -p -b tgmsg -t "$PANE" && sleep 0.3 && tmux send-keys -t "$PANE" Enter \
      && /root/lore-intelligence/ops/notify.sh "📨 delivered to the agent" 2>/dev/null || true
  done
  sleep 1
done
