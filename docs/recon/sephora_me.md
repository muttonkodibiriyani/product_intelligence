# Recon: Sephora Middle East (`www.sephora.me`)

- Status: **partial**. Rung 0 partly done (`robots.txt` and the sitemap index fetched; child
  sitemaps **not** fetched). Rungs 1–4 installed but **not executed** (see §2).
- Date: 2026-09-30
- Requirement IDs: SRC-01 (access method, rights basis, field contract), SRC-03 (discovery and count
  reconciliation, §3), SRC-08 (permitted access; deviations in ADR-0003 and ADR-0005), SCP-02 / SCP-08
  (coverage register and explicit limits), SCP-11 (decision log: ADR-0005).
- Blueprint refs: §1.1, §1.4, §6, §13; ADR-0003 (ladder), ADR-0005 (pilot scope, robots deviation, probe)
- Egress used: our server, an Indian (IN) datacenter IP.
- **Owner decisions of 30 Sep 2026 (ADR-0005, relayed by the program coordinator):**
  1. Pilot = **UAE only** (Sephora `ae-en` / `ae-ar` vs Ulta `ulta.ae`, EN + AR). KSA is dropped for now.
  2. Sephora's robots-disallowed paths, including the `/{locale}/api/v1` BFF, are **approved** at
     ~1 req/s with jitter, run off-peak (SRC-01/SRC-08 deviation).
  3. A Gulf-egress **probe is approved** (Cloud Run job, `me-central1`/`me-central2`, < $1). It
     runs as a separate task after this PR.
- **Rights basis / terms of use (SRC-01):** public, logged-out catalogue data only, under the
  owner's decisions in ADR-0003/ADR-0005. No account, cart or checkout. The site's terms of use
  have **not been reviewed**: the terms page sits behind the same Akamai page rule (§2). The probe
  should fetch and record them. §10 lists licensed alternatives, which SRC-01 prefers.

Every statement below is labelled **verified** (we saw it) or **inferred** (a reasonable reading of
what we saw, still to be confirmed).

## 1. Summary

| Market / locale | Discovery (sitemaps) | Product / category pages | Working rung |
|---|---|---|---|
| UAE `en-AE`, `ar-AE` (**pilot**) | Sitemap index **open at rung 0** (verified); child files not fetched | Same Akamai edge; assumed 403 from our egress (not tested separately) | none yet |
| KSA `en-SA`, `ar-SA` (out of pilot scope) | Sitemap index open at rung 0 with a browser User-Agent (verified) | **403 Akamai** at rung 0 (verified) | not pursued |

The sitemap index can be read for free. From our egress, product pages sit behind Akamai edge
rules. It is **still unknown** whether ordinary requests work from Gulf egress. The approved probe
(§9) answers that.

## 2. What was tried

| # | Rung | Request | Result |
|---|---|---|---|
| 1 | 0 | `curl` default UA → `/sa-en/`, `/robots.txt`, `/sitemap.xml` | **403** `AkamaiGHost`, 382 B "Access Denied" for all three |
| 2 | 0 | `curl` + desktop Chrome 140 UA + `Accept-Language` → `/robots.txt` | **200**, 1,645 B |
| 3 | 0 | same → `/sitemap.xml` | **200**, 11,801 B (index; see §3) |
| 4 | 0 | same → `/sa-en/` (home) | **403** Akamai, 382 B |
| 5 | 0 | bulk fetch of the child sitemaps at ~1 req/s | **not run**: blocked by this session's tool-permission policy |
| 6 | 1–4 | higher ladder rungs (ADR-0003) | **not run**: same policy |

Rows 1–4: Akamai rejects the bare `curl` UA on every path. A browser UA gets through, but only on
`robots.txt` and the sitemaps; HTML routes need more than a UA string. One reading (**inferred**)
is that page routes are scored on client fingerprint and IP reputation (datacenter ASN, non-GCC
location). The Gulf-egress probe with ordinary requests will show how much of this is location.

No proxy, Tor, login, cart or checkout was used. Total requests to `sephora.me`: 7. Nothing was
worked around.

## 3. Discovery (rung 0, index only)

`/sitemap.xml` is an index of **locale-specific slug sitemaps** plus an app-routes file (verified):

| Locale | Product sitemap files | Category sitemap files |
|---|---|---|
| `en-AE` | 40 (`productSlugsCO-0..39.xml`) | 10 |
| `ar-AE` | 40 | 10 |
| `en-SA` | 8 (`productSlugsCO-0..7.xml`) | 2 |
| `ar-SA` | 8 | 2 |
| — | `sitemap-app-routes.xml` | |

