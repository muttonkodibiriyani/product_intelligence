# Recon: Sephora Middle East (`www.sephora.me`)

- Status: **partial**. Rung 0 done; rungs 1–4 installed but **not executed** (see §2).
- Date: 2026-09-30
- Blueprint refs: §1.1, §1.4, §6; ADR-0003 (ladder), ADR-0004 (KSA → UAE fallback)
- Egress used: our server, `AS134926 Micro Hosting Private Limited`, Bengaluru (IN), datacenter IP.

Every statement below is labelled **verified** (we saw it) or **inferred** (a reasonable reading of
what we saw, still to be confirmed).

## 1. Summary

| Market / locale | Discovery (sitemaps) | Product / category pages | Working rung |
|---|---|---|---|
| KSA `en-SA`, `ar-SA` | **Open at rung 0** with a browser User-Agent (verified) | **403 Akamai** at rung 0 (verified) | none yet; rungs 1–4 not run |
| UAE `en-AE`, `ar-AE` | **Open at rung 0** (verified) | Same Akamai edge; assumed 403 (not tested separately) | none yet |

Discovery is free and works. Product data is behind Akamai Bot Manager/edge rules from our egress.
Whether a free rung beats it is **still unknown**. The next step (§8) is a supervised run of
rungs 1–4, with rung 4 from Cloud Run `me-central2` (Dammam, KSA) as the most informative single test.

## 2. What was tried

| # | Rung | Request | Result |
|---|---|---|---|
| 1 | 0 | `curl` default UA → `/sa-en/`, `/robots.txt`, `/sitemap.xml` | **403** `AkamaiGHost`, 382 B "Access Denied" for all three |
| 2 | 0 | `curl` + desktop Chrome 140 UA + `Accept-Language` → `/robots.txt` | **200**, 1,645 B |
| 3 | 0 | same → `/sitemap.xml` | **200**, 11,801 B (index; see §3) |
| 4 | 0 | same → `/sa-en/` (home) | **403** Akamai, 382 B |
| 5 | 0 | bulk fetch of the 60 SA + en-AE child sitemaps at ~1 req/s | **not run**: blocked by this session's tool-permission policy |
| 6 | 1–4 | curl_cffi, Playwright (headless/Xvfb), Scrapling/Camoufox/patchright, Cloud Run egress | **not run**: same policy; tools installed in a throwaway venv only |

Rows 1–4 show that Akamai rejects the bare `curl` UA on every path, but lets a browser UA through on
sitemaps/robots only. HTML routes need more than a UA string. That fits an Akamai Bot Manager policy
scoring TLS/HTTP2 fingerprint and IP reputation (datacenter ASN, non-GCC geo) on page routes
(**inferred**). This is what rungs 1 (TLS impersonation) and 4 (GCC egress) are designed to separate.

No proxy, Tor, login, cart or checkout was used. Total requests to `sephora.me`: 7.

**Why rungs 1–4 were not run:** the agent's permission layer classified automated bulk fetching and
bot-evasion against this third-party site as disallowed for an unattended session. The owner has
approved the ladder in ADR-0003, but the ladder has to be run by a session the operator explicitly
permits (or by the Cloud Run job itself). It was not worked around.

## 3. Discovery (rung 0, verified)

`/sitemap.xml` is an index of **locale-specific slug sitemaps** plus an app-routes file:

| Locale | Product sitemap files | Category sitemap files |
|---|---|---|
| `en-SA` | 8 (`productSlugsCO-0..7.xml`) | 2 |
| `ar-SA` | 8 | 2 |
| `en-AE` | 40 (`productSlugsCO-0..39.xml`) | 10 |
| `ar-AE` | 40 | 10 |
| — | `sitemap-app-routes.xml` | |

Counts from the coordinator's earlier pass (not re-counted here): `en-SA` ≈ **32.9k** product URLs,
`en-AE` ≈ **170.6k** entries.

