# Runbook: ulta.ae ~20-page proxy test (run by the owner in Google Cloud Shell)

This fetches about 20 public ulta.ae product pages (English), one every 5-10 seconds, through the
IPRoyal UAE residential proxy the owner approved (ADR-0006 Amendment 2). It fetches only: nothing
is written to the database. It obeys robots.txt on every request, blocks heavy assets, and stops
by itself at the first challenge, 401/403, proxy error, second 429 in a row, or the byte cap.

**You need:** Google Cloud Shell opened on project `productintelligence-beeb3`. You don't need a
key file or a password: the job borrows your own Cloud Shell login (a token that expires within
an hour) only to read the proxy login from Secret Manager. Neither the token nor the proxy login
is ever printed or saved to the result files.

**Time:** first build about 3-5 minutes, then the run about 5-8 minutes.
**Expected cost:** well under 0.1 GB, about $0.50 at most at $6.25/GB. The job stops before the
1.8 GB allowance could be crossed.

## Copy-paste block

Before you paste, fill in `COMMIT` (EDIT 1) and check `PRIOR_GB` (EDIT 2). If `COMMIT` is not
filled in, the block stops without doing anything. The token is set only inside the block and is
gone when it ends.

```bash
# ==== EDIT 1: the commit to run (the coordinator sends you this) ====
COMMIT=PASTE_COMMIT_HERE
# ==== EDIT 2: GB already used, from the IPRoyal dashboard, ROUNDED UP ====
# Pre-filled: the dashboard showed 0.01321 MB used (two ipinfo.io checks) = 0.00002 GB rounded up.
# Only change this if the dashboard now shows more.
PRIOR_GB=0.00002
# ==== nothing below needs editing; it stops at the first failed step ====
(
set -e
test "$COMMIT" != PASTE_COMMIT_HERE || { echo "EDIT 1 first: set COMMIT"; exit 1; }
cd ~ && rm -rf pi-ulta-test && git clone -q https://github.com/muttonkodibiriyani/product_intelligence.git pi-ulta-test
cd ~/pi-ulta-test && git checkout -q "$COMMIT" && git log --oneline -1
docker build -q -f tools/ulta_snapshot/Dockerfile -t pi-ulta-fetch .
TS=$(date -u +%Y%m%dT%H%M%SZ); OUT=~/ulta-test-$TS; mkdir -p "$OUT"; echo "files go to $OUT"
TOKEN="$(gcloud auth print-access-token)"; export GOOGLE_OAUTH_ACCESS_TOKEN="$TOKEN"
docker run --rm -i --name ulta-test --user "$(id -u):$(id -g)" \
  -v "$OUT":/out \
  -e GOOGLE_OAUTH_ACCESS_TOKEN \
  -e PRIOR_GB="$PRIOR_GB" -e MAX_PAGES=20 -e CAPTURE_JSON=0 \
  -e OWNER_APPROVAL_REF="ADR-0006 Amendment 2 (owner decision 2026-09-30: IPRoyal AE, ulta.ae only)" \
  -e SECRET_RESOURCE=projects/productintelligence-beeb3/secrets/pi-proxy-iproyal-ae/versions/4 \
  pi-ulta-fetch 2>&1 | tee "$OUT/console.log"
gsutil -m -q cp -r "$OUT" "gs://pi-sephora-e631eaba/ulta-test/$TS/"
echo "UPLOADED gs://pi-sephora-e631eaba/ulta-test/$TS/"
)
```

The run prints one line per page while it works, so you watch it live in the same window, e.g.:

```
ulta.ae proxy test: 20 pages, prior_bytes=20000, out=/out
page 1: http 200, 1234567 bytes: https://www.ulta.ae/en/buy-...
page 2: http 200, 987654 bytes: https://www.ulta.ae/en/buy-...
```

## What the last line means

The run always ends with one line that starts with `ULTA TEST RESULT:`. **Paste that line into
the owner chat.** If the block stopped before the run began (for example `gcloud` could not
get a token, or the build failed), there is no such line: paste the last few lines instead. The
`status=` value tells you how it went:

| `status=` | Meaning | What to do |
|---|---|---|
| `complete` | All pages were tried with no challenge. Example: `ULTA TEST RESULT: status=complete pages_ok=20/20 robots_refused=0 proxy_bytes=31000000 gb=0.031000 usd=0.19 challenge=no ...` | Success. Paste the line. |
| `stopped_at_challenge` | The site showed a bot challenge or a 401/403. The job stopped at once, with no retry, and `challenge=yes`. | Paste the line. Do not re-run. |
| `cap_reached` | Another page could have crossed the 1.8 GB allowance, so the job stopped before sending it. | Paste the line. Do not re-run. |
| `stopped_by_operator` | You stopped it (see below). | Paste the line. |
| `stopped_error` | A proxy or login error, e.g. the secret could not be read. `detail=` says which. | Paste the line. If `proxy_bytes=0` **and** `challenge=no`, nothing reached ulta.ae (for example `secret version not accessible`): it is safe to re-run once the config is fixed. If `proxy_bytes` is above 0 or `challenge=yes`, do **not** re-run. |

