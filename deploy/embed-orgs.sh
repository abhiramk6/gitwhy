#!/usr/bin/env bash
# Re-embed organizations with the cloud embedder (Vertex) by running the gitwhy-embed Cloud Run job once per org.
# Usage: PROJECT_ID=... [REGION=us-central1] deploy/embed-orgs.sh [org-slug ...]    (default: the demo organizations)
set -euo pipefail
: "${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
ORGS=("$@"); [ ${#ORGS[@]} -gt 0 ] || ORGS=(northwind oss-pallets records-lab-2)
for org in "${ORGS[@]}"; do
  echo "== embedding $org"
  gcloud run jobs execute gitwhy-embed --project "$PROJECT_ID" --region "$REGION" \
    --update-env-vars "ORG_SLUG=${org}" --wait 2>&1 | tail -3 | cut -c1-200
done
