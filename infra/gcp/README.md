# GCP project state (productintelligence-beeb3)

Record of every change made to the live project outside a deploy workflow. Append; never rewrite.
Budget: $25/month. The billing account ID is kept out of this public repo; get it with
`gcloud billing projects describe productintelligence-beeb3`.

## Enabled APIs (beyond Firebase defaults)

| Date       | API                              | Why                                   | Cost |
|------------|----------------------------------|---------------------------------------|------|
| 2026-09-30 | `cloudbilling.googleapis.com`    | read project billing link             | free |
| 2026-09-30 | `billingbudgets.googleapis.com`  | list/create budget alert thresholds   | free |

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
| 2026-10-01 | Cloud Run service `pi-api` | me-central1; image by digest `sha256:086dbd859f5b…`; min 0 / max 3, concurrency 80, 1 vCPU, 1Gi, timeout 30 s, request-based CPU (startup CPU boost on: the gcloud default, startup-only, accepted by the coordinator 2026-10-01); `allUsers` invoker (in-app Firebase ID-token auth, fails closed); `PI_API_DATASETS=datasets/ae/beauty/latest.json` (v2 only) | ≈ $0–2/month at min 0 |
| 2026-10-01 | Hosting rewrite `/api/**` → `pi-api` (me-central1) | from `infra/firebase.json`, before the SPA catch-all | free |

The owner ran `gcloud run deploy` (revision `pi-api-00001-jpx`) and the Hosting deploy (main `42d3632`); the auto-mode classifier refuses production deploys from the Infra agent, so those go to the owner. Verified 2026-10-01 (runbook §8): `/api/v1/*` without or with a bad token → 401 `private, no-store` with a Bearer challenge; a signed-in viewer gets 200 on `/api/v1/meta` and a coverage CSV export whose line 1 is the `pi-api.export/v1` manifest; the `pi_api.export` audit log line is present (no row content); EN+AR dashboard smoke passes on WebKit, Firefox and Chromium; live Hosting files match `apps/web/deployed.sha256`. Tear-down order: runbook §9.
