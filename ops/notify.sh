#!/usr/bin/env bash
# Send a Telegram message to the owner.  Usage: ops/notify.sh "text"
# Reads TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (owner DM) and optional TELEGRAM_GROUP_CHAT_ID
# from ~/.config/gitwhy/telegram.env (mode 600). Sends to the paired group when set;
# NOTIFY_DM=1 forces the owner DM.
set -euo pipefail
ENV_FILE="${GITWHY_TELEGRAM_ENV:-$HOME/.config/gitwhy/telegram.env}"
[ -f "$ENV_FILE" ] || { echo "notify: $ENV_FILE missing" >&2; exit 2; }
# shellcheck disable=SC1090
source "$ENV_FILE"
: "${TELEGRAM_BOT_TOKEN:?}" "${TELEGRAM_CHAT_ID:?}"
TARGET="${TELEGRAM_GROUP_CHAT_ID:-$TELEGRAM_CHAT_ID}"
[ "${NOTIFY_DM:-0}" = 1 ] && TARGET="${TELEGRAM_CHAT_ID}"
curl -sS --max-time 15 -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${TARGET}" \
  --data-urlencode "text=${1:?message required}" >/dev/null
