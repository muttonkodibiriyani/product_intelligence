# Recon: Sephora Middle East (`www.sephora.me`)

- Status: **partial**. Rung 0 partly done (`robots.txt` and the sitemap index fetched; child
  sitemaps **not** fetched). Rungs 1–4 installed but **not executed** (see §2).
- Date: 2026-09-30
- Requirement IDs: SRC-01 (access method, rights basis, field contract), SRC-03 (discovery and count
  reconciliation, §3), SRC-08 (permitted access; deviation recorded in ADR-0003), SCP-02 / SCP-08
  (coverage register and explicit limits), SCP-11 (decision log).
- Blueprint refs: §1.1, §1.4, §6, §13; ADR-0003 (ladder), ADR-0004 (KSA → UAE fallback)
- Egress used: our server, an Indian (IN) datacenter IP.
- **Pilot market: UAE.** Owner decision, relayed by the program coordinator on 2026-09-30: Ulta ME
  has no KSA storefront (see `ulta_me.md` §1), so the Ulta ↔ Sephora pilot runs on UAE. Sephora UAE
  (`en-AE`, `ar-AE`) comes first. Sephora KSA (`en-SA`, `ar-SA`) stays in scope where it can be
  collected. This still has to be entered in the decision log (SCP-11).
- **Rights basis / terms of use (SRC-01):** public, logged-out catalogue pages only. No account,
  cart or checkout. The site's terms of use have **not been reviewed**: the terms page sits behind
  the same Akamai page rule (§2). Someone must read and record them before PR6 goes live.

Every statement below is labelled **verified** (we saw it) or **inferred** (a reasonable reading of
what we saw, still to be confirmed).

## 1. Summary

| Market / locale | Discovery (sitemaps) | Product / category pages | Working rung |
|---|---|---|---|
| UAE `en-AE`, `ar-AE` (pilot) | Sitemap index **open at rung 0** (verified); child files not fetched | Same Akamai edge; assumed 403 (not tested separately) | none yet |
| KSA `en-SA`, `ar-SA` | Sitemap index **open at rung 0** with a browser User-Agent (verified); child files not fetched | **403 Akamai** at rung 0 (verified) | none yet; rungs 1–4 not run |

The sitemap index can be read for free. From our egress, product pages sit behind Akamai edge rules.
It is **still unknown** whether any free rung gets past them. Two open owner decisions gate the next
step (§9): the probe method, and whether robots-disallowed paths may be used.

## 2. What was tried

| # | Rung | Request | Result |
|---|---|---|---|
| 1 | 0 | `curl` default UA → `/sa-en/`, `/robots.txt`, `/sitemap.xml` | **403** `AkamaiGHost`, 382 B "Access Denied" for all three |
| 2 | 0 | `curl` + desktop Chrome 140 UA + `Accept-Language` → `/robots.txt` | **200**, 1,645 B |
| 3 | 0 | same → `/sitemap.xml` | **200**, 11,801 B (index; see §3) |
| 4 | 0 | same → `/sa-en/` (home) | **403** Akamai, 382 B |
| 5 | 0 | bulk fetch of the 60 SA + en-AE child sitemaps at ~1 req/s | **not run**: blocked by this session's tool-permission policy |
| 6 | 1–4 | curl_cffi, Playwright (headless/Xvfb), Scrapling/Camoufox/patchright, Cloud Run egress | **not run**: same policy; tools installed in a throwaway venv only |

Rows 1–4: Akamai rejects the bare `curl` UA on every path. A browser UA gets through, but only on
`robots.txt` and the sitemaps; HTML routes need more than a UA string. One reading (**inferred**) is
an Akamai Bot Manager policy that scores the TLS/HTTP2 fingerprint and IP reputation (datacenter
ASN, non-GCC location) on page routes.

No proxy, Tor, login, cart or checkout was used. Total requests to `sephora.me`: 7.

