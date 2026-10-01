# ADR-0009: Recurring Sephora UAE snapshots for price/stock history

- Status: accepted. These are owner decisions relayed by the coordinator on 1 Oct 2026:
  - Q1: the follow-up recon was approved, in revised form (a).
  - Q2: the cheap cadence was approved, on condition that Q1 succeeded. It did.
- Date: 2026-10-01
- Amended 2026-10-01 (owner approval, relayed by the coordinator): a deeper category tree and
  variant breadth. Decision 2 is now a gap-first variant pass with a first-run backfill, and
  Decision 3 a leaf-level sweep with the `cgid` tree, EN + AR. Same method, pace, window and
  stop rules; no new path. The estimate is on paper (offline analysis of the saved recon samples
  and the baseline); no request was made for it.
- Drafted by: the Crawl Engineer, on the coordinator's brief.
- Supersedes (for `sephora_me` only): the 2026-09-30 decision "one-time baseline snapshot per
  source, then on-demand refreshes only". That covers the blueprint's Cadence row, §6.4 and its "No
  Cloud Scheduler jobs" line, and the §Costs crawling row.
- Sequencing: **the build starts after the landing dashboard ships.** Nothing in this ADR is built
  or scheduled before then.
- Carries over unchanged:
  - ADR-0005 (UAE pilot);
  - ADR-0006 (access rulings): ordinary browser behaviour only, no impersonation, no stealth, no
    challenge solving, no proxy, stop on any block, and no change of egress after a block;
  - blocked or unread means `not_observed`, never out of stock or removed;
  - regular price decision A: regular stays `not_collected`, and `c_valuePrice` is never used;
  - Ulta stays blocked. This ADR adds no Ulta collection.

## Context
The owner wants product-journey history: price, promo and stock over time. The dataset contract
never carries a value forward (v2 rule 6). History therefore exists only where a source is re-read
on a later date.

Measured on the 30 Sep–1 Oct baseline, at the polite rate (~0.5 req/s, one worker, UAE night),
each product needs one PDP read for price and one tRPC read for stock. A full pass is ~16.6k
requests, ~9 h and ~$0.7 on Cloud Run. That does not fit the 18:00–02:00Z night window.

### Recon (b) and Q1, 1 Oct 2026
Both were owner-approved and one-off. The vehicle was the existing Cloud Run job, PACE 2.0, with no
cookies or auth. Every request returned 200 with no block.

1. **4 listing-page GETs** (execution `q4nth`).
   - Category pages are server-rendered with 36 product tiles.
   - `?page=` and `?sz=` are ignored.
   - "Load More" is client-side.
2. **The route's 32 public static JS chunks** (execution `msskc`).
   - They show that Load More calls the site's tRPC procedure `products.getProducts`, with
     `{refine, locale, category, targetCategoryId, offset, q?, isBrandPage?, sort?}`.
   - Page size is fixed by the client at 36. There is no size argument, and we add none.
3. **2 calls of that procedure** for Makeup > Face (C342, total 982), execution `gm8sr`:
   - `offset=36` returns 36 hits, 157 KB.
   - `offset=972` returns 10 hits, so it ends exactly at `total`.

Each hit is **product-level**:
- `c_price`: the lowest variant price (the "from" price). It matched the PDP variant range on 71/71
  tiles cross-checked;
- `c_isInStock` and `c_isLowStock`;
- `c_productAts`: an available-to-sell count;
- `c_variantsCount`, plus variant ids only;
- promotions, rating and image.

The listing carries no regular-price signal: the old price equals the price, and the discount is
undefined. Per-variant price and stock are not on the listing. 1,203 of 8,299 products (14.5%)
have variants at different prices.

## Decision
1. **Nightly listing sweep** (product-level, ~100% of the catalogue).
   - For each top-level category, page `products.getProducts` from offset 0 to `total` with the
     client's own arguments, sequentially at PACE with jitter, during the UAE night.
   - Basis: `/api/trpc` is robots-disallowed. Collecting it is covered by ADR-0005 decision 2, the
     owner's approval of Sephora's robots-disallowed paths at polite pacing (~1 req/s with jitter,
     off-peak UAE night, no login, cart, checkout or account routes). Per ADR-0005's consequences
     and the recon doc, every such fetch is tagged robots-disallowed in the audit log (the job
     runs with robots `tag_only`). This ADR adds a schedule, not a new path or a faster rate.
   - About 8.3k / 36 ≈ 235 calls, and at most ~380 if the sweep has to use leaf categories.
   - About 5–13 minutes at PACE 1.0–2.0.
   - The sweep dedupes by product id and counts unique products against `total`. Any shortfall
     stays `not_observed`.
   - The default order can drift: page 1 over SSR and page 2 over tRPC, 20 minutes apart, shared 4
     of 36 ids. If drift is material, the sweep uses a stable option from the response's
     `sortingOptions`. The build verifies this before go-live.
