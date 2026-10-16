#!/usr/bin/env bash
# One Voyage embedding pass for the OSS corpus (no retries; a 429 stops it and is recorded). Run inside tmux.
set -uo pipefail
cd "$(dirname "$0")/../backend"
set -a; . ~/.config/lore/db.env; . ~/.config/lore/gemini.env; . ~/.config/lore/voyage.env; set +a
export PROVIDER=gemini EMBED_PROVIDER=voyage ORG_SLUG=oss-pallets \
  VOYAGE_REQUESTS_PER_MIN=3 VOYAGE_REQUEST_TOKENS=3000 VOYAGE_TOKENS_PER_MIN=9000   # free account without card: 3 RPM / ~10K TPM
LOG=${1:-/tmp/agent-0/-root-lore-intelligence/b5139bff-47bc-4e91-ab42-99c5942473ed/scratchpad/embed_voyage.log}
.venv/bin/python -m app.retrieval.embed >"$LOG" 2>"$LOG.err"; rc=$?
res=$(tail -n1 "$LOG")
../ops/notify.sh "Voyage embedding pass finished (exit $rc): $(echo "$res" | python3 -c 'import sys,json
try:
  d=json.loads(sys.stdin.read()); print(d["coverage_text"], "| embedded this pass", d["embedded"], "| pending", d["pending"], "| stopped:", d["stopped"] or "complete", "| tokens billed", d.get("voyage_tokens_billed"))
except Exception as e: print("see log", e)')"
