# GCP project state (productintelligence-beeb3)

Record of every change made to the live project outside a deploy workflow. Append; never rewrite.
Budget: $100/month (owner, 2026-10-07; was $25). The billing account ID is kept out of this public repo; get it with
`gcloud billing projects describe productintelligence-beeb3`.

## Enabled APIs (beyond Firebase defaults)

| Date       | API                              | Why                                   | Cost |
|------------|----------------------------------|---------------------------------------|------|
| 2026-09-30 | `cloudbilling.googleapis.com`    | read project billing link             | free |
| 2026-09-30 | `billingbudgets.googleapis.com`  | list/create budget alert thresholds   | free |
| 2026-10-07 | `cloudscheduler.googleapis.com` | ADR-0009 Sephora variant pass (`sephora_schedule_setup.sh`) | free (1 job of the 3 free) |

## Budget alerts

Required: one budget of $100/month (owner, 2026-10-07; was $25) scoped to this project,
alerting billing admins at 50%, 90% and 100% of actual spend ($50 / $90 / $100). New billable
resources are pre-approved while the projected total stays at or under $100/month; each one
still states its expected and maximum monthly cost in its PR. Anything that would take the
projected total over $100 goes back to the owner.

Created or updated by `infra/gcp/budget_setup.sh` (idempotent). It renames an existing
`pi-monthly-25usd` to `pi-monthly-100usd` and resets its amount and thresholds in place, without
touching its notification rule (emails and the kill-switch topic). The amount is in the billing
account's currency: 100USD, or 367.25AED at 3.6725 AED per USD. The assistant kill switch trips
at 90% of this budget, so it now trips at ~$90. The $5 budgets `pi-vertex-5usd` and
`pi-uae-collect-5usd` are separate.

The deploy service account has no billing-account role, and none is granted: nothing automated
reads costs or manages budgets yet, so `roles/billing.costsManager` for a service account waits
for a named consumer. The owner runs the script from Cloud Shell as a billing account admin,
pinned to the reviewed commit, and checks its sha256 against the one posted with the PR merge:

```sh
curl -fsSLo /tmp/budget_setup.sh https://raw.githubusercontent.com/muttonkodibiriyani/product_intelligence/<merge sha>/infra/gcp/budget_setup.sh && sha256sum /tmp/budget_setup.sh
bash /tmp/budget_setup.sh
```

| Date       | Resource | Settings | Cost |
|------------|----------|----------|------|
| pending owner run | budget `pi-monthly-100usd` (was `pi-monthly-25usd`) | $100/month, project filter, alerts at 50/90/100% | free |

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
| 2026-09-30 | bucket `pi-sephora-e631eaba` (created outside the repo) | me-central1, soft delete 7 days, lifecycle `{Delete, age: 1}` on every object (**superseded 2026-10-01**, next row: only `dev-`, `recon-`, `ulta-test/` delete at 1 day; everything else at 14) | < $0.01/month |
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

## UAE collection (task 01a11653-ac7a)

Coordinator-approved plan (~$5/month cap for Faces, Bloomingdale's and Ounass together). Created
by `infra/gcp/uae_collect_setup.sh` (idempotent) from an `IMAGE` built from main and pinned by
digest; owner steps, cron and budget in `tools/uae_collect/README.md`. Faces first.

| Date | Resource | Settings | Cost |
|------|----------|----------|------|
| pending owner run | SA `pi-uae-collect` (no key, no project role) | `roles/storage.objectUser` on `pi-capture-productintelligence-beeb3` under an IAM condition limited to `runs/`, `state/` and `feeds/`; runtime of the `pi-uae-collect-*` jobs | free |
| pending owner run | job `pi-uae-collect-faces` | `SHOP=faces_ae`; 1 vCPU / 1 GiB; task timeout 7 h; no retries; label `pi-collect=uae` | ≈ $0.9/month (≈ $0.08 per full or AR pass, ~10 a month; daily passes ≈ $0.003) |
| pending owner run | SA `pi-uae-scheduler` (no key, no project role) | `roles/run.invoker` on each `pi-uae-collect-*` job only | free |
| pending owner run | Scheduler job `pi-uae-collect-faces` (me-central1) | `0 20 * * *` UTC; the job picks daily / full (Mon, Thu) / ar (1st); no retries; **created paused** | free (2nd of the 3 free jobs) |
| pending owner run | SA `pi-feed-reader` (no key, no project role) | `roles/storage.objectViewer` on the capture bucket under IAM condition `feeds-only` (objects under `feeds/`, lists with prefix `feeds/`); `firebase-adminsdk-fbsvc` has `roles/iam.serviceAccountTokenCreator` on this SA only | free |
| pending owner run | budget `pi-uae-collect-5usd` | $5/month on label `pi-collect=uae`, alerts at 50/90/100% | free |

## Capture reader (Coordinator 01a11c92-591d)

A read-only identity for loading capture outputs on the host, so the Firebase Admin SDK key stays
with one holder. Created by `infra/gcp/capture_reader_setup.sh` (idempotent), which creates no key
and STOPs if the account has any project role. Applying it and minting its one key both need the
owner's explicit OK; the key goes to `~/.config/pi-capture-reader/key.json` (mode 600), never into
a repo or an image. `pi-sephora-e631eaba` runs `pi-runs-lifecycle.json`: `dev-`, `recon-` and `ulta-test/` delete at
1 day, every other prefix (run outputs such as `p0-20261008-sephora`) at 14 days, with 7 days of
soft delete after that. Read the live rules before relying on either (`gcloud storage buckets
describe gs://pi-sephora-e631eaba --format='value(lifecycle_config)'`). RAW is the one artefact
that cannot be re-fetched, so each output is also held under `sephora-hold/` in the capture
bucket (same region, no egress; that bucket has no lifecycle rule).

| Date | Resource | Settings | Cost |
|------|----------|----------|------|
| pending owner OK | SA `pi-capture-reader` (no project role) | `roles/storage.objectViewer` on `pi-sephora-e631eaba` and `pi-capture-productintelligence-beeb3` only; one user-managed key, minted on the owner's OK | free |
| 2026-10-08 | prefix `gs://pi-capture-productintelligence-beeb3/sephora-hold/<PREFIX>/` | in-GCS hold copy of each Sephora output (RAW included). `pi-sephora-e631eaba` deletes every object 14 days after it was written (lifecycle rule 2, no prefix); the held copy lives in `pi-capture-productintelligence-beeb3/sephora-hold/`, which has no lifecycle rule. Family: `p0-20261008-sephora`, `-ar`, `-ar2`, `-stock1` (4.32 GiB, 12,568 objects in 4 prefixes; CLARIFY, 2026-10-09), plus `p0-20261009-sephora-ar3` after the AR completion pass ends. One copy per prefix, same region: `gcloud storage cp -r gs://pi-sephora-e631eaba/<PREFIX> gs://pi-capture-productintelligence-beeb3/sephora-hold/`, run by CLARIFY under its own existing identity; `pi-capture-reader` stays objectViewer and copies nothing. Verified by `du -s` bytes and object count per prefix, source against destination, which must match exactly. Done by 2026-10-12, before the first source expiry at 2026-10-22T17:36Z; the source objects and their 14-day rule are left as they are (Coordinator 01a11c97-bac8, 01a11c9a-4b08, 01a11cad-a1a9, 01a11cb7-7aa5, 01a11e6f-95ab). Capture data is evidence: never deleted | ~0.11 USD/month plus ~0.06 USD one-off for the writes; **cap 2 USD/month** for the hold prefix: at the cap the owner is asked |