Counts from the coordinator's earlier pass (not re-counted here): `en-AE` ≈ **170.6k** entries,
`en-SA` ≈ **32.9k** product URLs.

**Reconciliation (open, SRC-03):** the 5× gap between AE and SA is too large to be explained by
assortment alone. Possible causes, not yet checked: AE entries count `<image:image>` children or
`hreflang` alternates as entries; AE lists one URL per variant/shade where SA lists one per
product; or AE still carries discontinued slugs. The probe must count **distinct product IDs** and
**distinct variant IDs** in the AE sitemaps, not `<loc>`/`<url>` elements. That count sets the
UAE volume in §6. Sample: `samples/sephora_sitemap_index_head.xml`.

## 4. Platform signals and robots status (inferred from `robots.txt`)

Sample: `samples/sephora_robots.txt` (as served 2026-09-30).

| Signal | Reading | Robots | Use |
|---|---|---|---|
| `/on/demandware.store/*`, `Product-Show`, `Product-Variation?pid=`, `Search-Show?cgid=`, `mastercatalog_sephora` | **Salesforce Commerce Cloud (SFCC)** back end, master catalogue `mastercatalog_sephora`, variants addressed by `pid` | Disallowed | Approved (ADR-0005) |
| `productSlugs`/`categorySlugs` sitemaps, `sitemap-app-routes.xml` | Probably a **headless front end** on slug routes | Allowed | Yes |
| `Disallow: */api/v1*` | The front end probably calls its own BFF at `/{locale}/api/v1/...`, the richest JSON candidate | Disallowed | Approved (ADR-0005) |
| `bvrrp=`, `bvstate=`, `bvroute=Reviews` | Reviews and ratings are served by **Bazaarvoice** | Disallowed on `sephora.me` | Approved on `sephora.me`; the Bazaarvoice host itself is third-party and unchecked |
| `/catalogs/mastercatalog_sephora/default/images` | Product images on SFCC's static image path | Disallowed | Approved (ADR-0005) |
| `search?q=`, `?sz=`, `prefn/prefv`, `pmin/pmax`, `srule` | Search and listing paging (`sz` = page size, `srule` = sort rule) | Disallowed | Approved (ADR-0005) |

The approval (ADR-0005) covers **pacing** (~1 req/s with jitter, off-peak), not only paths.
Fetches of robots-disallowed paths are tagged as such in the audit log. Login, cart, checkout,
wishlist and account routes stay out of scope.

## 5. Field-availability matrix

Legend: ✅ verified · ◐ expected (inferred, unverified) · ✗ not available · ? unknown.
"Rung" is the lowest rung expected to deliver the source, not a tested result. Only the sitemap
index has actually been observed. **(D)** = robots-disallowed, approved by ADR-0005.

| Field | Sitemap (r0) | PDP slug page: JSON-LD / embedded state | BFF `/api/v1` JSON (D) | Listing grid with paging (D) | Bazaarvoice API | Image host (D) |
|---|---|---|---|---|---|---|
| Product URL / slug | ✅ (index) / ◐ (children) | ◐ | ◐ | ◐ | ✗ | ✗ |
| Locale EN/AR | ✅ (separate files) | ◐ | ◐ | ◐ | ◐ (`locale`) | ✗ |
| `lastmod` | ? (not yet checked) | ✗ | ✗ | ✗ | ✗ | ✗ |
| Product ID / SKU | ? (slug may embed ID) | ◐ | ◐ | ◐ | ◐ (external ID) | ✗ |
| Brand, name, category path | ✗ | ◐ | ◐ | ◐ (partial) | ✗ | ✗ |
| Variants (shade/size), variant IDs | ✗ | ◐ (state blob) | ◐ | ✗ (master only) | ✗ | ✗ |
| Price (current) | ✗ | ◐ | ◐ | ◐ | ✗ | ✗ |
| Original / strike price | ✗ | ◐ | ◐ | ◐ | ✗ | ✗ |
| Promotions / badges | ✗ | ◐ | ◐ | ◐ | ✗ | ✗ |
| Stock / availability (variant) | ✗ | ◐ (JSON-LD `availability`) | ◐ | ◐ (master) | ✗ | ✗ |
| Description, ingredients, how-to | ✗ | ◐ | ◐ | ✗ | ✗ | ✗ |
| Rating, review count | ✗ | ◐ (JSON-LD `aggregateRating`) | ? | ◐ | ◐ | ✗ |
| Review texts | ✗ | ✗ | ✗ | ✗ | ◐ (paged) | ✗ |
| Image URLs (main/alt/swatch) | ◐ if `image:image` present | ◐ | ◐ | ◐ (main) | ✗ | — |
| Image bytes | ✗ | ✗ | ✗ | ✗ | ✗ | ? (untested) |
| Search rank | ✗ | ✗ | ◐ | ◐ | ✗ | ✗ |