**Why rungs 1–4 were not run:** the agent's permission layer classified automated bulk fetching and
bot-evasion against this third-party site as disallowed for an unattended session. They were not
worked around. How the ladder probe is run is a pending owner decision (§9).

## 3. Discovery (rung 0, index only)

`/sitemap.xml` is an index of **locale-specific slug sitemaps** plus an app-routes file (verified):

| Locale | Product sitemap files | Category sitemap files |
|---|---|---|
| `en-SA` | 8 (`productSlugsCO-0..7.xml`) | 2 |
| `ar-SA` | 8 | 2 |
| `en-AE` | 40 (`productSlugsCO-0..39.xml`) | 10 |
| `ar-AE` | 40 | 10 |
| — | `sitemap-app-routes.xml` | |

Counts from the coordinator's earlier pass (not re-counted here): `en-SA` ≈ **32.9k** product URLs,
`en-AE` ≈ **170.6k** entries.

**Reconciliation (open, SRC-03):** a 5× gap between SA and AE is too large to be explained by
assortment alone. Possible causes, not yet checked: AE entries count `<image:image>` children or
`hreflang` alternates as entries; AE lists one URL per variant/shade where SA lists one per
product; or AE still carries discontinued slugs. The trial run must count **distinct product IDs**
and **distinct variant IDs** per locale, not `<loc>`/`<url>` elements. Because UAE is the pilot,
this count decides the UAE volume in §6. Sample: `samples/sephora_sitemap_index_head.xml`.

## 4. Platform signals and robots status (inferred from `robots.txt`)

Sample: `samples/sephora_robots.txt` (as served 2026-09-30).

| Signal | Reading | Robots status |
|---|---|---|
| `/on/demandware.store/*`, `Product-Show`, `Product-Variation?pid=`, `Search-Show?cgid=`, `mastercatalog_sephora` | **Salesforce Commerce Cloud (SFCC)** back end, master catalogue `mastercatalog_sephora`, with variants addressed by `pid` | **Disallowed** |
| `productSlugs`/`categorySlugs` sitemaps, `sitemap-app-routes.xml` | Probably a **headless front end** on slug routes | Sitemaps and slug routes **allowed** |
| `Disallow: */api/v1*` | That front end probably calls its own BFF at `/{locale}/api/v1/...`, the richest JSON candidate | **Disallowed** |
| `bvrrp=`, `bvstate=`, `bvroute=Reviews` | Reviews and ratings are served by **Bazaarvoice** | Those `sephora.me` routes are **disallowed**; the third-party Bazaarvoice host is unchecked |
| `/catalogs/mastercatalog_sephora/default/images` | Product images on SFCC's static image path (there may also be a separate CDN host) | That path is **disallowed**; any other image host is unchecked |
| `search?q=`, `?sz=`, `prefn/prefv`, `pmin/pmax`, `srule`, `Search-Show?cgid=` | Search and listing paging exist (`sz` = page size, `srule` = sort rule) | **Disallowed** |

**Robots decision (pending, owner):** the richest sources (BFF JSON, listing paging, variation
calls, Bazaarvoice review routes, the SFCC image path) are all robots-disallowed. ADR-0003 records
the owner's choice of the ladder over SRC-08. It does **not** decide robots compliance. This doc
therefore treats the **robots-compliant path as the baseline** (§6–§8). The disallowed paths appear
only as a labelled alternative that applies **only if the owner approves a robots deviation (not yet
decided)**. If approved, the deviation goes into the decision log (SCP-11) and the traceability
matrix before PR6 uses any of those paths.

## 5. Field-availability matrix

Legend: ✅ verified · ◐ expected (inferred, unverified) · ✗ not available · ? unknown.
"Rung" is the lowest rung expected to deliver the source, not a tested result. Only the sitemap
index has actually been observed. Columns marked **(R)** are robots-disallowed and depend on the
pending owner decision.

