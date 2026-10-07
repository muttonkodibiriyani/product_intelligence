#!/bin/bash
# Idempotent setup of the project's monthly budget: $100/month (owner, 2026-10-07; raised from
# $25), scoped to this project, emailing billing admins at 50%, 90% and 100% of actual spend.
#   - An existing pi-monthly-25usd or pi-monthly-100usd budget is updated in place: renamed to
#     pi-monthly-100usd, amount and thresholds reset. Its notification rule (the email recipients
#     and the pi-budget-alerts Pub/Sub topic of docs/runbooks/assistant-enablement.md) is not
#     touched. Otherwise the budget is created.
#   - The amount is in the billing account's currency: 100USD, or 367.25AED at the fixed peg of
#     3.6725 AED per USD. Any other currency stops the script.
#   - The assistant kill switch trips at 90% of this budget, so it now trips at ~$90, not $22.50.
#   - The $5 budgets (pi-vertex-5usd, pi-uae-collect-5usd) are separate and not touched.
# Re-running it changes nothing that is already right. Run from Cloud Shell as a billing account
# admin, or as a principal with roles/billing.costsManager on the billing account:
#   bash infra/gcp/budget_setup.sh
set -euo pipefail
PROJECT=productintelligence-beeb3
NAME=pi-monthly-100usd
OLD_NAME=pi-monthly-25usd

BILLING_ACCOUNT=$(gcloud billing projects describe "$PROJECT" \
  --format='value(billingAccountName.basename())')
: "${BILLING_ACCOUNT:?project $PROJECT has no billing account}"
CURRENCY=$(gcloud billing accounts describe "$BILLING_ACCOUNT" --format='value(currencyCode)')
case "$CURRENCY" in
  USD) AMOUNT=100USD ;;
  AED) AMOUNT=367.25AED ;;
  *) echo "billing currency '$CURRENCY' is neither USD nor AED; set the amount by hand" >&2; exit 1 ;;
esac

thresholds=(--threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0)
found=$(gcloud billing budgets list --billing-account="$BILLING_ACCOUNT" \
  --filter="displayName=($NAME,$OLD_NAME)" --format='value(name)')
if [ "$(printf '%s\n' "$found" | grep -c .)" -gt 1 ]; then
  echo "more than one of $NAME / $OLD_NAME exists; delete the extra one first:" >&2
  printf '%s\n' "$found" >&2
  exit 1
elif [ -n "$found" ]; then
  gcloud billing budgets update "$found" --billing-account="$BILLING_ACCOUNT" \
    --display-name="$NAME" --budget-amount="$AMOUNT" \
    --clear-threshold-rules "${thresholds[@]/--threshold-rule/--add-threshold-rule}" >/dev/null
else
  gcloud billing budgets create --billing-account="$BILLING_ACCOUNT" \
    --display-name="$NAME" --budget-amount="$AMOUNT" \
    --filter-projects="projects/$PROJECT" "${thresholds[@]}" >/dev/null
fi

gcloud billing budgets list --billing-account="$BILLING_ACCOUNT" \
  --filter="displayName=$NAME" \
  --format='table(displayName,amount.specifiedAmount,thresholdRules[].thresholdPercent.list(),notificationsRule.pubsubTopic)'
echo "budget_setup: OK"