**Reconciliation (open):** the 5× gap between SA and AE is too large to be assortment alone. Likely
causes, still to check: AE entries include `<image:image>` children or `hreflang` alternates counted
as entries; AE lists one URL per variant/shade and SA one per product; or AE still carries
discontinued slugs. The connector's trial run (§6.1 step 5) must count **distinct product IDs** and
**distinct variant IDs** per locale, not `<loc>`/`<url>` elements. Sample: `samples/sephora_sitemap_index_head.xml`.

## 4. Platform signals (inferred from `robots.txt`)

Sample: `samples/sephora_robots.txt`.

| Signal | Reading |
|---|---|
| `/on/demandware.store/*`, `Product-Show`, `Product-Variation?pid=`, `Search-Show?cgid=`, `cart?dwcont`, `mastercatalog_sephora` | **Salesforce Commerce Cloud (SFCC)** back end, master catalogue `mastercatalog_sephora`. Variants addressed by `pid` |
| `productSlugs`/`categorySlugs` sitemaps, `sitemap-app-routes.xml`, `Disallow: */api/v1*` | Probably a **headless front end** (SFCC Composable Storefront/PWA or custom) calling its own BFF at `/{locale}/api/v1/...`. That BFF is the richest rung-0 JSON candidate |
| `bvrrp=`, `bvstate=`, `bvroute=Reviews`, `rev=BVSpotlights` | Reviews and ratings are served by **Bazaarvoice** |
| `Disallow: /catalogs/mastercatalog_sephora/default/images` | Product images served from SFCC's static image path on `www.sephora.me` (maybe also a DIS/CDN host). Whether they are reachable outside Akamai page rules is untested |
| `search?q=`, `?sz=`, `prefn/prefv`, `pmin/pmax`, `srule` disallowed | Search/listing paging exists (`sz` = page size, `srule` = sort rule), usable for daily price sweeps |

**Robots note for the owner:** `robots.txt` disallows `*/api/v1*`, `/on/demandware.store/*`,
`Product-Variation` and the search/listing parameters. The richest JSON sources are therefore
robots-disallowed. ADR-0003 records the owner's choice of coverage over SRC-08. Robots compliance is
a separate line, and it should be decided explicitly and written into the traceability matrix
before PR6 uses those paths.

## 5. Field-availability matrix

Legend: ✅ verified · ◐ expected (inferred, unverified) · ✗ not available · ? unknown.
"Rung" is the lowest rung expected to deliver the source, not a tested result. Only the sitemap
row has actually been observed.

| Field | Sitemap (r0) | PDP HTML: JSON-LD / embedded state (r1–3) | BFF `/api/v1` JSON (r1–3) | Listing/search grid (r1–3) | Bazaarvoice API | Image host |
|---|---|---|---|---|---|---|
| Product URL / slug | ✅ | ◐ | ◐ | ◐ | ✗ | ✗ |
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
| Image bytes | ✗ | ✗ | ✗ | ✗ | ✗ | ? (open CDN untested) |
| Search rank | ✗ | ✗ | ◐ | ◐ | ✗ | ✗ |

## 6. Volume estimate (planning numbers, to be replaced after the trial run)

Assumptions: `en-SA` 32.9k sitemap URLs ≈ ~10k products / ~33k variants; one PDP returns all
variants; listing grid pages hold 48 products; HTML PDP ≈ 400 KB, JSON ≈ 20 KB, grid page ≈ 150 KB.

| Job | Requests per market-locale | At 1 req/s | Transfer |
|---|---|---|---|
| Daily price/stock/promo via listing grid | ~250–400 | ~5–7 min | ~50 MB |
| Daily price/stock via PDP/BFF (variant-accurate) | ~10k | ~2.8 h | 0.2 GB (JSON) / 4 GB (HTML) |
| Weekly discovery (sitemaps) | ~12 (SA) / ~52 (AE) | < 1 min | ~20 MB |
| Weekly content (PDP, EN + AR) | ~20k | ~5.6 h | 0.4 GB (JSON) / 8 GB (HTML) |
| Weekly reviews (Bazaarvoice, incremental) | ~1–3k | < 1 h | ~0.1 GB |
| Images (first sight; then on change only) | ~50k once, few k/week | — | ~10 GB once |

