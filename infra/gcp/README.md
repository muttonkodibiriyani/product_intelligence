# GCP project state (productintelligence-beeb3)

Record of every change made to the live project outside a deploy workflow. Append; never rewrite.
Billing account: `01B406-EF5690-CCF2FD`. Budget: $25/month.

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
gcloud billing budgets create --billing-account=01B406-EF5690-CCF2FD \
  --display-name="pi-monthly-25usd" --budget-amount=25USD \
  --filter-projects=projects/productintelligence-beeb3 \
  --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0
```

Check first with `gcloud billing budgets list --billing-account=01B406-EF5690-CCF2FD`; if a
budget already exists, add the missing thresholds with `gcloud billing budgets update` instead.
