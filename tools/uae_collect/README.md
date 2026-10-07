# uae_collect: recurring incremental UAE beauty collection

Task 01a11653-ac7a. One Cloud Run job per shop, started once a day by Cloud Scheduler. Each
execution reads the shop's sitemap, picks the product pages its pass needs, fetches them with
page_capture (plain httpx, robots-checked, paced, stop on first block), reads them with
capture_read's reader, builds the feed with `pi_capture.feed`, and advances the shop's state.
The host's cron (`infra/scripts/feed_load.py`) then loads new feeds into pi_db.

Shops: `faces_ae` (this PR). Bloomingdale's and Ounass come next, after their 10-03 counts
(task 01a11653-aab4) settle scope and cadence under the cap.

## Passes

The job picks its pass from the UTC date (`uae_collect/shops.py`); one daily Scheduler job per
shop, no per-run overrides.

| Pass | Faces | Reads | Fed |
|------|-------|-------|-----|
| `daily` | every other day | product URLs no run has read yet (new products, and pages an earlier run did not reach) | yes, `complete_catalogue: false` |
| `full`  | Monday, Thursday | every in-scope English product URL | yes; `complete_catalogue: true` only when every URL was read (`pi_capture.feed.completeness`) |
| `ar`    | the 1st | every in-scope Arabic product URL | no (the importer takes en-AE only); captured and read for later |

Faces' sitemap `<lastmod>` is touched in bulk (940 of the 1,458 products captured on 10-02 carry
2026-10-06), so it is not used as a change signal; the twice-weekly full pass carries price and
stock changes.

## Stops and gaps (ADR-0006)

Ordinary browser behaviour only: no impersonation, stealth, challenge solving or proxy (the job
never configures `PROXY_*`). The first block (challenge marker, 401/403, a second 429 in a row,
ten transport errors) stops the shop's host, and with it the run; nothing is retried. A sitemap
that cannot be read plans nothing. Then:

- the pages read before the stop are still read and fed; the feed is partial
- every page not read keeps its old state entry, so the next daily pass picks it up; nothing is
  ever marked removed or out of stock because a run did not see it
- `collect.json` says `blocked` (or `error`) with the reason, and the execution exits 2, so it
  shows as failed in Cloud Run

`MAX_ITEMS` (default 5000) caps one run's plan; a longer selection is cut and the run is partial.

## Outputs (capture bucket)

| Object | What |
|--------|------|
| `runs/<source>/<run id>/` | page_capture's plan, pages, raw bodies (sitemaps too), status; capture_read's `readings/`; `collect.json` (pass, outcome, counts, feed, `complete_catalogue`) |
| `feeds/<source>/<run id>/` | `<source>.feed.json`, `.mapping.json`, `.feed-report.json` (English passes with readings only) |
| `state/<source>/urls.json.gz` | per product URL: last read date, lastmod then, scope |

Run id: `<UTC start %Y-%m-%dT%H%M%SZ>-<pass>`.

## Cost (Faces)

Measured 2026-10-07: 1,480 English and 1,480 Arabic product URLs. At 1.5 s pace (+ jitter) a
full pass is about 50 min of 1 vCPU / 1 GiB.

| Item | Per run | Per month |
|------|---------|-----------|
| full EN pass (×~9) | ≈ $0.08 | ≈ $0.70 |
| AR pass (×1) | ≈ $0.08 | ≈ $0.08 |
| daily pass (×~20: sitemaps + new pages, ~2 min) | ≈ $0.003 | ≈ $0.06 |
| raw pages in the bucket (~150 MB per full run) | | < $0.05 at the bucket's run lifecycle |
| Cloud Scheduler | | free (2nd of the 3 free jobs) |
| **Faces total** | | **≈ $0.9** (before the Cloud Run free tier) |