2. **Weekly variant-level pass, gap-first** (amended).
   - EN PDP (price, content, variants/shades/sizes, hotlinked image URLs) plus tRPC availability
     (stock) for every product, split over two nights inside the window.
   - The planner orders it gap-first and stops at the cutoff:
     1. products whose listing variant ids (`representedProducts`) are not all in the DB, and new
        products;
     2. products with differently priced variants (~1.2k, 14.5%);
     3. the rest.
   - The gap detector is exact: it compares the listing's variant ids with the DB. Nothing is
     guessed.
   - The nightly sweep also queues PDPs for its own gap set, typically tens of products, a few
     minutes a night.
   - **First run = backfill, PDPs only.** Every product's EN PDPs on night 1 (~8.3k, ~4.6 h) and
     its AR PDPs on night 2 (~4.6 h). Each night fits the 18:00–02:00Z window.
     - The backfill carries **no tRPC stock reads**. A PDP-plus-stock pass for every product
       (~16.6k requests, ~9 h, see Context) would not fit one night.
     - Product-level stock comes from the nightly sweep. Variant-level stock stays in the regular
       weekly pass, split over its two nights as above.
     - Sizes for reference: the ~1.2k multi-price products take ~40 min; every multi-variant
       product (~4–6.5k) takes ~2.2–3.6 h.
   - Raw PDP HTML is not kept. The job stores extracted records only, plus a page's raw HTML when
     it fails to parse, under the run's own GCS prefix. The build PR states the retention
     (lifecycle rule) for those prefixes.
   - Images: URLs only, hotlinked from `img-product.sephora.me` (Images B). No image bytes are
     fetched or rehosted.
3. **Weekly AR pages and discovery, leaf-level** (amended).
   - AR PDPs plus a sitemap diff. New products join the sweep automatically.
   - The discovery night sweeps every **leaf** category with the same `products.getProducts`
     call, in EN and in AR (`ar-AE`): about 380–420 calls per locale.
   - The `cgid` refinement in each response carries the nested category tree with hit counts
     (e.g. Makeup C302 > Face C342 > 11 leaves). The run stores the tree (ids, EN and AR labels)
     and each product's leaf membership. Leaves overlap: Face's leaves sum to 1,120 hits against
     982.
   - Category and AR labels are stored as data only: they are displayed, never interpreted. The
     sweep calls only the leaf ids that the `cgid` tree returns, never URLs built from labels.
   - The export keeps `CATEGORY_DEPTH` 3. Publishing the deeper tree waits for the Deep Coder's
     `category_tree` fix, and any depth change needs the owner's OK.
   - "Removed" is recorded only from an explicit page result, never from absence in a listing or
     sitemap.
4. **Each run is its own dated snapshot.**
   - Every run gets a new GCS prefix and its own `crawl_run` rows, and the strict status rule
     applies.
   - Nothing is carried forward. A product not seen on a date is `null` for that date.
5. **Contract (agreed with the Deep Coder).**
   - Listing observations go to the **v3 producer path only**; v2 stays frozen.
   - They are published as `offer.series.listing = {fromPrice: MoneyValue|null, inStock:
     bool|null, lowStock: bool|null}`, dated like the other series. `null` means not observed, and
     there is no carry-forward.
   - There are `capabilities.listing` and `fields.listing.{fromPrice,inStock,lowStock}`.
   - `ats` stays internal: it is kept in the DB and not exported.
   - `variantsCount` is internal until the owner approves publishing it.
   - `pi_metrics` never reads `listing.*` into price, availability or promo metrics. A later
     endpoint reads it explicitly as a "from" price.
