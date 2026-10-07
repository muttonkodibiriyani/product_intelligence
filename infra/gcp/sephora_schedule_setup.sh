#!/bin/bash
# One-time, idempotent setup of the ADR-0009 Sephora UAE variant pass (owner OK 2026-10-06,
# ~$4.5/month; decision log 2026-10-06):
#   - the existing job pi-sephora-snapshot runs IMAGE (built from main, so it has AUTO mode, #147)
#     with AUTO=1 and PACE=2.0, an 8 h task timeout (18:00Z start to the 01:55Z cutoff is 7 h 55 min;
#     the stored 7 h SIGTERMed run r4w9l at 01:00Z) and no retries. The one-off PREFIX, CUTOFF, PLAN
#     and LIMIT left from the last manual run are removed: an AUTO run given any of them is refused.
#   - invoker service account with no key and no project role: roles/run.invoker on this job only
#   - Cloud Scheduler job, Monday and Tuesday 18:00Z: the weekly pass over two consecutive nights
#     (the second night plans from the first night's covered.json.gz). It is CREATED PAUSED; resume
#     it only on the coordinator's GO (tools/sephora_snapshot/README.md, Schedule).
# Re-running it changes nothing that is already right and never resumes or pauses an existing
# Scheduler job. Run from Cloud Shell or the gcloud container as a project owner:
#   IMAGE=me-central1-docker.pkg.dev/productintelligence-beeb3/pi-sephora/snapshot@sha256:<digest> \
#     bash infra/gcp/sephora_schedule_setup.sh
set -euo pipefail
PROJECT=productintelligence-beeb3
REGION=me-central1
JOB=pi-sephora-snapshot
SA=pi-sephora-scheduler
SA_EMAIL=$SA@$PROJECT.iam.gserviceaccount.com
SCHEDULER_JOB=pi-sephora-variant-pass
SCHEDULE="0 18 * * 1,2"
: "${IMAGE:?set IMAGE to the snapshot image built from main, pinned by digest}"
case "$IMAGE" in
  *@sha256:*) ;;
  *) echo "IMAGE must be pinned by digest (…@sha256:…)" >&2; exit 1 ;;
esac

gcloud services enable cloudscheduler.googleapis.com --project="$PROJECT"

gcloud run jobs update "$JOB" --project="$PROJECT" --region="$REGION" --image="$IMAGE" \
  --task-timeout=8h --max-retries=0 \
  --remove-env-vars=PREFIX,CUTOFF,PLAN,LIMIT \
  --update-env-vars=AUTO=1,PACE=2.0,TRPC=1

if ! gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SA" --project="$PROJECT" \
    --display-name="Sephora snapshot scheduler" \
    --description="Starts $JOB only (run.invoker on that job); no keys (see sephora_schedule_setup.sh)"
fi
gcloud run jobs add-iam-policy-binding "$JOB" --project="$PROJECT" --region="$REGION" \
  --member="serviceAccount:$SA_EMAIL" --role=roles/run.invoker --quiet >/dev/null

target=(
  --schedule="$SCHEDULE" --time-zone=Etc/UTC
  --uri="https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/$JOB:run"
  --http-method=POST --oauth-service-account-email="$SA_EMAIL"
  --oauth-token-scope=https://www.googleapis.com/auth/cloud-platform
  --max-retry-attempts=0
)
if gcloud scheduler jobs describe "$SCHEDULER_JOB" --project="$PROJECT" --location="$REGION" \
  >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$SCHEDULER_JOB" --project="$PROJECT" --location="$REGION" \
    "${target[@]}"
else
  gcloud scheduler jobs create http "$SCHEDULER_JOB" --project="$PROJECT" --location="$REGION" \
    --description="ADR-0009 variant pass: starts $JOB (AUTO=1) Mon+Tue 18:00Z" "${target[@]}"
  gcloud scheduler jobs pause "$SCHEDULER_JOB" --project="$PROJECT" --location="$REGION"
fi
state=$(gcloud scheduler jobs describe "$SCHEDULER_JOB" --project="$PROJECT" \
  --location="$REGION" --format='value(state)')
echo "ok: $JOB on $IMAGE (AUTO=1, 8h); $SA_EMAIL run.invoker on $JOB; $SCHEDULER_JOB '$SCHEDULE' UTC, $state"
