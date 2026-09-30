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
  -e SECRET_RESOURCE=projects/productintelligence-beeb3/secrets/pi-proxy-iproyal-ae/versions/latest \
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
| `stopped_error` | A proxy or login error, e.g. the secret could not be read. `detail=` says which. | Paste the line. Do not re-run. |

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