## 6. Volume estimate (UAE, planning numbers, to be replaced after the probe)

Assumptions: ~10k products / ~33k variants in UAE. This is a placeholder taken from the `en-SA`
count; the real UAE count is unknown until §3 is reconciled. One PDP or BFF call returns all
variants. HTML PDP ≈ 400 KB, BFF JSON ≈ 20 KB, grid page ≈ 150 KB. At 1 req/s, 10k requests take
≈ 2.8 h. Runs are off-peak (UAE night), so a daily job has to fit in a ~6–8 h window.

### 6.1 Preferred (ADR-0005): BFF JSON + listing grid

| Job | Requests | Transfer |
|---|---|---|
| Daily price/stock/promo via listing grid (`sz` paging) | ~250–400/day | ~50 MB/day |
| Daily variant-accurate refresh via BFF, EN | 10k/day | 0.2 GB/day |
| Weekly content via BFF, EN + AR | 20k/week (≈ 2.9k/day) | 0.4 GB/week |
| Weekly reviews (Bazaarvoice, incremental) | ~1–3k/week (≈ 0.3k/day) | ~0.1 GB/week |
| Weekly discovery (AE sitemaps) | ~52 files/week | ~20 MB/week |

Per day: 0.4k + 10k + 2.9k + 0.3k ≈ **13.6k requests/day** (≈ 95k/week), which takes ≈ 3.8 h at
1 req/s and fits the off-peak window. Transfer: 1.4 (BFF) + 0.35 (grid) + 0.4 (content) + 0.1
(reviews) ≈ **2.3 GB/week** (≈ 10 GB/month).

### 6.2 Fallback: HTML only (if the BFF is unavailable or blocked)

- **Option A:** full daily PDP pass (EN, 10k/day = 70k/week) + weekly AR pass (10k/week) = 80k/week
  ≈ **11.4k/day**, ≈ 32 GB/week, ≈ 3.2 h/day.
- **Option B:** daily PDP for ~3k priority/changed items (21k/week) + weekly full EN (10k) + weekly
  AR (10k) = 41k/week ≈ **5.9k/day**, ≈ 16.4 GB/week, ≈ 1.6 h/day.

If UAE really has ~5× the placeholder product count, only 6.1 and a capped Option B fit the
off-peak window at 1 req/s.

## 7. Proxy Decision Report (provisional)

Rung 5 is **not** requested. The ladder has not been run, and ADR-0003 requires rungs 0–4 first.
If they all fail, these are the numbers for the owner (UAE; blueprint §13 proxy line is **$10–30/month**):

| Scenario | GB/month through proxy | At $3–8/GB residential | vs. $10–30 budget line |
|---|---|---|---|
| 6.1 BFF JSON + grid | ~10 | ~$30–80 | **exceeds** at all but the lowest price |
| 6.1 minus daily BFF refresh (grid daily + BFF weekly) | ~3–6 | ~$10–50 | fits at the low end only |
| 6.2 Option B (HTML) | ~70 | ~$210–560 | **exceeds**, not viable |
| 6.2 Option A (HTML) | ~140 | ~$420–1,100 | **exceeds**, not viable |

Conclusion: a proxy fits the budget only for JSON/grid traffic, with images and sitemaps fetched
direct, ETag/`If-Modified-Since`, and the BFF refresh limited to changed items.

## 8. Recommendation for PR6 (Sephora connector)

1. **Runtime and cost.**
   - **Approved probe (ADR-0005), budget < $1.** Cost line (unverified; check current GCP pricing
     for `me-central1`/`me-central2`, which are not Tier-1 regions):
     - Cloud Run job, 1 vCPU / 512 MiB, ~10 min per region × 2 regions ≈ 1,200 vCPU-s → **≈ $0.05**.
     - Artifact Registry image, ~0.5 GB for one month → **≈ $0.05**.
     - Cloud Build, one build → **$0** within the free build minutes.
     - Network egress, a few MB → **≈ $0**.
     - Total **≈ $0.10–0.20**. Delete the image and job after the probe. Cloud Run jobs availability
       in `me-central2` must be confirmed, with `me-central1` as the alternative.
   - **Recurring runtime (not yet approved; needs owner approval before creation):** the §6.1 daily job
     ≈ 3.8 h at 1 vCPU / 1 GiB ≈ 410k vCPU-s + 410k GiB-s per month ≈ **$12–16/month** at Middle East
     region pricing, before any free tier. Cloud Scheduler: first 3 jobs per billing account free.
     Cloud SQL is already in blueprint §13 ($0–10). If the probe shows our own server works, that is
     $0–3/month (blueprint §13) and stays the default.
