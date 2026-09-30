# Recon: Ulta Beauty Middle East (Alshaya franchise)

- Status: **partial**. Storefronts identified by desk research; direct access tried once (blocked); ladder not yet run.
- Date: 2026-09-30
- Blueprint refs: §1.1, §1.2 (discovery item), §1.4; ADR-0003, ADR-0004

## 1. Headline: blueprint §1.2 case is (c), not (b)

The blueprint assumed there was no confirmed Ulta ME storefront. **There are two**, both run by
Alshaya, plus an app:

| Market | Online storefront | App | Physical stores | Evidence |
|---|---|---|---|---|
| Kuwait | **`www.ulta.com.kw/en/`** (search listing: "over 25,000 products") | Ulta Beauty Middle East | The Avenues (Nov 2025) | web search, 2026-09-30 |
| UAE | **`www.ulta.ae/en/`** (same claim) | same app | Mall of the Emirates (Jan 2026), Dubai Mall (Mar 2026) | web search + direct request (Cloudflare, see §3) |
| KSA | **none found** (`ulta.sa` / `ulta.com.sa` not indexed) | app coverage of KSA unknown | Red Sea Mall, Jeddah (2026) | web search |

App: "Ulta Beauty Middle East", developer **M.H. Alshaya Co. W.L.L.**, Android `com.ub.mena`, iOS
id `6748057305`. It offers shopping with express delivery and in-store pickup.

Third-party listings on noon (`noon.com/uae-en/ulta_beauty/`, `/saudi-en/ulta_beauty/`), amazon.sa and
ubuy are Ulta-brand products resold by marketplaces. They are **not** Ulta ME's own offer and not
usable as Ulta ME prices.

So §1.2 resolves as **(c) mix**: full connector for **UAE** (and Kuwait if wanted), and Alshaya price
files or store audits for **KSA** until a KSA storefront appears. By ADR-0004, the Ulta ↔ Sephora
head-to-head should run on **UAE** first (Ulta `ulta.ae` vs Sephora `en-AE`/`ar-AE`). KSA stays
`pending` for Ulta with reason "no KSA storefront; store-only", retried weekly.

## 2. Platform (inferred, to confirm)

Alshaya's multi-brand e-commerce estate (for example its Bath & Body Works, H&M and Victoria's Secret
Gulf sites) has historically run on a shared stack with a **Drupal** front end, a commerce back end
and **Algolia** search, with public, search-only Algolia keys in page config. If `ulta.ae` /
`ulta.com.kw` are on the same stack, an Algolia index would give the full catalogue (products,
variants, prices, special prices, stock flags, images, category paths) as JSON in a few hundred
paged calls. That would be the best rung-0 source. **Unverified**: the homepage was not readable
from our egress (see §3).

## 3. What was tried

| # | Rung | Request | Result |
|---|---|---|---|
| 1 | 0 | `curl` + desktop Chrome UA → `https://www.ulta.ae/robots.txt` | **403** Cloudflare |
| 2 | 0 | same → `https://www.ulta.ae/en/` | **403** Cloudflare "Sorry, you have been blocked – You are unable to access ulta.ae" (4,544 B; `server: cloudflare`, `__cf_bm` cookie) |

That is a Cloudflare **WAF block page**, not a JS/Turnstile challenge. Even `robots.txt` is blocked,
which points to an IP/ASN or geo rule against our IN datacenter egress rather than fingerprinting
(**inferred**). Rung 4 (Cloud Run `me-central1`/`me-central2`) is therefore the most promising single
test, ahead of stealth browsers. Rungs 1–4 were not run in this session (same tool-permission
limit as the Sephora recon; see `sephora_me.md` §2). Sample:
`samples/ulta_ae_cloudflare_block_head.html`. `ulta.com.kw` was not requested.

## 4. Field-availability matrix (expected, all unverified)

| Field | Algolia index (if present) | PDP HTML / JSON-LD | Sitemap | Alshaya price file | Store audit |
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
   once reachable. Until then, use the launch coverage (300+ brands, for example Ôrəbella, Morphe,
   Polite Society, LolaVie, Sacheu, Kiko Milano, Peter Thomas Roth, Bex Beauty, Asteri, Nadine Njeim
   Beauty) as a seed. Sephora is then benchmarked on those brands.
2. **Alshaya price files / store audits:** the importable offline channel (§1.1). This is the only
   KSA route until a KSA storefront exists.
3. **Ulta US (`ulta.com`)** as a reference catalogue labelled **non-ME**, for matching and
   content only, never for ME price analytics.

## 6. Volume estimate (UAE, planning numbers)

~25k products claimed (likely counts variants). With Algolia at 1,000 hits/page: ~30–60 calls per
locale per day for full price/stock, and ~0.05 GB/day. With PDP HTML only: ~10–25k requests/day,
~3–7 h at 1 req/s, which is too slow for a daily run, so the grid/Algolia path matters. Weekly content
×2 locales: ~20–50k PDP requests. Kuwait roughly doubles this if added.

## 7. Proxy Decision Report (provisional)

Not requested yet. Free rungs are untested and rung 4 (GCC egress) is the likely fix for an
IP/geo-based Cloudflare block. If a proxy is ever needed: Algolia/JSON-only traffic ≈ **2–5 GB/month**
(≈ $6–40 at $3–8/GB). HTML-only ≈ 60–100 GB/month is not viable within the budget.

## 8. Next steps

1. From a Cloud Run job in `me-central1` and `me-central2`, run a single probe of `ulta.ae`
   `robots.txt`, home and one PLP. If readable, look for Algolia app ID / index names in page config,
   sitemaps and the PDP data layer.
2. Same probe against `ulta.com.kw`.
3. Decide the Ulta pilot market (recommended: UAE) and update blueprint §1.2 and the coverage register.
4. Ask Alshaya for price files for Ulta KSA (Red Sea Mall) to cover KSA.

## Sources

- Ulta Beauty IR, first ME store (Kuwait): https://www.ulta.com/investor/news-events/press-releases/detail/218/ulta-beauty-expands-international-footprint-with-first
- Ulta Beauty IR, UAE entry: https://www.ulta.com/investor/news-events/press-releases/detail/221/ulta-beauty-to-enter-the-uae-at-mall-of-the-emirates-as
- Alshaya news: https://www.alshaya.com/en/media-centre/alshaya-news/ulta-beauty-expands-international-footprint-with-first-middle-east-store-in-kuwait/
- Storefronts: https://www.ulta.com.kw/en/ · https://www.ulta.ae/en/
- App: https://play.google.com/store/apps/details?id=com.ub.mena · https://apps.apple.com/am/app/ulta-beauty-middle-east/id6748057305
- Brand mix: https://beautymatter.com/articles/ulta-beauty-makes-its-middle-east-debut-in-kuwait
