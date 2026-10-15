#!/usr/bin/env bash
# Send a Telegram message to the owner.  Usage: ops/notify.sh "text"
# Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from ~/.config/lore/telegram.env (mode 600).
set -euo pipefail
ENV_FILE="${LORE_TELEGRAM_ENV:-$HOME/.config/lore/telegram.env}"
[ -f "$ENV_FILE" ] || { echo "notify: $ENV_FILE missing" >&2; exit 2; }
# shellcheck disable=SC1090
source "$ENV_FILE"
: "${TELEGRAM_BOT_TOKEN:?}" "${TELEGRAM_CHAT_ID:?}"
curl -sS --max-time 15 -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=${1:?message required}" >/dev/null
