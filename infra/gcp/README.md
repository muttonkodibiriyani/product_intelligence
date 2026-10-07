# GCP project state (productintelligence-beeb3)

Record of every change made to the live project outside a deploy workflow. Append; never rewrite.
Budget: $25/month. The billing account ID is kept out of this public repo; get it with
`gcloud billing projects describe productintelligence-beeb3`.

## Enabled APIs (beyond Firebase defaults)

| Date       | API                              | Why                                   | Cost |
|------------|----------------------------------|---------------------------------------|------|
| 2026-09-30 | `cloudbilling.googleapis.com`    | read project billing link             | free |
| 2026-09-30 | `billingbudgets.googleapis.com`  | list/create budget alert thresholds   | free |
| 2026-10-07 | `cloudscheduler.googleapis.com` | ADR-0009 Sephora variant pass (`sephora_schedule_setup.sh`) | free (1 job of the 3 free) |

## Budget alerts

Required: one budget of $25/month scoped to this project, alerting billing admins at 50%, 90%
and 100% of actual spend. The deploy service account has no billing-account role, so the owner
creates it (from Cloud Shell, as a billing account admin):

```sh
BILLING_ACCOUNT=$(gcloud billing projects describe productintelligence-beeb3 --format='value(billingAccountName.basename())')
gcloud billing budgets create --billing-account="$BILLING_ACCOUNT" \
  --display-name="pi-monthly-25usd" --budget-amount=25USD \
  --filter-projects=projects/productintelligence-beeb3 \
  --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0
```

Check first with `gcloud billing budgets list --billing-account="$BILLING_ACCOUNT"`; if a
budget already exists, add the missing thresholds with `gcloud billing budgets update` instead.

## Database backups

| Date       | Resource | Settings | Cost |
|------------|----------|----------|------|
| pending owner run | bucket `productintelligence-beeb3-pg-backups` | me-central1, uniform access, public access prevention, delete at 14 days | < $0.01/month |
| pending owner run | SA `pi-db-backup` (no key) | `roles/storage.objectCreator` on that bucket only; `firebase-adminsdk-fbsvc` has `roles/iam.serviceAccountTokenCreator` on this SA only | free |

The uploader cannot read or delete backups, but `firebase-adminsdk-fbsvc` (key on the server) can, through its project role; soft delete (7 days) is the backstop. See the runbook.

Created by `infra/gcp/pg_backup_setup.sh` (idempotent). Runbook: `docs/runbooks/db-backup-restore.md`.

## pi-api (service layer)

Created 2026-10-01 from `docs/runbooks/pi-api-deploy.md` at `19655dd` (decision log, 2026-10-01: S4 approval and 1Gi).

| Date       | Resource | Settings | Cost |
|------------|----------|----------|------|
| 2026-10-01 | datasets bucket `productintelligence-beeb3.firebasestorage.app` | **uniform bucket-level access enabled** (was off; object ACLs held only project-team entries and the uploader, nothing public). Revert window 90 days: `--no-uniform-bucket-level-access` | free |
| 2026-10-01 | Artifact Registry repo `pi-api` | Docker, me-central1, cleanup `infra/gcp/pi-api-ar-cleanup.json` (keep last 5, delete the rest; not dry run) | ~60 MB per image, inside the 0.5 GB free tier |
| 2026-10-01 | SA `pi-api` (no key, no project role) | custom role `piApiObjectReader` (`storage.objects.get` only) on the datasets bucket, condition `pi-api-datasets-only` = `datasets/` prefix | free |
| 2026-10-01 | Cloud Run service `pi-api` | me-central1; image by digest `sha256:086dbd859f5b185ce01bc2c84fb1541911c346d7c03f6cbce250c46db00ce1e2` (tag `19655dd7e123`); min 0 / max 3, concurrency 80, 1 vCPU, 1Gi, timeout 30 s, request-based CPU (startup CPU boost on: the gcloud default, startup-only, accepted by the coordinator 2026-10-01); `allUsers` invoker (in-app Firebase ID-token auth, fails closed); `PI_API_DATASETS=datasets/ae/beauty/latest.json` (v2 only) | ≈ $0–2/month at min 0 |
| 2026-10-01 | Hosting rewrite `/api/**` → `pi-api` (me-central1) | from `infra/firebase.json`, before the SPA catch-all | free |

The owner ran `gcloud run deploy` (revision `pi-api-00001-jpx`) and the Hosting deploy (main `42d3632`); the auto-mode classifier refuses production deploys from the Infra agent, so those go to the owner. Verified 2026-10-01 (runbook §8): `/api/v1/*` without or with a bad token → 401 `private, no-store` with a Bearer challenge; a signed-in viewer gets 200 on `/api/v1/meta` and a coverage CSV export whose line 1 is the `pi-api.export/v1` manifest; the `pi_api.export` audit log line is present (no row content); EN+AR dashboard smoke passes on WebKit, Firefox and Chromium; live Hosting files match `apps/web/deployed.sha256`. Tear-down order: runbook §9.