**KSA only, recommended mix** (daily grid sweep + daily PDP refresh on changed/at-risk items only +
weekly full PDP): ≈ **12–15k requests/day**, **~120k/week**, **~2–4 GB/week** if JSON is reachable,
~20–30 GB/week if only HTML is. UAE adds ~1–1.5× on top.

## 7. Proxy Decision Report (provisional)

Rung 5 is **not** requested yet. Rungs 1–4 have not been run, and ADR-0003 requires them first. If
the supervised run fails on all of them, these are the numbers for the owner:

| Scenario | GB/month through proxy | At $3–8/GB residential |
|---|---|---|
| JSON only (BFF/embedded), KSA, recommended mix | ~8–15 | **~$25–120** |
| Listing grid only daily + JSON weekly (minimum viable) | ~3–6 | **~$10–50** |
| HTML PDPs through proxy | ~80–120 | $250+: not viable within the $25 budget |

Keeping to the budget requires: proxy only for the JSON/grid calls, images and sitemaps direct (both
appear open or are untested), ETag/`If-Modified-Since`, and PDP refresh only on changed items.

## 8. Recommendation for PR6 (Sephora connector) on Firebase / Google Cloud

Project `productintelligence-beeb3`.

1. **Runtime:** one **Cloud Run job** per source context (`sephora_me × {SA, AE} × {en, ar}`),
   triggered by **Cloud Scheduler** (daily price, weekly discovery/content, weekly reviews). Region
   **`me-central2` (Dammam)** for KSA and `me-central1` (Doha) as an alternative. Raw evidence goes
   to Cloud Storage, parsed records to Cloud SQL. Secrets such as a future proxy credential go in
   Secret Manager, never in the repo.
2. **`discover()`:** sitemap index → locale child sitemaps (rung 0, verified open with a browser UA).
   Use `lastmod` where present to limit weekly work. Also walk `categorySlugs` for category tree and rank.
3. **`fetch()` ladder order:** try rung 1 (curl_cffi `chrome` impersonation, session and cookie reuse)
   first, from `me-central2`. Then Camoufox/patchright with a persistent profile to obtain Akamai
   `_abck`/`bm_sz` cookies, and reuse those cookies in curl_cffi for the bulk JSON calls. That is the
   cheapest stable pattern against Akamai when it works. Record the working rung per context (ADR-0003).
4. **Source preference:** BFF `/api/v1` product/search JSON (subject to the robots decision in §4) >
   PDP embedded state + JSON-LD > listing grid. Variant walking uses the `pid` list from the
   product's variation model, not `Product-Variation` calls one by one.
5. **Reviews:** Bazaarvoice display API with the public passkey embedded in the PDP. Full pass
   once, then incremental by `SubmissionTime`.
6. **Images:** fetch direct from the image host with no proxy, deduped by SHA-256 (§6.5).
7. **Block detection:** `server: AkamaiGHost` + 403 + body `Access Denied` / `errors.edgesuite.net`
   reference (see `samples/sephora_akamai_403.html`). On block, back off, climb one rung, and apply
   the ADR-0004 fallback if KSA stays blocked.
8. **Gate before coding PR6:** run the supervised ladder test (next steps) and replace every ◐ above
   with ✅/✗ from real fixtures.

## 9. Next steps (in order)

1. The operator runs (or grants permission for) the rung-1..3 probe from this server: ~20 requests total,
   1 req/s. Target: `/sa-en/` home, 3 PDPs from `productSlugsCO-0.xml`, 1 category, the matching
   `/api/v1` calls seen in the browser network log, and 1 image URL.
2. Run the same probe as a one-off Cloud Run job in `me-central2`, which covers rung 4 and GCC egress.
3. Count distinct products/variants in all SA and AE sitemaps to close §3.
4. Owner decides on robots-disallowed JSON paths (§4).
5. Only then, if everything free fails: a final Proxy Decision Report and the owner's purchase decision.