2. **`discover()`:** AE sitemap index → locale child sitemaps (rung 0). Count distinct product and
   variant IDs (SRC-03). Use `lastmod` where present. Walk `categorySlugs` for the category tree.
3. **`fetch()`:** ladder order per ADR-0003; the working rung is chosen from recorded probe evidence
   and stored per context. Escalation options beyond ordinary requests are pending an owner decision.
4. **Source preference:** BFF `/api/v1` JSON > PDP embedded state + JSON-LD > listing grid (for daily
   price/stock sweeps). Variant data comes from the product's variation model in one call, not from
   `Product-Variation` calls one by one. Pacing is ~1 req/s with jitter, off-peak (ADR-0005).
5. **Reviews:** `aggregateRating` from the PDP/BFF. Review texts via Bazaarvoice after that host's
   robots/terms are checked (ADR-0005 covers `sephora.me` paths only). The passkey is read at runtime
   and **never committed**. Drop reviewer nickname, location, user ID and profile fields before
   storage (blueprint §12: no PII).
6. **Images:** fetch from the image path found in the PDP/BFF (approved even where robots-disallowed),
   deduped by SHA-256 (§6.5).
7. **Block detection:** `server: AkamaiGHost` + 403 + body `Access Denied` / `errors.edgesuite.net`
   reference (see `samples/sephora_akamai_403.html`). On block, back off. Affected listings are
   marked `blocked`/`not_observed` and the run is marked `partial` (blueprint §15.3). A blocked or
   partial run must **never** produce stock-outs or removals.
8. **Gate before coding PR6:** the probe results, replacing every ◐ above with ✅/✗ from real fixtures,
   and the §10 feed check.

## 9. Next steps (in order)

1. **Probe (approved, separate task):** Cloud Run job in `me-central1` and/or `me-central2`, normal
   browser User-Agent and ordinary requests first, ~1 req/s. Targets: `robots.txt`, the terms page,
   `/ae-en/` and `/ae-ar/` home, 3 PDPs from an `en-AE` product sitemap, 1 category page, the
   matching `/api/v1` calls, 1 image URL, and all AE child sitemaps (for §3). Report exactly what
   works from Gulf egress.
2. Count distinct products/variants in the AE sitemaps to close §3, then re-cost §6.
3. Check the feed options in §10 in parallel.
4. Only if ordinary requests fail from Gulf egress: a further owner decision on escalation, and
   only after that, a final Proxy Decision Report.

## 10. Licensed / partner full-catalogue sources (SRC-01 prefers these)

SRC-01 prefers licensed APIs or feeds to page collection. What desk research found (secondary
sources, **unverified**; nothing applied for):

| Source | What it would give | Status / how to get it |
|---|---|---|
| **Sephora ME affiliate programme, DCMnetwork** (UAE + KSA) | Affiliate programmes of this type usually provide a **product feed** (CSV/XML: product ID, name, brand, price, sale price, availability, image URL, deep link) plus promo codes | Apply as a publisher at dcmnetwork.com. Check whether the feed covers the full catalogue, both locales and variants, how often it refreshes, and whether its terms allow price analytics (many forbid non-promotional use) |
| **Sephora.ae on TradeTracker** (30-day cookie) | Same type of feed, if offered | Apply as a publisher at TradeTracker. Same checks |
| Other networks active in the Gulf (ArabClicks, Admitad, Optimise) | Sephora ME listing not confirmed | Check the network directories before applying |
| Sephora Squad ME (`sephorasquad.me`) | Influencer programme, **no data feed** | Not relevant |

Assessment: a feed from an affiliate network is the cleanest rights basis (SRC-01) and costs
nothing. It rarely carries full variant stock, content, ratings or reviews, and it may lag the site
by up to a day. Treat it as a **complement** to the BFF (IDs, prices, deep links, images), not a
replacement. The application needs a publisher identity (a website and a business owner). That is
the owner's call, and nothing has been applied for.

The Ulta side (Alshaya `ulta.ae` export, owner to request) is in `ulta_me.md` §5.
