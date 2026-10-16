#!/usr/bin/env bash
# Rebuild the knowledge graph for one org (model judgments are cached, so unchanged payloads replay for free).
# Usage: ops/rebuild_graph.sh <org-slug>.  One pass; on a model quota error the judgment is skipped and reported, never retried in a loop.
set -uo pipefail
cd "$(dirname "$0")/../backend"
set -a; . ~/.config/gitwhy/db.env; . ~/.config/gitwhy/gemini.env; . ~/.config/gitwhy/voyage.env; set +a
export PROVIDER=gemini EMBED_PROVIDER=voyage ORG_SLUG="${1:?org slug}"
mkdir -p ~/.local/state/gitwhy; LOG=~/.local/state/gitwhy/graph_$ORG_SLUG.log
.venv/bin/python - >"$LOG" 2>&1 <<'PY'
import json
from app.config import get_settings
from app.db import connect
from app.knowledge.build_graph import build
from app.models.provider import make_provider
from app.intelligence.judge import meter
s = get_settings(); prov = make_provider(s)
with connect() as c:
    org = c.execute("select id from organizations where slug=%s", (s.org_slug,)).fetchone()["id"]
    g = build(c, org, prov)
print(json.dumps({"graph": g.__dict__, "meter": {k: v for k, v in meter.__dict__.items() if k in ("live", "replayed", "unavailable", "replay_models")},
                  "model": getattr(prov, "last_model", None)}, default=str))
PY
rc=$?; ../ops/notify.sh "Graph rebuild for $ORG_SLUG finished (exit $rc): $(tail -n1 "$LOG" | cut -c1-600)"
