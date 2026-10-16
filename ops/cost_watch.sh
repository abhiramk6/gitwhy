#!/usr/bin/env bash
# Hourly GCP cost/health digest -> Telegram, with a hard guard at 80% of the free-trial credit.
#
# IMPORTANT: gcloud cannot read remaining free-trial credit directly. This script ESTIMATES spend from the
# resources that exist (Cloud SQL uptime x tier price, + a small allowance for Cloud Run/Vertex/Build) and
# says so in every message. The authoritative number is Billing > Credits in the console.
#
# Usage: PROJECT_ID=... ops/cost_watch.sh [--dry-run]     (run hourly under cron/tmux)
# Env: CREDIT_USD=300  STOP_AT_PCT=80  SQL_INSTANCE=gitwhy-pg  SQL_HOURLY_USD=0.0150 (db-f1-micro, confirm in pricing)
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
: "${PROJECT_ID:?set PROJECT_ID}"
CREDIT_USD="${CREDIT_USD:-300}"; STOP_AT_PCT="${STOP_AT_PCT:-80}"
SQL_INSTANCE="${SQL_INSTANCE:-gitwhy-pg}"; SQL_HOURLY_USD="${SQL_HOURLY_USD:-0.0150}"
STATE="${HOME}/.config/gitwhy/cost_state"; mkdir -p "$(dirname "$STATE")"
DRY="${1:-}"
say() { if [ "$DRY" = --dry-run ]; then echo "$1"; else "$HERE/notify.sh" "$1"; fi; }

command -v gcloud >/dev/null || { say "cost_watch: gcloud missing"; exit 2; }
if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | grep -q .; then
  say "cost_watch: gcloud not authenticated; cannot read project ${PROJECT_ID}"; exit 2
fi

sql_json=$(gcloud sql instances describe "$SQL_INSTANCE" --project "$PROJECT_ID" --format=json 2>/dev/null || echo '{}')
sql_state=$(echo "$sql_json" | python3 -I -c 'import sys,json; print(json.load(sys.stdin).get("state","ABSENT"))')
runs=$(gcloud run services list --project "$PROJECT_ID" --format='value(metadata.name)' 2>/dev/null | wc -l)

# accumulate estimated hours while the instance is RUNNABLE (ticks once per invocation, assumes hourly runs)
hours=$(cat "$STATE" 2>/dev/null || echo 0)
[ "$sql_state" = RUNNABLE ] && hours=$((hours + 1))
echo "$hours" > "$STATE"
est=$(python3 -I -c "print(round($hours*$SQL_HOURLY_USD + 0.5,2))")   # +0.5 flat allowance for other services
pct=$(python3 -I -c "print(round($est/$CREDIT_USD*100,1))")

msg="GCP digest ($(date -u +%H:%M) UTC) project=${PROJECT_ID}
Cloud SQL ${SQL_INSTANCE}: ${sql_state} · Cloud Run services: ${runs}
Estimated spend: \$${est} of \$${CREDIT_USD} (${pct}%) — ESTIMATE; check console Billing > Credits."
if python3 -I -c "import sys; sys.exit(0 if $pct >= $STOP_AT_PCT else 1)"; then
  msg="$msg
⚠️ ${STOP_AT_PCT}% guard reached: stopping Cloud SQL."
  if [ "$DRY" != --dry-run ] && [ "$sql_state" = RUNNABLE ]; then
    gcloud sql instances patch "$SQL_INSTANCE" --project "$PROJECT_ID" --activation-policy=NEVER --quiet >/dev/null 2>&1 \
      && msg="$msg (done)" || msg="$msg (FAILED - stop it manually!)"
  fi
fi
say "$msg"
