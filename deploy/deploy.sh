#!/usr/bin/env bash
# Deploy to GCP. NOT RUN YET: needs gcloud auth, a project with billing on the free trial, and owner approval.
# Creates BILLABLE resources (Cloud SQL, Cloud Run). Defaults are the cheapest viable shapes.
# Usage: PROJECT_ID=... ./deploy/deploy.sh [plan|apply]    (default: plan = print commands only)
set -euo pipefail
MODE="${1:-plan}"
: "${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
SQL_INSTANCE="${SQL_INSTANCE:-lore-pg}"
SQL_TIER="${SQL_TIER:-db-f1-micro}"      # smallest shared-core; confirm pgvector support for the chosen version
DB_VERSION="${DB_VERSION:-POSTGRES_16}"
SERVICE="${SERVICE:-lore-app}"
JOB="${JOB:-lore-seed}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/lore/app:latest"
SA="lore-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
CONN="${PROJECT_ID}:${REGION}:${SQL_INSTANCE}"

run() { echo "+ $*"; [ "$MODE" = apply ] && "$@"; return 0; }

run gcloud config set project "$PROJECT_ID"
run gcloud services enable run.googleapis.com sqladmin.googleapis.com artifactregistry.googleapis.com \
    cloudbuild.googleapis.com secretmanager.googleapis.com aiplatform.googleapis.com cloudscheduler.googleapis.com
run gcloud artifacts repositories create lore --repository-format=docker --location="$REGION"
run gcloud iam service-accounts create lore-runtime --display-name="LORE runtime"
for role in roles/cloudsql.client roles/aiplatform.user roles/secretmanager.secretAccessor; do
  run gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${SA}" --role="$role"
done
run gcloud sql instances create "$SQL_INSTANCE" --database-version="$DB_VERSION" --tier="$SQL_TIER" \
    --region="$REGION" --storage-size=10 --storage-type=HDD --availability-type=zonal --no-backup
run gcloud sql databases create lore --instance="$SQL_INSTANCE"
echo "# create DB user + store DATABASE_URL and DEMO_TOKEN in Secret Manager (values are generated, never printed)"
run gcloud builds submit --config deploy/cloud-build/cloudbuild.yaml --substitutions=_REGION="$REGION" .
COMMON=(--image="$IMAGE" --region="$REGION" --service-account="$SA" --add-cloudsql-instances="$CONN"
        --set-env-vars="ENVIRONMENT=prod,PROVIDER=vertex,GCP_PROJECT=${PROJECT_ID},GCP_LOCATION=${REGION}"
        --set-secrets="DATABASE_URL=lore-database-url:latest,DEMO_TOKEN=lore-demo-token:latest")
run gcloud run jobs deploy "$JOB" "${COMMON[@]}" --command=python --args=-m,app.seed --max-retries=1
run gcloud run jobs execute "$JOB" --region="$REGION" --wait
run gcloud run deploy "$SERVICE" "${COMMON[@]}" --min-instances=0 --max-instances=2 --concurrency=20 \
    --memory=512Mi --allow-unauthenticated
