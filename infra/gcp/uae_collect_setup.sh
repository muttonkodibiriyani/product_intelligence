#!/bin/bash
# One-time, idempotent setup of the recurring UAE beauty collection for one shop (task
# 01a11653-ac7a; tools/uae_collect/README.md):
#   - runtime service account pi-uae-collect, no key, no project role: roles/storage.objectUser on
#     the capture bucket only (it writes runs/, state/ and feeds/ there)
#   - Cloud Run job pi-uae-collect-<shop> on IMAGE (built from main, pinned by digest): SHOP=<shop>,
#     1 vCPU / 1 GiB, 7 h task timeout (the run's own page cutoff is 6 h), no retries, label
#     pi-collect=uae for the budget filter
#   - invoker service account pi-uae-scheduler, no key, no project role: roles/run.invoker on the
#     job only
#   - Cloud Scheduler job pi-uae-collect-<shop>, daily at SCHEDULE UTC; the job picks the pass
#     from the date (daily / full / ar). It is CREATED PAUSED; resume it only on the coordinator's GO.
#   - feed reader pi-feed-reader, no key, no project role: roles/storage.objectViewer on the
#     capture bucket under an IAM condition limited to feeds/; the host account (MINTER) may mint
#     tokens for it (tokenCreator on this one account), for infra/scripts/feed_load.py on the host
# Re-running it changes nothing that is already right and never resumes or pauses an existing
# Scheduler job. Run from Cloud Shell or the gcloud container as a project owner:
#   IMAGE=me-central1-docker.pkg.dev/productintelligence-beeb3/pi-capture/uae-collect@sha256:<digest> \
#     SHOP=faces_ae bash infra/gcp/uae_collect_setup.sh
set -euo pipefail
PROJECT=productintelligence-beeb3
REGION=me-central1
BUCKET=pi-capture-productintelligence-beeb3
SHOP=${SHOP:-faces_ae}
SCHEDULE=${SCHEDULE:-"0 20 * * *"}
MINTER=${MINTER:-firebase-adminsdk-fbsvc@$PROJECT.iam.gserviceaccount.com}
RUNNER=pi-uae-collect@$PROJECT.iam.gserviceaccount.com
INVOKER=pi-uae-scheduler@$PROJECT.iam.gserviceaccount.com
READER=pi-feed-reader@$PROJECT.iam.gserviceaccount.com
case "$SHOP" in
  faces_ae) ;;
  *) echo "SHOP must be one of: faces_ae" >&2; exit 1 ;;
esac
JOB=pi-uae-collect-${SHOP%_ae}
SCHEDULER_JOB=$JOB
: "${IMAGE:?set IMAGE to the uae-collect image built from main, pinned by digest}"
case "$IMAGE" in
  *@sha256:*) ;;
  *) echo "IMAGE must be pinned by digest (…@sha256:…)" >&2; exit 1 ;;
esac
GIT_SHA=${GIT_SHA:-}

ensure_sa() {  # name, display name, description
  if ! gcloud iam service-accounts describe "$1@$PROJECT.iam.gserviceaccount.com" \
    --project="$PROJECT" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$1" --project="$PROJECT" --display-name="$2" \
      --description="$3"
  fi
}

ula=$(gcloud storage buckets describe "gs://$BUCKET" --project="$PROJECT" \
  --format='value(uniform_bucket_level_access)')
if [ "$ula" != "True" ]; then
  echo "gs://$BUCKET needs uniform bucket-level access for the conditional feed-reader binding" >&2
  exit 1
fi

ensure_sa pi-uae-collect "UAE collection runtime" \
  "Runs pi-uae-collect-* jobs; objectUser on gs://$BUCKET only; no keys (uae_collect_setup.sh)"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --project="$PROJECT" \
  --member="serviceAccount:$RUNNER" --role=roles/storage.objectUser --quiet >/dev/null

gcloud run jobs deploy "$JOB" --project="$PROJECT" --region="$REGION" --image="$IMAGE" \
  --service-account="$RUNNER" --cpu=1 --memory=1Gi --tasks=1 --task-timeout=7h --max-retries=0 \
  --labels=pi-collect=uae --set-env-vars="BUCKET=$BUCKET,SHOP=$SHOP,GIT_SHA=$GIT_SHA"

ensure_sa pi-uae-scheduler "UAE collection scheduler" \
  "Starts pi-uae-collect-* jobs only (run.invoker per job); no keys (uae_collect_setup.sh)"
gcloud run jobs add-iam-policy-binding "$JOB" --project="$PROJECT" --region="$REGION" \
  --member="serviceAccount:$INVOKER" --role=roles/run.invoker --quiet >/dev/null

target=(
  --schedule="$SCHEDULE" --time-zone=Etc/UTC
  --uri="https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/$JOB:run"
  --http-method=POST --oauth-service-account-email="$INVOKER"
  --oauth-token-scope=https://www.googleapis.com/auth/cloud-platform
  --max-retry-attempts=0
)
if gcloud scheduler jobs describe "$SCHEDULER_JOB" --project="$PROJECT" --location="$REGION" \
  >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$SCHEDULER_JOB" --project="$PROJECT" --location="$REGION" \
    "${target[@]}"
else
  gcloud scheduler jobs create http "$SCHEDULER_JOB" --project="$PROJECT" --location="$REGION" \
    --description="UAE collection: starts $JOB daily; the job picks the pass" "${target[@]}"
  gcloud scheduler jobs pause "$SCHEDULER_JOB" --project="$PROJECT" --location="$REGION"
fi

ensure_sa pi-feed-reader "UAE feed reader" \
  "Reads gs://$BUCKET/feeds/ only (IAM condition); no keys; tokens minted by the host"
condition=$(mktemp)
trap 'rm -f "$condition"' EXIT
cat >"$condition" <<JSON
{"title": "feeds-only", "description": "read and list feeds/ only",
 "expression": "resource.name.startsWith(\"projects/_/buckets/$BUCKET/objects/feeds/\") || api.getAttribute(\"storage.googleapis.com/objectListPrefix\", \"\").startsWith(\"feeds/\")"}
JSON
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --project="$PROJECT" \
  --member="serviceAccount:$READER" --role=roles/storage.objectViewer \
  --condition-from-file="$condition" --quiet >/dev/null
gcloud iam service-accounts add-iam-policy-binding "$READER" --project="$PROJECT" \
  --member="serviceAccount:$MINTER" --role=roles/iam.serviceAccountTokenCreator --quiet >/dev/null

state=$(gcloud scheduler jobs describe "$SCHEDULER_JOB" --project="$PROJECT" \
  --location="$REGION" --format='value(state)')
echo "ok: $JOB on $IMAGE (SHOP=$SHOP) as $RUNNER (objectUser gs://$BUCKET);"
echo "    $INVOKER run.invoker on $JOB; $SCHEDULER_JOB '$SCHEDULE' UTC, $state;"
echo "    $READER objectViewer on gs://$BUCKET/feeds/ only, tokens minted by $MINTER"
echo "Go-live, on the coordinator's GO only:"
echo "  gcloud scheduler jobs resume $SCHEDULER_JOB --location=$REGION --project=$PROJECT"
echo "Stop everything: gcloud scheduler jobs pause $SCHEDULER_JOB --location=$REGION --project=$PROJECT"
