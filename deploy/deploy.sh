#!/usr/bin/env bash
# Build the image and deploy the app to Cloud Run (Cloud SQL Postgres + pgvector, Vertex embeddings, free-tier Gemini keys).
# One-time infrastructure is described in docs/operations.md; this script is the repeatable part.
# Usage: PROJECT_ID=... [REGION=us-central1] [TAG=$(git rev-parse --short HEAD)] deploy/deploy.sh [plan|apply]
set -euo pipefail
MODE="${1:-plan}"
: "${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
SQL_INSTANCE="${SQL_INSTANCE:-gitwhy-pg}"
SERVICE="${SERVICE:-gitwhy-app}"
TAG="${TAG:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/gitwhy/app:${TAG}"
CONN="${PROJECT_ID}:${REGION}:${SQL_INSTANCE}"
BUCKET="${PROJECT_ID}-gitwhy-secrets"      # private bucket mounted as the per-organization token folder

run() { echo "+ $*"; [ "$MODE" = apply ] && "$@"; return 0; }

cd "$(dirname "$0")/.."     # the repository root, wherever the script is started from
[ -n "${SKIP_BUILD:-}" ] || run gcloud builds submit . --project "$PROJECT_ID" --tag "$IMAGE"
run gcloud run deploy "$SERVICE" --quiet --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE" \
  --allow-unauthenticated --port 8080 --memory 1Gi --cpu 1 --timeout 300 --concurrency 40 \
  --min-instances 1 --max-instances 3 --no-cpu-throttling \
  --add-cloudsql-instances "$CONN" \
  --add-volume "name=secrets,type=cloud-storage,bucket=${BUCKET}" --add-volume-mount "volume=secrets,mount-path=/secrets" \
  --set-env-vars "ENVIRONMENT=production,AUTH_REQUIRED=1,PROVIDER=gemini,EMBED_PROVIDER=vertex,SYNC_EMBED=1,ORG_SLUG=northwind,GCP_PROJECT=${PROJECT_ID},GCP_LOCATION=${REGION},SECRETS_DIR=/secrets" \
  --set-secrets "DATABASE_URL=gitwhy-database-url:latest,GITWHY_SESSION_SECRET=gitwhy-session-secret:latest,GEMINI_API_KEY=gitwhy-gemini-key:latest,GEMINI_API_KEY_BACKUP=gitwhy-gemini-key-backup:latest,DEMO_TOKEN=gitwhy-demo-token:latest"
echo "service url:"; run gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format "value(status.url)"
