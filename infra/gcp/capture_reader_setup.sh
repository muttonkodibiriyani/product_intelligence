#!/bin/bash
# One-time, idempotent setup of a read-only reader for the capture outputs (Coordinator
# 01a11c92-591d; the capture lane loads Sephora and other captures from GCS):
#   - service account pi-capture-reader, no project role: roles/storage.objectViewer on exactly
#     gs://pi-sephora-e631eaba and gs://pi-capture-productintelligence-beeb3, nothing else, so
#     read-only is enforced by IAM (no write, delete or run.jobs.run)
# It creates NO key. A key is minted only on the owner's explicit OK, with the command this script
# prints, into a host path outside any repo. Run from Cloud Shell or the gcloud container as a
# project owner:
#   bash infra/gcp/capture_reader_setup.sh
set -euo pipefail
PROJECT=productintelligence-beeb3
READER=pi-capture-reader@$PROJECT.iam.gserviceaccount.com
BUCKETS=(pi-sephora-e631eaba pi-capture-productintelligence-beeb3)

if ! gcloud iam service-accounts describe "$READER" --project="$PROJECT" >/dev/null 2>&1; then
  gcloud iam service-accounts create pi-capture-reader --project="$PROJECT" \
    --display-name="Capture output reader" \
    --description="objectViewer on ${BUCKETS[*]} only; key only on the owner's OK (capture_reader_setup.sh)"
fi
for bucket in "${BUCKETS[@]}"; do
  gcloud storage buckets add-iam-policy-binding "gs://$bucket" --project="$PROJECT" \
    --member="serviceAccount:$READER" --role=roles/storage.objectViewer --quiet >/dev/null
done

roles=$(gcloud projects get-iam-policy "$PROJECT" --flatten='bindings[].members' \
  --filter="bindings.members:serviceAccount:$READER" --format='value(bindings.role)')
if [ -n "$roles" ]; then
  echo "STOP: $READER has project roles it must not have: $roles" >&2
  exit 1
fi
keys=$(gcloud iam service-accounts keys list --iam-account="$READER" --project="$PROJECT" \
  --managed-by=user --format='value(name)' | wc -l)
echo "ok: $READER objectViewer on gs://${BUCKETS[0]} and gs://${BUCKETS[1]}; no project role; user keys: $keys"
echo "Key, on the owner's explicit OK only (one key; mode 600; never in a repo or an image):"
echo "  install -d -m 700 ~/.config/pi-capture-reader && gcloud iam service-accounts keys create ~/.config/pi-capture-reader/key.json --iam-account=$READER --project=$PROJECT && chmod 600 ~/.config/pi-capture-reader/key.json"
echo "Revoke: gcloud iam service-accounts keys delete <KEY_ID> --iam-account=$READER --project=$PROJECT"