| Field | Sitemap (r0) | PDP slug page: JSON-LD / embedded state (r1–3) | BFF `/api/v1` JSON **(R)** | Listing grid with paging **(R)** | Bazaarvoice API **(R/unchecked)** | Image host |
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
| Image bytes | ✗ | ✗ | ✗ | ✗ | ✗ | ? (SFCC path is (R); any other CDN host unchecked) |
| Search rank | ✗ | ✗ | ◐ | ◐ | ✗ | ✗ |

On the robots-compliant baseline, **review texts** and **search rank** are not available (SCP-08:
show them as unavailable). Variant-level price and stock depend on the PDP carrying the full
variation model in embedded state. JSON-LD alone often lists only the selected variant.

## 6. Volume estimate (planning numbers, to be replaced after the trial run)

Assumptions: ~10k products / ~33k variants per market (from `en-SA` 32.9k URLs, unreconciled);
one PDP returns all variants; HTML PDP ≈ 400 KB, BFF JSON ≈ 20 KB. At 1 req/s, 10k requests
take ≈ 2.8 h.

### 6.1 Baseline: robots-compliant (sitemaps + PDP slug pages), one market

| Job | Requests | Transfer (HTML) |
|---|---|---|
| Weekly discovery (sitemaps) | ~12 files (SA) / ~52 (AE) per week | ~20 MB/week |
| **Option A:** full daily PDP pass, EN | 10k/day → 70k/week | 4 GB/day → 28 GB/week |
| **Option B (recommended):** daily PDP for ~3k priority / changed items, EN | 3k/day → 21k/week | 1.2 GB/day → 8.4 GB/week |
| + weekly full PDP pass, EN (Option B only) | 10k/week | 4 GB/week |
| Weekly AR content pass (both options) | 10k/week | 4 GB/week |

Totals per market:
- Option A: 70k + 10k = **80k requests/week ≈ 11.4k/day**, ≈ 32 GB/week, ≈ 3.2 h/day at 1 req/s.
- Option B: 21k + 10k + 10k = **41k requests/week ≈ 5.9k/day**, ≈ 16.4 GB/week, ≈ 1.6 h/day.

Images are not included: they are gated on the image-host question in §4.

**UAE (pilot):** the product count is unknown until §3 is reconciled. If UAE ≈ KSA in distinct
products, the same numbers apply. If UAE really has ~5× the products, Option A (≈ 14 h/day at
1 req/s) cannot run, and Option B's priority set has to be capped. KSA, when enabled, adds its
own figures on top.

### 6.2 Alternative: only if the owner approves a robots deviation (not yet decided)

Daily price and stock via listing grid paging (`?sz=`, ~250–400 requests) plus a BFF JSON PDP
refresh (10k × 20 KB = 0.2 GB/day). Weekly JSON content EN + AR is 20k requests (0.4 GB). Bazaarvoice
reviews are ~1–3k incremental requests per week (~0.1 GB). Per market: 10k + ~0.4k + 20k/7 + ~0.3k ≈ **13.5k requests/day**;
transfer 1.4 (BFF) + 0.35 (grid, ~50 MB/day) + 0.4 (content) + 0.1 (reviews) ≈ 2.3 GB/week.

## 7. Proxy Decision Report (provisional)

Rung 5 is **not** requested. Rungs 1–4 have not been run, and ADR-0003 requires them first. If the
supervised run fails on all of them, these are the numbers for the owner (one market; blueprint §13
proxy line is **$10–30/month**):

| Scenario | GB/month through proxy | At $3–8/GB residential | vs. $10–30 budget line |
|---|---|---|---|
| Baseline Option B (HTML PDPs) | ~70 | ~$210–560 | **exceeds**, not viable |
| Baseline Option A (HTML PDPs) | ~140 | ~$420–1,100 | **exceeds**, not viable |
| Alternative 6.2, JSON + grid (needs robots deviation) | ~10 | ~$30–80 | **exceeds** at all but the lowest price |
| Alternative: grid daily + JSON weekly only (needs robots deviation) | ~3–6 | ~$10–50 | fits at the low end only |

