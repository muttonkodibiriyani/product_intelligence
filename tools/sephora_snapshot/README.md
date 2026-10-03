# sephora_snapshot

One-off Sephora UAE (`/ae-en`, `/ae-ar`) catalogue snapshot for the pilot (task 01a0f424-006c).
Ordinary access only (ADR-0005/0006):
- plain `httpx` with normal browser headers;
- sequential, ~1 req/s with jitter;
- no retries, no impersonation, no proxy.

A challenge or a 401/403 stops the whole job. Anything not fetched is absent, which the
loader treats as `not_observed`.

| Module | Role |
| --- | --- |
| `run.py` | Cloud Run job. Full mode: sitemaps -> EN PDPs -> tRPC stock -> AR PDPs, until `CUTOFF`. `PLAN=<object>`: a continuation run over a plan (tRPC unless `TRPC=0`, then the plan's AR PDPs). |
| `plan.py` | Builds a continuation plan from a finished snapshot folder: `--phase stock` (EN seeds, skips stock already read) or `--phase ar` (AR seeds, skips AR pages already fetched; run with `TRPC=0`). `--done` adds earlier continuation folders. |
| `cadence.py` | Pure rules for unattended runs: the window and cutoff, the gap-first plan, the run outcome and the unloaded-run check. |
| `stale.py` | Host side, read-only: lists runs still unloaded at day 10 (exit 1 if any), for the host timer or monitoring. |
| `load.py` | Idempotent load of a synced folder into `pi_db`. It keeps a part ledger, creates one `crawl_run` per language only once that language has rows, and `--finish` closes them. `succeeded` is strict: `mode=full`, `limit=0`, `trpc=true`, `stopped=complete`, every seeded page and stock read done with no block, 429, transport, HTTP or parse skip. Everything else, including every PLAN run, is `partial`. Prices are parsed as exact decimals, and a price without a currency is stored as `unknown`, never AED. `--country SA` loads a Saudi (`COUNTRY=SA`) snapshot as its own source, `sephora_sa`, with `en-SA`/`ar-SA` contexts on Asia/Riyadh time: it never upserts or re-dates a `sephora_me` listing, never writes a brand row it did not create (a name another source owns is counted as `brand_name_clash`), and stores a price in any currency other than SAR as `unknown` (`price_currency_mismatch`). AE stays the default and is unchanged. |

Env for `run.py`:
- `BUCKET` (`file:<dir>` for local tests);
- `PREFIX`, `CUTOFF` (ISO-8601);
- optional: `PACE` (>= 1.0 s, enforced), `LIMIT`, `TRPC`, `PLAN`;
- capture options (task 01a0fc6d, KSA): `COUNTRY` (`AE` default or `SA`: picks the `en-SA`/`ar-SA`
  locales and the `sa-*` sitemap entries), `FULL=1` (keep every `productDetails` field, nothing
  dropped), `RAW=1` (store each page as `raw/<lang>-<pid>.html.gz` with its sha256 in the row),
  `IMAGES=1` (download the EN product and variant pictures to `images/<sha256>.<ext>`, deduplicated
  by URL, paced by `IMAGE_PACE` >= 1.0 s or the host's `Crawl-delay` if longer, each image host's
  robots.txt read first and refused when unreadable; the first 401/403 or non-image 200 stops the
  picture pass for the run, never the page pass), `IMAGE_HOSTS` (comma-separated exact hostnames
  a picture may be fetched from, default `img-product.sephora.me`; a URL that is not `https` on
  one of them is recorded `host_refused` and never requested). Pictures are always fetched
  directly, never through a proxy. Redirects are never followed blindly: each hop (at most 5) is
  gated before anything is requested for it, its robots.txt included. A picture hop must stay
  on an allowed image host; a page, sitemap or tRPC hop on the storefront host
  (`www.sephora.me`); a robots.txt hop on the very host whose robots.txt was asked for; all
  `https`, exact host, no userinfo, no port. Anything else is `host_refused` (count
  `hop_host_refused`), and a refused robots.txt hop leaves that host's robots unreadable, so its
  pictures are refused too. A seed or plan URL off the storefront is `host_refused` without a
  request. Allowed hops are then checked against the target host's robots.txt; every row records
  `final_url` and, when there were hops, `redirects`. Bodies are read under a byte cap (pictures
  10 MB, robots.txt 512 KB, pages 32 MB, sitemaps 50 MB as sitemaps.org allows); over it nothing
  is stored and the row says `too_large`. See ADR-0009, amendment 2026-10-02.
- or `AUTO=1` instead of `PREFIX`/`CUTOFF`/`PLAN` (setting any of them with `AUTO=1` makes no
  request: the run ends with outcome `refused` under its own new prefix and exits 1).

Unattended runs (`AUTO=1`, ADR-0009 variant pass):
- `PREFIX` is `auto-<start, YYYYMMDDTHHMMSSZ>`, plus `-<execution suffix>-<attempt>` from
  `CLOUD_RUN_EXECUTION`/`CLOUD_RUN_TASK_ATTEMPT` on Cloud Run. The job refuses to start, writing
  nothing, if that prefix already holds objects. `CUTOFF` is the next 01:55Z. A start outside
  18:00Z-01:55Z fetches nothing and ends with outcome `outside_window`.
- The job seeds from the sitemaps, then plans gap-first from every earlier run's `covered.json.gz`
  still in the bucket: products with no EN page attempt, then products last seen with differently
  priced variants, then the rest, longest-unattempted first (a failed page counts as attempted, so
  it rotates rather than heading every plan). An unreadable `covered.json.gz` is skipped and
  counted as `plan_covered_unreadable`. Interim: the first tier is a proxy from the bucket's last
  14 days, not ADR-0009's gap detector (listing variant ids against pi_db), which needs the
  listing sweep. Each product gets its EN page, then its stock
  read (`TRPC=0` skips stock). No AR pages: AR is the weekly discovery pass.
- How often it runs is the Scheduler's setting. ADR-0009 makes the variant pass weekly, over two
  consecutive nights (the second night picks up where the first stopped, because the plan reads
  the first night's `covered.json.gz`). The nightly listing sweep is a separate build.
- Every AUTO run is `partial` in pi_db (it covers a subset by design).

Every run, in every mode, ends by writing two files under its prefix:
- `covered.json.gz`: the products whose EN page was attempted, whose EN page (with a multi-price
  flag) and stock were read, and when. The next AUTO plan reads it.
- `status.json`: the terminal marker, written once at the end. `state` is `finished`, and
  `outcome` is `complete`, `cutoff`, `blocked`, `rate_limited`, `outside_window`, `refused` or `error`. It also
  carries `stopped`, `started`, `finished`, `cutoff`, `mode`, `loadable` and `counts`. An unexpected
  error still writes it, and then the job exits 1 (as does `refused`).

Retention and the day-10 check: the run bucket deletes objects 14 days after they are written
(#124). `python -m sephora_snapshot.stale <bucket>` (read-only on pi_db) reports every run that is
at least 10 days old, has something to load, and has no finished `crawl_run` in pi_db. A held load
therefore raises an alert four days before its run is deleted.

`progress.json` records `mode`, `limit`, `trpc`, `country`, `full`, `raw`, `images`,
`image_hosts` and `image_pace_s`.

Off-peak window: runs are scheduled in the UAE night, 18:00Z-02:00Z (22:00-06:00 Gulf time), and `CUTOFF` must fall inside it. Longer passes are split across nights, and each continuation excludes work already done (`plan.py --done`). The single exception was the owner-approved first snapshot (execution `9drcr`, 2026-09-30/10-01): it ran to its own 03:20Z cutoff.

A stock-read variant with no `inStock` value is not recorded as an observation; it is counted as `trpc_instock_unknown`.

Tests use synthetic payloads only (`tests/sephora_synth.py`).
