#!/bin/bash
# One-time, idempotent setup for infra/scripts/pg_backup.py (docs/runbooks/db-backup-restore.md):
#   - private bucket in me-central1: uniform bucket-level access, public access prevention,
#     objects deleted 14 days after upload
#   - uploader service account with no project role: objectCreator on that bucket only
#     (it cannot read, list, overwrite or delete)
#   - no key for it: the account whose credentials are already on the server may mint
#     short-lived tokens for it (tokenCreator on this one account, not project-wide)
# Run from Cloud Shell or the gcloud container as a project owner, in this directory.
set -euo pipefail
PROJECT=productintelligence-beeb3
BUCKET=productintelligence-beeb3-pg-backups
SA=pi-db-backup
SA_EMAIL=$SA@$PROJECT.iam.gserviceaccount.com
MINTER=${MINTER:-firebase-adminsdk-fbsvc@$PROJECT.iam.gserviceaccount.com}

if ! gcloud storage buckets describe "gs://$BUCKET" --project="$PROJECT" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$BUCKET" --project="$PROJECT" --location=me-central1 \
    --default-storage-class=STANDARD --uniform-bucket-level-access --public-access-prevention
fi
gcloud storage buckets update "gs://$BUCKET" --project="$PROJECT" \
  --uniform-bucket-level-access --public-access-prevention \
  --lifecycle-file=pg-backups-lifecycle.json

if ! gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SA" --project="$PROJECT" \
    --display-name="PostgreSQL backup uploader" \
    --description="Creates objects in gs://$BUCKET only; no keys (see pg_backup_setup.sh)"
fi
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --project="$PROJECT" \
  --member="serviceAccount:$SA_EMAIL" --role=roles/storage.objectCreator --quiet >/dev/null
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" --project="$PROJECT" \
  --member="serviceAccount:$MINTER" --role=roles/iam.serviceAccountTokenCreator --quiet >/dev/null
echo "ok: gs://$BUCKET, $SA_EMAIL (objectCreator), token minting by $MINTER"