Conclusion: a proxy only fits the budget if the owner approves the robots deviation **and** traffic
is limited to JSON/grid calls. On the robots-compliant baseline, a proxy is not affordable. In that
case the fallback is SCP-08: mark the context `blocked` and show the limits. Any proxy use also
needs ETag/`If-Modified-Since` and PDP refresh on changed items only.

## 8. Recommendation for PR6 (Sephora connector)

1. **Runtime:** run from **our server** first (blueprint §13: crawling from our server, $0–3/month).
   A GCC-egress runtime (Cloud Run job + Cloud Scheduler in `me-central1` Doha or `me-central2`
   Dammam) is an option **that requires owner approval before any resource is created**. Rough cost
   (unverified; check against current GCP pricing first): Middle East regions are not Tier-1 and are
   priced higher. The free tier may not apply the same way. Cloud Run **jobs** availability in
   `me-central2` must be confirmed. A daily ~1.6 h job at 1 vCPU / 1 GiB ≈ 175k vCPU-s + 175k GiB-s
   per month ≈ **$5–8/month** before any free tier. Cloud Scheduler: first 3 jobs per billing
   account free, then ~$0.10/job/month. Cloud SQL is already budgeted in §13 ($0–10). A one-off probe
   job costs cents but still needs approval. Build and enable **`AE` first** (pilot), then `SA`.
2. **`discover()`:** sitemap index → locale child sitemaps (rung 0). Count distinct product and
   variant IDs (SRC-03). Use `lastmod` where present. Walk `categorySlugs` for the category tree.
3. **`fetch()`:** ladder order per ADR-0003. The working rung is chosen from recorded evidence of
   the supervised probe and stored per context. Any Akamai-specific handling needs its own explicit
   owner decision in the decision log (SCP-11) that cites the SRC-08 deviation.
4. **Source preference (baseline):** sitemaps + PDP slug pages (JSON-LD + embedded state). The BFF
   `/api/v1`, listing paging, `Product-Variation` and demandware routes are used **only if** the
   owner approves a robots deviation (§4, §6.2).
5. **Reviews:** baseline = `aggregateRating` from JSON-LD. Review texts via Bazaarvoice only after
   an owner decision, and after that host's robots/terms have been checked. The passkey is read at
   runtime from the page and **never committed**. Drop reviewer nickname, location, user ID and
   profile fields before storage (blueprint §12: no PII).
6. **Images:** the SFCC image path is robots-disallowed. If PDP image URLs point to a separate CDN
   host, check that host's robots before fetching; otherwise this needs an owner decision. Dedupe
   by SHA-256 (§6.5).
7. **Block detection:** `server: AkamaiGHost` + 403 + body `Access Denied` / `errors.edgesuite.net`
   reference (see `samples/sephora_akamai_403.html`). On block, back off. Affected listings are
   marked `blocked`/`not_observed` and the run is marked `partial` (blueprint §15.3). A blocked or
   partial run must **never** produce stock-outs or removals.
8. **Gate before coding PR6:** the two owner decisions (§9), then the supervised ladder test,
   replacing every ◐ above with ✅/✗ from real fixtures.

## 9. Next steps (in order)

Pending owner decisions (nothing below runs until they are answered): **(a)** ladder probe method
(Cloud Run job or otherwise), **(b)** whether robots-disallowed paths may be used (§4).

1. Probe by the approved method: ~20 requests total, 1 req/s, **UAE first** (`/ae-en/` home, 3 PDPs
   from an en-AE product sitemap, 1 category slug page, 1 image URL), then the same for `/sa-en/`.
   `/api/v1` calls only if (b) allows them.
2. Count distinct products/variants in all SA and AE sitemaps to close §3.
3. Read and record the site's terms of use (SRC-01).
4. Only then, if everything free fails: a final Proxy Decision Report and the owner's purchase decision.
