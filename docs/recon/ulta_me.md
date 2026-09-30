# Recon: Ulta Beauty Middle East (Alshaya franchise)

- Status: **partial**. Storefronts identified by desk research only; one direct request, which was
  blocked; ladder not yet run.
- Date: 2026-09-30
- Requirement IDs: SRC-01 (access method, rights basis, field contract), SRC-03 (discovery and count
  reconciliation), SRC-08 (permitted access; deviation recorded in ADR-0003), SRC-14 (offline imports
  for Ulta KSA), SCP-02 / SCP-08 (coverage register; Ulta KSA `pending`), SCP-11 (decision log).
- Blueprint refs: §1.1, §1.2 (discovery item), §1.4, §13; ADR-0003, ADR-0004
- **Owner decision (2026-09-30, relayed by the program coordinator): pilot market = UAE.** In the
  owner's words: "do UAE if KSA doesn't work". The Ulta ↔ Sephora head-to-head therefore runs on
  UAE (`ulta.ae` vs Sephora `en-AE`/`ar-AE`). Ulta KSA stays `pending` (SCP-02/SCP-08). This still
  has to be entered in the decision log (SCP-11) and blueprint §1.2 in a follow-up.
- **Rights basis / terms of use (SRC-01):** public, logged-out catalogue pages only. No account,
  cart or checkout. Neither site's terms of use nor its `robots.txt` has been read, because both were
  blocked or not requested (§3). They must be read and recorded before any connector goes live.

Every statement below is labelled **verified** (we saw it) or **inferred** (a reasonable reading of
what we saw, still to be confirmed).

## 1. Storefronts (inferred from desk research)

The blueprint assumed there was no confirmed Ulta ME storefront. Web search and press releases
**indicate** two storefronts run by Alshaya, plus an app (**inferred**). Neither storefront has
been verified by a successful request: `ulta.ae` returned a Cloudflare block (§3), and
`ulta.com.kw` was never requested.

| Market | Online storefront (inferred) | App | Physical stores | Evidence |
|---|---|---|---|---|
| Kuwait | `www.ulta.com.kw/en/` (search listing: "over 25,000 products") | Ulta Beauty Middle East | The Avenues (Nov 2025) | web search only; **not requested** |
| UAE | `www.ulta.ae/en/` (same claim) | same app | Mall of the Emirates (Jan 2026), Dubai Mall (Mar 2026) | web search; the domain answers but is Cloudflare-blocked from our egress (§3), so the content is unseen |
| KSA | **none found** (`ulta.sa` / `ulta.com.sa` not indexed) | app coverage of KSA unknown | Red Sea Mall, Jeddah (2026) | web search |

App store listings: "Ulta Beauty Middle East", developer **M.H. Alshaya Co. W.L.L.**, Android
`com.ub.mena`, iOS id `6748057305`. The listings say it offers shopping with express delivery and
in-store pickup.

Third-party listings on noon (`noon.com/uae-en/ulta_beauty/`, `/saudi-en/ulta_beauty/`), amazon.sa and
ubuy are Ulta-brand products resold by marketplaces. They are **not** Ulta ME's own offer and cannot
be used as Ulta ME prices.

**Recommendation (for the owner to confirm into blueprint §1.2):** case **(c) mix**. That means a
full connector for **UAE** (and Kuwait if wanted), and for **KSA**, Alshaya price files or store
audits (SRC-14) until a KSA storefront appears. Ulta KSA stays `pending` with the reason "no KSA
storefront; store-only" and is retried weekly. Whether to ask Alshaya for KSA price files is a
**pending owner decision**. The UAE part is already decided (header).

## 2. Platform (inferred, to confirm)

Alshaya's multi-brand e-commerce estate (for example its Bath & Body Works, H&M and Victoria's Secret
Gulf sites) has historically run on a shared stack: a **Drupal** front end, a commerce back end
and **Algolia** search, with public, search-only Algolia keys in page config. `ulta.ae` /
`ulta.com.kw` may be on the same stack. If so, an Algolia index could hold the full catalogue
(products, variants, prices, special prices, stock flags, images, category paths) as JSON.
**Unverified**: the homepage could not be read from our egress (see §3).

Caveats if Algolia is found:
- Algolia's default `paginationLimitedTo` is **1,000 hits per query in total**, not per page. Search-only
  keys usually lack the `browse` ACL. Full enumeration of ~25k records therefore needs **facet
  partitioning** (category × brand, split further by price band where a partition exceeds 1,000
  hits). It cannot be done by paging one query.
- Querying Algolia directly means calling an internal API on a third-party host. Treat it like
  Sephora's BFF: use it **only if the owner approves** it as an access method (SRC-01/SRC-08, SCP-11).
- App IDs and keys are read at runtime from page config and are **never committed**.

## 3. What was tried

| # | Rung | Request | Result |
|---|---|---|---|
| 1 | 0 | `curl` + desktop Chrome UA → `https://www.ulta.ae/robots.txt` | **403** Cloudflare |
| 2 | 0 | same → `https://www.ulta.ae/en/` | **403** Cloudflare "Sorry, you have been blocked – You are unable to access ulta.ae" (4,544 B; `server: cloudflare`, `__cf_bm` cookie) |

That is a Cloudflare **WAF block page**, not a JS/Turnstile challenge (verified from the body). Even
`robots.txt` is blocked, which points to an IP/ASN or geo rule against our IN datacenter egress
rather than fingerprinting (**inferred**). Rungs 1–4 were not run in this session (same
tool-permission limit as the Sephora recon; see `sephora_me.md` §2). How the probe is run is a
pending owner decision (§8). Sample: `samples/ulta_ae_cloudflare_block_head.html`. `ulta.com.kw`
was not requested.