6. **Automation, as the owner directed.**
   - Cloud Scheduler starts the existing Cloud Run job through a dedicated service account that
     has `run.invoker` on that job only.
   - The job builds its own plan from the previous runs' outputs, so no laptop or agent session is
     in the loop.
   - Infra owns the host-side wiring, on the **existing pilot host**: the VM that runs the pi
     Postgres (Docker Compose), where the loader, export and publish already run. A systemd timer
     there waits for the run's status file → load → finish → export → **publish only through the
     gate**.
   - The gate is the existing publish gate (`infra/scripts/publish_dataset.py`), extended with
     the no-count-drop and newer-cutoff holds that Infra runs by hand today. Infra does that
     extension as an infra PR when this is built.
   - Proposed, **not approved by this ADR**: the host uses a dedicated publisher service account
     whose key is a 0600 file on the host, never in the repo. The nightly path would then not use
     the broad Firebase admin key.
   - Target scope (what IAM can enforce, stated at build time):
     - read the run outputs, and write `datasets/**` in the Firebase bucket only through an IAM
       Condition on the object-name prefix;
     - Firestore `demo_meta`-only is **not** IAM-enforceable. IAM grants database-level roles,
       and the Admin SDK bypasses security rules. The build PR states the actual Firestore grant,
       or a separate database, as the residual scope.
   - Creating any service account or key (this publisher SA and the Scheduler invoker SA) needs
     the owner's explicit OK at build time.
   - There is no new runtime. There are no tokens in a crontab, the repo or a log.
   - If the agent safety classifier refuses to install the systemd timer, the owner installs the
     unit files from `infra/`, as with the backup cron.
7. **Guards.**
   - Any block or challenge stops the run, and the run is partial.
   - The gate holds the publish when the run failed, the cutoff is not newer than the live
     dataset, or counts drop.
   - Pausing the Scheduler job stops everything.
   - Changes to pacing, window or scope need the owner's approval.

## Cost
- Nightly sweep: ~$0.01–0.02/night, which is under $1/month.
- Weekly variant pass and weekly AR + discovery: ~$3–4/month.
- Leaf-level sweep (amended Decision 3): ~10–20 min and ≈ $0.03 per locale per run, so EN + AR
  add ≈ $0.12/month. Data is ~150 KB per call, so ~60 MB per locale.
- **Steady state: about $4.5–5.5/month.** There is no proxy spend.
- One-off first-run backfill (amended Decision 2): ≈ $0.40 for EN and ≈ $0.75 with AR, over 2
  nights. PDP HTML is ~1–4 GB inbound; inbound and same-region GCS writes are free.
- **First month: about $5–6**, including the backfill.
- Owner approved gap-fill Sephora crawling (subcategory depth + shade/size variants) on
  2026-10-01, within the $25/month cap, folded into the approved cadence (relayed by the
  coordinator). That adds about +$0.5–1/month over the $4–5 above, plus the one-off ≈ $0.75
  backfill.
- Cloud Scheduler: one job, inside the free tier (3 jobs per billing account), so $0.
- Host side: no new runtime and no new cost beyond the job runs already budgeted. The publisher
  service account is free.

## Alternatives considered
- **PDP halves nightly:** variant-level price and stock for half the catalogue each night, about
  8.3k requests and 4.6 h per night, $15–25/month. It was rejected: about 30× the traffic for
  variant detail that only 14.5% of products need. Those products get it weekly instead.
- **Listing pages without paging:** about 47% coverage, the first 36 per leaf category. Paging
  turned out to work, so this was not needed.
- **Full price + stock nightly:** needs a higher rate than the polite one. Not proposed.
- **Status quo (on demand only):** gives no history unless someone asks for a refresh.

## Consequences
- The blueprint's Cadence row, §6.4 and the crawling cost row now point here for `sephora_me`.
  "No Cloud Scheduler jobs" becomes "one Scheduler job, `sephora_me` only, owner-approved
  (ADR-0009)".
- Build: about 1.5 days, after the landing ships.
  - The Crawl Engineer builds the listing parser and fixtures (synthetic only), the product-level
    observation path, the in-job planner (gap-first order, first-run backfill) and the leaf-level
    sweep with the `cgid` tree.
  - The Deep Coder builds v3 `offer.series.listing`.
  - Infra builds the Scheduler, timer and gate wiring. The service accounts and key are created
    only after the owner's explicit OK at build time; this ADR does not approve them.
- Until the build lands, Sephora history comes only from approved one-off runs.