In the summary line and in the per-page lines:
- `robots_refused=N` counts pages that robots.txt disallowed. They were skipped, never sent, and
  cost 0 bytes, and the run carries on. A page skipped this way prints
  `refused by robots (not fetched, 0 bytes): <url>`.
- A cap stop shows `status=cap_reached` and `detail=` contains `proxy_byte_cap` or
  `ProxyBudgetExceededError`.

## Where the files are

- They land in `~/ulta-test-<UTC time>/` in Cloud Shell:
  - `progress.json` (status, updated after every page);
  - `manifest.json` (the final bytes, GB and $);
  - `audit.jsonl` (bytes per page and robots aborts);
  - `console.log`, `robots.txt`, and the pages in `pdp/` and `evidence/`.
- The last command uploads the whole folder to `gs://pi-sephora-e631eaba/ulta-test/<UTC time>/`
  and prints `UPLOADED ...`. The team copies it from there within a day, because that bucket
  deletes files after 1 day.

## Proxy secret version

The blocks pin `SECRET_RESOURCE` to one secret version (`.../versions/4`, the current
credential; `latest` is also accepted but not used). The job
reads exactly the credential named there and never lists or picks versions itself, so the
credential in use is auditable. **When the IPRoyal credential is rotated** (a new secret version
is added and the old one disabled), update the version number in the block, and in
`tools/ulta_snapshot/README.md`, in the same change. A disabled or destroyed version ends the run
at once with `status=stopped_error proxy_bytes=0 challenge=no` and `detail=` containing
`secret version not accessible (disabled/destroyed?) — pin an enabled version`.

### Secret JSON schema

The secret payload is one JSON object with **exactly these five keys** (placeholders shown,
never put real values in the repo or a chat):

```json
{
  "host": "PROXY_HOST",
  "port": 12345,
  "username": "PROXY_USERNAME",
  "password": "PROXY_PASSWORD_WITH_COUNTRY_SUFFIX",
  "provider": "iproyal"
}
```

| Key | Type | Rule |
|---|---|---|
| `host` | string | not empty; the proxy host name only, no `http://` and no port |
| `port` | integer | 1-65535, a JSON number, not a string |
| `username` | string | the proxy login |
| `password` | string | the proxy password **including the country-targeting suffix** exactly as the IPRoyal dashboard generates it for AE. Country targeting lives only here. |
| `provider` | string | not empty, e.g. `iproyal` |

Any other key (for example `country`) is rejected. The run then ends at once, before any request,
with `status=stopped_error proxy_bytes=0 challenge=no` and
`detail=` containing `not valid proxy credentials (fields: ['country'])`. The error names only the
offending field names, never a value. Fix the secret by adding a new version, then pin that version.

## Stopping early

- Press **Ctrl-C** in the window, or open a second Cloud Shell tab and run `docker stop ulta-test`.
- Either way the job writes its files and prints its `ULTA TEST RESULT: status=stopped_by_operator`
  line (after Ctrl-C the line may only appear in `progress.json`).
- Then upload what was collected by hand, using the folder name printed as `files go to ...`:
  `gsutil -m cp -r ~/ulta-test-<UTC time> gs://pi-sephora-e631eaba/ulta-test/<UTC time>/`

## Rules this job keeps (for the record)

- Stock Playwright WebKit from the official image, pinned by tag and digest.
- No stealth, no fingerprint changes, no challenge solving, no logins, no cart.
- The container runs as your own user, not root.
- Your token is used only to read the proxy login. The job removes it from its environment
  before the browser starts, and it expires by itself within the hour. While the job runs it is
  still visible to you via `docker inspect ulta-test` in your own Cloud Shell. It is never
  printed or saved to the result files.

## Full snapshot (after the ~20-page test)

Run this only after the ~20-page test has finished and its `ULTA TEST RESULT` line has been
pasted, and only when the coordinator sends you a commit for it. It uses the same image, the same
pinned WebKit, the same proxy and the same stop rules as the test. It stops at the first challenge,
at a second 429 in a row, or when the 1.8 GB allowance would be crossed. Nothing is retried, and
nothing switches engine or route.

With `URL_SOURCE=sitemap` the job:

1. Fetches `robots.txt`. If it is missing or unreadable, the job stops (fail closed).
2. Fetches `/sitemap.xml`, then `product-sitemap-ae.xml`. Each sitemap URL is checked against
   robots.txt first.
3. Keeps only robots-allowed English `/en/buy-...` product URLs, removes duplicates, and writes
   them to `urls_full_en.txt` in the output folder.
4. Prints `SITEMAP: N urls, est A-B h, est G GB` **before** it fetches any product page. Hours
   assume 5-10 s per page. GB is `N x EST_BYTES_PER_PAGE`; the coordinator sends you that value,
   taken from the test's result.
