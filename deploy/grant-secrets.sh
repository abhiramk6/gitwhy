#!/usr/bin/env bash
# Let the Cloud Run runtime service account read ONLY the application's secrets (not every secret in the project).
# Usage: PROJECT_ID=... deploy/grant-secrets.sh
set -euo pipefail
: "${PROJECT_ID:?set PROJECT_ID}"
NUM=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
SA="${RUNTIME_SA:-${NUM}-compute@developer.gserviceaccount.com}"
for s in gitwhy-database-url gitwhy-session-secret gitwhy-gemini-key gitwhy-gemini-key-backup gitwhy-demo-token; do
  gcloud secrets add-iam-policy-binding "$s" --project "$PROJECT_ID" \
    --member="serviceAccount:${SA}" --role=roles/secretmanager.secretAccessor --format='value(etag)' >/dev/null
  echo "granted read on $s to $SA"
done
