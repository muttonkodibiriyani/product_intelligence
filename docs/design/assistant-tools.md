# Ryzan AI Assistant — tools ↔ `/api/v1` endpoints

Each tool is a read-only client of one `/api/v1` endpoint (design doc `ai-assistant.md` §4). The
five aggregate tools are thin views over sections of `/summary`, citing its envelope cohort. Tools
are defined in code (`apps/assistant/src/tools/definitions.ts`) and never generated at runtime.
`apps/assistant/test/endpoint-map.test.ts` fails when a new `/api/v1` operation has neither a
tool nor an exclusion below, or when this page misses a tool or an operation.

Contract: `docs/contracts/pi-api.openapi.json` (API 1.21.0). All operations are GET.

## Tools

| Tool | Endpoint | What it returns |
| --- | --- | --- |
| `search_products` | `/products` | Product cards with the latest price per retailer; the gap for two retailers. Each card's match list becomes one `unconfirmedMatch` flag (true when any edge is not exact and approved/locked, or several retailers are priced with no edge; such prices are not compared), match details come from `get_product`, and a page is at most 15 cards, so a worst-case page fits the result size cap |
| `price_per_unit` | `/products` | Price per 1 ml or 1 g (listed price / published size, exact decimals), ranked; products with no size or price are counted as excluded |
| `get_product` | `/products/{product_id}` | Offers per retailer, pair gaps, match details, evidence links |
| `price_history` | `/products/{product_id}/history` | Per-retailer price, regular price and availability per collection date |
| `compare` | `/compare` | Exact same-size pair gaps between two retailers, with summaries |
| `price_suggestions` | `/price-suggestions` | Rule-based (not ML) price cuts so a subject retailer beats or matches a rival on exact reviewed same-size pairs, with the outcome or no-suggestion reason per row (API 1.14.0) |
| `category_compare` | `/category-compare` | Per-category price stats for two retailers' full catalogues and the gap between medians (no product matching); drops the `unmapped` breadcrumb list, keeping its count |
| `index_trend` | `/index` | Fixed-basket price index between two retailers over time |
| `promotions` | `/promotions` | Promotion share per retailer and promoted products |
| `assortment_gaps` | `/assortment-gaps` | Products at one retailer with no match at another |
| `launches` | `/launches` | Products first seen since a date |
| `reviews_summary` | `/reviews-summary` | Rating count and weighted average per retailer |
| `availability` | `/availability` | Stock-state counts and out-of-stock / low-stock shares per retailer |
| `coverage_status` | `/coverage` | Retailer ids, coverage status, counts and freshness (latest data date) |
| `price_ladder` | `/summary` (`ladder`) | Per-category min, p25, median, p75 and max price |
| `price_distribution` | `/summary` (`priceHist`, `medianPrice`, `priced`) | Price histogram and median |
| `brand_positioning` | `/summary` (`brandPrice`) | Per-brand priced count and median price |
| `category_mix` | `/summary` (`categoryMix`, `products`) | Products per category path |
| `assortment_breadth` | `/summary` (`products`, `priced`, `brands`, `categories`) | Catalogue counts |

Every `/summary` view also keeps `retailer`, `asOf`, `currency` and `freshness`. A field that
`/summary` withheld (null, with its section in `withheld`) makes the view `not_enough_data` with
the service's reason, so it is never read as zero. Freshness has no tool of its own: it folds
into `coverage_status` (and every `/summary` view carries it).

The other `/summary` sections (`promoDepth`, `promoSharePct`, `topDiscounts`, `ratingPrice`) have
no view yet: promotions are answered by `promotions`, and ratings by `reviews_summary`.

## Excluded endpoints

| Endpoint | Why no tool |
| --- | --- |
| `/export/assortment-gaps`, `/export/compare`, `/export/coverage`, `/export/index`, `/export/products`, `/export/promotions` | File downloads (CSV/XLSX) of reads the tools already make; not an answer |
| `/admin/products/{product_id}` | Admin evidence view; the assistant serves viewers with the same tools |
| `/matches` | The match review queue (an operator workflow); `compare` covers approved matches |
| `/meta` | Page bootstrap (attribute sets, labels, dates); `coverage_status` covers retailers and freshness |
| `/insights` | Insights page aggregates (brand price policy, size ladders) built from `compare`'s counted pairs; `compare` answers the same questions. A tool can follow once the page settles |
| `/catalogues/{retailer}`, `/catalogues/{retailer}/skus/{sku}` | SKU galleries and identity links for the product page (display only); no prices or counts to answer with (coordinator ruling 2026-10-01) |

## Planned

- When the Deep Coder adds category / brand / price-band / rating-band filters to `/summary`, the
  five views gain those inputs, still 1:1 over its sections.
- DC's `/price-position` and `/price-suggestion` get two tools, `price_position` and `price_suggestion` (latest only), in a PR after they land.