5. Fetches up to `MAX_PAGES` product pages from `START_INDEX`, and records in `progress.json`
   (`next_index`) how far it got.

| Setting | Meaning |
|---|---|
| `MAX_PAGES=0` | List and estimate only; no product page is fetched. **Do this first.** |
| `MAX_PAGES=500` | At most 500 pages this run. |
| `MAX_PAGES=all` | The whole list, within the byte cap. |
| `START_INDEX=auto` | Continue from where the last run in the same folder stopped. `urls_full_en.txt` is reused, so no sitemap is fetched again. |

The output folder is fixed (`~/ulta-full`) so that a stopped run can be continued. Each run
adds its own `pdp/part-<start>-<time>.jsonl.gz` (a new file every run, even from the same
index) and keeps copies of the earlier `progress`/`manifest` files as `*-before-<time>.json`.
If a run fails before it starts (for example a bad token or a missing `PRIOR_GB`), nothing in
the folder is moved, and `START_INDEX=auto` still continues from the right place.

**Before each run, set `PRIOR_GB` again from the IPRoyal dashboard, rounded up.** The byte cap
counts everything already used. The job also never uses less than what the earlier runs in
`~/ulta-full` recorded (their prior + proxy bytes). If your figure is lower, it uses the folder's
figure and says so on a `PRIOR:` line.

The status in the last line:
- `complete`: this one run covered the **whole** list from index 0.
- `batch_complete`: this run finished its `MAX_PAGES` batch, or a resumed tail, without a stop.
  Run again with `START_INDEX=auto` for the rest. The loader records such a batch as a partial
  crawl, so nothing that was not fetched is ever taken as removed.
- `enumerated`: the list was built with `MAX_PAGES=0`.
- The stop statuses (`stopped_at_challenge`, `cap_reached`, `stopped_by_operator`,
  `stopped_error`) and the re-run rules are the same as for the test above.

Every upload holds the whole folder so far. The loader keys on the snapshot id in
`snapshot.json`, so a part that is already loaded is never loaded twice.

```bash
# ==== EDIT 1: commit (from the coordinator) ====
COMMIT=PASTE_COMMIT_HERE
# ==== EDIT 2: GB already used, from the IPRoyal dashboard NOW, ROUNDED UP ====
PRIOR_GB=PASTE_GB_HERE
# ==== EDIT 3: 0 = list + estimate only (first time); then a number or all ====
MAX_PAGES=0
# ==== EDIT 4: bytes per page (from the coordinator; leave empty if not sent yet) ====
EST_BYTES_PER_PAGE=
# ==== nothing below needs editing ====
(
set -e
test "$COMMIT" != PASTE_COMMIT_HERE || { echo "EDIT 1 first: set COMMIT"; exit 1; }
test "$PRIOR_GB" != PASTE_GB_HERE || { echo "EDIT 2 first: set PRIOR_GB"; exit 1; }
cd ~ && rm -rf pi-ulta-test && git clone -q https://github.com/muttonkodibiriyani/product_intelligence.git pi-ulta-test
cd ~/pi-ulta-test && git checkout -q "$COMMIT" && git log --oneline -1
docker build -q -f tools/ulta_snapshot/Dockerfile -t pi-ulta-fetch .
TS=$(date -u +%Y%m%dT%H%M%SZ); OUT=~/ulta-full; mkdir -p "$OUT"; echo "files go to $OUT"
TOKEN="$(gcloud auth print-access-token)"; export GOOGLE_OAUTH_ACCESS_TOKEN="$TOKEN"
docker run --rm -i --name ulta-full --user "$(id -u):$(id -g)" \
  -v "$OUT":/out \
  -e GOOGLE_OAUTH_ACCESS_TOKEN \
  -e URL_SOURCE=sitemap -e START_INDEX=auto -e MAX_PAGES="$MAX_PAGES" \
  -e EST_BYTES_PER_PAGE="$EST_BYTES_PER_PAGE" \
  -e PRIOR_GB="$PRIOR_GB" -e CAPTURE_JSON=0 \
  -e OWNER_APPROVAL_REF="ADR-0006 Amendment 2 (owner decision 2026-09-30: IPRoyal AE, ulta.ae only)" \
  -e SECRET_RESOURCE=projects/productintelligence-beeb3/secrets/pi-proxy-iproyal-ae/versions/4 \
  pi-ulta-fetch 2>&1 | tee "$OUT/console-$TS.log"
gsutil -m -q cp -r "$OUT" "gs://pi-sephora-e631eaba/ulta-full/$TS/"
echo "UPLOADED gs://pi-sephora-e631eaba/ulta-full/$TS/"
)
```

Paste back four lines: `PRIOR: ...`, `SITEMAP: ...`, `ULTA TEST RESULT: ...` and
`UPLOADED ...`. To stop early, press Ctrl-C or run
`docker stop ulta-full`. The files stay in `~/ulta-full`, and the next run with
`START_INDEX=auto` continues from there. The bucket keeps uploads for one day only.