## 4. Field-availability matrix (expected, all unverified)

| Field | Algolia index (if present; needs owner approval) | PDP HTML / JSON-LD | Sitemap | Alshaya price file (SRC-14) | Store audit (SRC-14) |
|---|---|---|---|---|---|
| Product / variant IDs, SKU | ◐ | ◐ | ◐ URL only | ◐ | ✗ |
| Brand, name, category | ◐ | ◐ | ✗ | ◐ | ◐ |
| Price, original price | ◐ | ◐ | ✗ | ◐ | ◐ |
| Promotions | ◐ (labels) | ◐ | ✗ | ? | ◐ |
| Stock | ◐ (in-stock flag) | ◐ | ✗ | ✗ | ◐ (shelf) |
| Content | ◐ (short) | ◐ (full) | ✗ | ✗ | ✗ |
| Ratings / reviews | ? | ? | ✗ | ✗ | ✗ |
| Images | ◐ URLs | ◐ URLs | ✗ | ✗ | photo |
| EN + AR | ◐ (per-locale index) | ◐ | ◐ | ? | ✗ |

## 5. Fallback (for KSA, or if UAE stays blocked)

1. **Brand list:** build the "brands Ulta stocks" list from the Ulta ME app/storefront brand pages
   once they can be reached. Until then, seed it from the launch coverage (300+ brands, for example
   Ôrəbella, Morphe, Polite Society, LolaVie, Sacheu, Kiko Milano, Peter Thomas Roth, Bex Beauty,
   Asteri, Nadine Njeim Beauty). Sephora is then benchmarked on those brands.
2. **Alshaya price files / store audits (SRC-14):** the importable offline channel (§1.1). This is the
   only KSA route until a KSA storefront exists. Requesting them is a pending owner decision.
3. **Ulta US (`ulta.com`)** as a reference catalogue labelled **non-ME**. It is for matching and
   content only, never for ME price analytics.

## 6. Volume estimate (UAE, planning numbers)

~25k products are claimed (the figure probably counts variants).

- **Algolia (only if approved):** partitions of ≤1,000 hits at `hitsPerPage` 1,000. At least 25
  partitions for 25k records, and realistically **~100–300** because brands and categories are
  unevenly sized. That is **~100–300 calls per locale per day** for full price/stock. At ~3 KB per
  record, transfer is ≈ 75 MB per locale per day, or ≈ 0.15 GB/day for EN + AR.
- **PDP HTML (baseline, if robots allows the PDP routes):** ~10–25k requests/day, ~3–7 h at 1 req/s.
  That is too slow for a daily full run, so it has to be tiered as in `sephora_me.md` §6.1 Option B.
  Weekly content for 2 locales: ~20–50k PDP requests.
- Kuwait roughly doubles this if added.

## 7. Proxy Decision Report (provisional)

Not requested. Free rungs are untested. Rung 4 (GCC egress) is the likely fix for an IP/geo-based
Cloudflare block. If a proxy is ever needed (blueprint §13 proxy line: **$10–30/month**):

| Scenario | GB/month | At $3–8/GB | vs. budget line |
|---|---|---|---|
| Algolia only (needs owner approval), EN + AR daily | ~4.5 | ~$14–36 | fits at the low end; **exceeds** at the upper price |
| PDP HTML | ~60–100 | ~$180–800 | **exceeds**, not viable |

## 8. Next steps

Pending owner decisions (nothing below runs until they are answered): **(a)** ladder probe method
(Cloud Run job or otherwise), **(b)** Alshaya price files for Ulta KSA, **(c)** whether Algolia may
be used if it is found (§2).

1. By the approved method, one probe of `ulta.ae` `robots.txt`, home and one PLP. If readable,
   record robots and terms, and look for sitemaps and any search configuration.
   A one-off Cloud Run job in `me-central1`/`me-central2` would cost cents, but it **requires owner
   approval before creation** (blueprint §13). A recurring daily job is costed in `sephora_me.md` §8.1
   (≈ $5–8/month, unverified).
2. Same probe against `ulta.com.kw`, if Kuwait is wanted.
3. Record the UAE pilot decision in the decision log (SCP-11), blueprint §1.2 and the coverage register.
4. If the owner approves (b): ask Alshaya for price files for Ulta KSA (Red Sea Mall).

## Sources

- Ulta Beauty IR, first ME store (Kuwait): https://www.ulta.com/investor/news-events/press-releases/detail/218/ulta-beauty-expands-international-footprint-with-first
- Ulta Beauty IR, UAE entry: https://www.ulta.com/investor/news-events/press-releases/detail/221/ulta-beauty-to-enter-the-uae-at-mall-of-the-emirates-as
- Alshaya news: https://www.alshaya.com/en/media-centre/alshaya-news/ulta-beauty-expands-international-footprint-with-first-middle-east-store-in-kuwait/
- Storefronts (not visited successfully): https://www.ulta.com.kw/en/ · https://www.ulta.ae/en/
- App: https://play.google.com/store/apps/details?id=com.ub.mena · https://apps.apple.com/am/app/ulta-beauty-middle-east/id6748057305
- Brand mix: https://beautymatter.com/articles/ulta-beauty-makes-its-middle-east-debut-in-kuwait
