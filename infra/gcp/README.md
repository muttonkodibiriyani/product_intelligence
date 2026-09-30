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