**Redeployed 2026-10-01** (owner-run, runbook §6 at `0278326`): revision `pi-api-00002-ffc` at 100%,
image by digest `sha256:708ce7d7f6081648176d2b45a43f583ca69c92eeb4aacb1d912de0dee9cae6c4` (tag
`2e374b1144be`, main after #72). Same settings as `pi-api-00001-jpx`, with `--cpu-boost` passed
explicitly and `PI_API_EVIDENCE_HOSTS=sephora_me=www.sephora.me` added. `ulta_ae` is left out: it
has no offers, so its evidence links stay null, and adding it later is a config change. §8
re-check passed: 401s, viewer meta and export, export audit line, the evidence url for
`s-P10000765-unknown-unknown` non-null on `https://www.sephora.me/`, and the EN+AR dashboard
smoke. Rollback target: `pi-api-00001-jpx`.

## Crawler run bucket

| Date       | Resource | Settings | Cost |
|------------|----------|----------|------|
| 2026-09-30 | bucket `pi-sephora-e631eaba` (created outside the repo) | me-central1, soft delete 7 days, lifecycle `{Delete, age: 1}` on every object | < $0.01/month |
| 2026-10-01 (applied 08:25Z, coordinator-approved) | lifecycle → `infra/gcp/pi-runs-lifecycle.json` | `dev-*`, `recon-*`, `ulta-test/` still delete at 1 day; everything else (run outputs: `snap-*`, `stock-*`, `price-*`, planner prefixes) at 14 days, matching pg-backups | < $0.01/month |

Why 14 days: a run must outlive a HELD load until it is cleared, and the ADR-0009 planner reads
previous runs. GCS has no "not prefix" condition, so the short-lived scratch prefixes are listed
explicitly and the 14-day rule is the catch-all: a new prefix is kept 14 days, not deleted after 1.
When objects match both rules, the 1-day rule deletes them first.

```sh
gcloud storage buckets describe gs://pi-sephora-e631eaba --format='json(lifecycle_config)'   # before
gcloud storage buckets update gs://pi-sephora-e631eaba --lifecycle-file=infra/gcp/pi-runs-lifecycle.json
gcloud storage buckets describe gs://pi-sephora-e631eaba --format='json(lifecycle_config)'   # after
```

Revert: `--lifecycle-file` with `{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 1}}]}`.

## Sephora schedule (ADR-0009)

Owner OK 2026-10-06 (~$4.5/month, decision log). Created by `infra/gcp/sephora_schedule_setup.sh`
(idempotent), from an `IMAGE` built from main and pinned by digest. The owner ran it on 2026-10-07
with `snapshot:150d6dbf7dee` (main 150d6dbf) `@sha256:64fca3a70e4651ad523d963c6bc2061a57b07cf9b61e9628637b9b8fe31ea23d`, built by Cloud Build
(build `1bbd6d01`, free tier). Enabled the same day; first run Monday 2026-10-12 18:00Z.

**Build from Cloud Shell with Cloud Build, not `docker push`.** On 2026-10-07 Cloud Shell's
`docker push` to `me-central1-docker.pkg.dev` failed with `connection refused` three times;
`gcloud builds submit --tag <image> --project productintelligence-beeb3` built and pushed the same
image (free tier: 120 build-minutes/day). Pin the digest it prints.

| Date | Resource | Settings | Cost |
|------|----------|----------|------|
| 2026-10-07 | job `pi-sephora-snapshot` (existing) | image `snapshot:150d6dbf7dee@sha256:64fca3a…` (above); `AUTO=1`, `PACE=2.0`, `TRPC=1`; one-off `PREFIX`/`CUTOFF`/`PLAN`/`LIMIT` removed; task timeout 8 h (was 7 h); no retries | the runs: ~$0.7 per weekly pass |
| 2026-10-07 | SA `pi-sephora-scheduler` (no key, no project role) | `roles/run.invoker` on `pi-sephora-snapshot` only | free |
| 2026-10-07 | Scheduler job `pi-sephora-variant-pass` (me-central1) | `0 18 * * 1,2` UTC: Monday and Tuesday 18:00Z, two consecutive nights; POSTs the job's `:run` as the SA above; no retries; created paused, **resumed 2026-10-07** (owner YES via coordinator), `describe` = `ENABLED` | free |

Go-live is a separate step, on the coordinator's GO: `gcloud scheduler jobs resume
pi-sephora-variant-pass --location=me-central1 --project=productintelligence-beeb3`. The first
`resume` right after the Scheduler API was enabled failed with an internal `NOT_FOUND` (`parent
resource not found … retryPolicies`); most likely API propagation; a retry worked. `pause`
stops everything (ADR-0009, Guards). A one-off manual run now has to override the job's `AUTO=1`:
`gcloud run jobs execute pi-sephora-snapshot --update-env-vars=AUTO=0,PREFIX=…,CUTOFF=…`.