Cap for the whole collection (Faces, Bloomingdale's, Ounass): ~$5/month. Bloomingdale's and
Ounass get their cadence from their own measurements (Ounass: no sitemap filter for beauty,
Crawl-delay 10; Bloomingdale's: measured from the region only). A 4th Scheduler job costs
$0.10/month.

## Owner setup (on the coordinator's GO)

1. Build from Cloud Shell with Cloud Build (`docker push` from Cloud Shell has failed before):

   ```sh
   git -C ~/product_intelligence fetch && git -C ~/product_intelligence checkout --detach origin/main
   cd ~/product_intelligence
   SHA=$(git rev-parse --short=12 HEAD)
   cat > /tmp/uae-collect.cloudbuild.yaml <<'YAML'
   steps:
   - name: gcr.io/cloud-builders/docker
     args: [build, -f, tools/uae_collect/Dockerfile, -t, $_IMAGE, .]
   images: [$_IMAGE]
   YAML
   gcloud builds submit . --project productintelligence-beeb3 \
     --config /tmp/uae-collect.cloudbuild.yaml \
     --substitutions _IMAGE=me-central1-docker.pkg.dev/productintelligence-beeb3/pi-capture/uae-collect:$SHA
   ```

   Pin the digest it prints.

2. Job, service accounts, Scheduler (created **PAUSED**), feed reader:

   ```sh
   IMAGE=me-central1-docker.pkg.dev/productintelligence-beeb3/pi-capture/uae-collect@sha256:<digest> \
     GIT_SHA=$SHA SHOP=faces_ae bash infra/gcp/uae_collect_setup.sh
   ```

3. Check the capture bucket's lifecycle keeps `state/` (it is rewritten every run, so an
   age-based rule only matters if it is shorter than a day) and deletes `runs/` in time:
   `gcloud storage buckets describe gs://pi-capture-productintelligence-beeb3 --format='json(lifecycle_config)'`.

4. Budget alert for the collection (billing admin):

   ```sh
   BILLING_ACCOUNT=$(gcloud billing projects describe productintelligence-beeb3 --format='value(billingAccountName.basename())')
   gcloud billing budgets create --billing-account="$BILLING_ACCOUNT" \
     --display-name="pi-uae-collect-5usd" --budget-amount=5USD \
     --filter-projects=projects/productintelligence-beeb3 --filter-labels=pi-collect=uae \
     --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0
   ```

5. One manual run before the schedule, to see a whole pass end to end:
   `gcloud run jobs execute pi-uae-collect-faces --region=me-central1 --project=productintelligence-beeb3 --update-env-vars=PASS=full`.
   (`--update-env-vars` applies to this execution only.)

6. Host cron for the load (as `tm8`, `crontab -e`), from a detached worktree of main that
   nothing else uses, like the backup cron. The owner writes the env file
   (`umask 077; printf 'PI_DATABASE_URL=%s\n' "…" > ~/.config/pi-feed-load/env`); nobody else
   reads it.

   ```sh
   git -C /home/tm8/projects/product_intelligence worktree add --detach /home/tm8/projects/pi-feed-load-cron origin/main
   mkdir -p ~/.config/pi-feed-load ~/.local/state/pi-feed-load
   ```

   ```cron
   30 3 * * * cd /home/tm8/projects/pi-feed-load-cron && set -a && . /home/tm8/.config/pi-feed-load/env && set +a && GOOGLE_APPLICATION_CREDENTIALS=/home/tm8/.config/firebase-sa/productintelligence-beeb3.json /usr/bin/flock -n /home/tm8/.local/state/pi-feed-load/lock /home/tm8/.local/bin/uv run --with 'google-auth>=2.30,<3' --with 'requests>=2.32,<3' python infra/scripts/feed_load.py load >> /home/tm8/.local/state/pi-feed-load/load.log 2>&1
   0 5 * * * cd /home/tm8/projects/pi-feed-load-cron && /home/tm8/.local/bin/uv run python infra/scripts/feed_load.py check >> /home/tm8/.local/state/pi-feed-load/check.log 2>&1
   ```

   03:30Z is after a full pass started at 20:00Z has finished (≤ 7 h).

7. Go-live, on the coordinator's GO only:
   `gcloud scheduler jobs resume pi-uae-collect-faces --location=me-central1 --project=productintelligence-beeb3`.
   `pause` stops everything.

## Local run and tests

```sh
BUCKET=file:/tmp/uae SHOP=faces_ae PASS=daily \
  PYTHONPATH=tools/uae_collect:tools/page_capture:tools/capture_read uv run python -m uae_collect.run
```

`tools/uae_collect/tests`: synthetic pages and sitemaps, stubbed HTTP client, local bucket;
nothing touches the network. `make check` covers ruff, mypy --strict and coverage.
