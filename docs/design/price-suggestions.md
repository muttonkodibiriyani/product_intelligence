# Design: rule-based price position and suggestions

| | |
|---|---|
| Status | Proposed (this PR ships the rules and their tests; the API endpoint is a later Deep Coder PR) |
| Owner | AI Assistant Engineer |
| Task | M5 (01a0f475-acf2) |
| Code | `packages/pi_metrics/src/pi_metrics/pricing.py`, tests in `packages/pi_metrics/tests/test_pricing.py` |
| Requirements | ANL-01 (price positioning: percentiles, bands, rank), ANL-10 (unit value), ANL-16 / UAT-31 (no demand or causal claims). KPI-26..30: TODO, see §8 |
| Related | `docs/design/ml-layer.md` (the gated ML models), `docs/design/service-layer.md` §5 (envelope), §7 (metrics) |

## 1. What and why

Analysts want a defensible answer to two questions about an offer: *where does this price sit
against comparable products*, and *what price would put it in a chosen band*. This design
answers both with **rules over observed prices only**. Every output is labelled
**"rule-based, not ML"**.

The rules never estimate demand, volume, revenue, margin, elasticity or uplift. Public price data
cannot support those claims (ANL-16, UAT-31), and no output has a field that could hold one; a
test walks the JSON schemas and fails on such a field name. A suggestion is a price that meets
the guardrails, not a prediction of what the price will do.

## 2. Inputs

* **Subject:** a product id and a context id (a retailer's sole context has the retailer's id),
  on a date (default: the snapshot's last date). The subject's price is its collected offer's
  `price` on that date. No price (no offer, an early recon sample, unobserved, or a currency other
  than the market's) → `not_enough_data` / `not_in_scope`.
* **Peers** (parameter `peers`):
  * `market` (default): every collected, non-early offer priced on the date, in the subject's
    market and currency, in any context, **excluding the subject product itself**. A product
    sold in two contexts contributes two values. That is how the market sees it.
  * `competitors`: the same, without the subject's own retailer.
  * Today the live snapshot has one retailer (Sephora), so `competitors` is empty and only
    `market` gives bands.

## 3. Cohorts and basis

Two cohorts per subject:

| Cohort | Members |
|---|---|
| `category` | peers whose **leaf** category equals the subject's (`view.fold`: NFKC, casefold) |
| `brand` | peers of the subject's brand **within its top-level category**. A brand median across unrelated categories (a lipstick and a fragrance) says nothing. |

The **basis** of a cohort:

1. **Unit price** (`price / pack measure`): when the subject has a measure (`size.value` and
   `size.unit`) and at least `MIN_COHORT` = 5 peers share its folded unit. Peers without that
   unit are left out.
2. Otherwise **ticket price** over the peers of the same size (`view.same_size`, the ADR-0008 §1
   rule: equal measures, or comparable equal labels).
3. Peers that fit neither are counted in `excluded`, never converted or guessed. There is no
   unit conversion (ml vs fl oz); a different unit is a different basis.

Unit prices are `Decimal` quotients; the wire shows them at 4 dp and ticket prices at the
currency's exponent.

## 4. Bands

Per cohort: **p25, median, p75** by linear interpolation between closest ranks (Hyndman-Fan type
7, the same as `statistics.quantiles(method="inclusive")`; a property test checks that).

| Band | Rule |
|---|---|
| `entry` | value **<** p25 |
| `mid` | p25 ≤ value ≤ p75 (inclusive, so a band edge is reachable) |
| `premium` | value **>** p75 |

A cohort with fewer than `MIN_COHORT` = 5 members has no band: that cohort's `reason` is
`cohort_too_small`, and its thresholds are `null`. `vs_median_pct` is
`(value − median) / median × 100`.

## 5. Suggestion rule

Input: the subject, a **target band**, the cohort (default `category`), the guardrails and the
aim.

1. If the subject is already in the target band → `already_in_band`, no price.
2. **Aim point:** the nearest edge of the target band seen from the current band: p25 for
   `entry`, p75 for `premium`, and for `mid` p25 (coming from entry) or p75 (coming from
   premium). With `aim = median`, `mid` aims at the median instead.
3. **Direction** comes from the band order (entry < mid < premium), not from the point, because
   the point can equal the current price. A suggestion only moves towards the target band.
4. **Clamp:** at most `maxChangePct` (default 10 %) from the current price.
5. **Allowed prices** inside the clamp, with an allowed ending (default `.00`, `.50`, `x9.00`,
   e.g. 49.00 or 129.00; configurable) and exact at the currency's exponent.
6. **Choose:** prefer allowed prices that land in the target band; among them, the closest to
   the aim point (a tie goes to the lower price). If none lands, take the allowed price closest
   to the aim point and set `reachesBand = false` (`short_of_band`).
7. **Minimum:** if the chosen change is below `minChangePct` (default 1 %) → `below_min_change`,
   no price. If no allowed price exists in the clamp → `no_allowed_price`.

For a unit-price cohort the thresholds are scaled by the subject's pack measure, so rounding and
guardrails work on the ticket price the shopper sees.

Each step adds a **rationale** entry: `current_band`, `target` (band, aim, point), `clamped`,
`rounded` (price, endings), `reaches_band` or `short_of_band`, `below_min_change`,
`no_allowed_price`. Params are strings and numbers stay digits (service-layer §5), so the
assistant's answer verifier can match them.

## 6. Output shapes

Both are wrapped in the standard `Metric` (status, data, reason, cohort, caveats, asOf), so the
API envelope is mechanical (service-layer §5).

Real output over the synthetic metrics fixture (`p01` at `shop_a`, 90.00 AED for 50 ml):

```jsonc
// price_position(ds, "p01", "shop_a").data
{
  "label": "rule-based, not ML",
  "product": "p01", "context": "shop_a",
  "price": {"amount": "90.00", "minor": 9000, "currency": "AED"},
  "peers": "market",
  "cohorts": [
    {"label": "rule-based, not ML", "scope": "category", "key": "serum",
     "basis": "unit_price", "n": 24, "excluded": 0,
     "p25": "1.0000", "median": "1.2000", "p75": "2.0000", "value": "1.8000",
     "band": "mid", "vsMedianPct": "50.0", "reason": null},
    {"label": "rule-based, not ML", "scope": "brand", "key": "fixture beauty / skincare",
     "basis": "unit_price", "n": 18, "excluded": 0,
     "p25": "1.0000", "median": "1.0000", "p75": "1.5500", "value": "1.8000",
     "band": "premium", "vsMedianPct": "80.0", "reason": null}
  ]
}
// price_suggestion(ds, "p01", "shop_a", Band.PREMIUM).data
{
  "label": "rule-based, not ML",
  "product": "p01", "context": "shop_a", "cohort": "category", "targetBand": "premium",
  "current": {"amount": "90.00", "minor": 9000, "currency": "AED"},
  "suggested": {"amount": "99.00", "minor": 9900, "currency": "AED"},
  "changePct": "10.0", "reachesBand": false, "outcome": "suggested",
  "rationale": [
    {"code": "current_band", "params": {"band": "mid"}},
    {"code": "target", "params": {"band": "premium", "aim": "edge", "point": "100.00"}},
    {"code": "clamped", "params": {"maxChangePct": "10.0"}},
    {"code": "rounded", "params": {"price": "99.00", "endings": ".00,.50,x9.00"}},
    {"code": "short_of_band", "params": {"band": "premium"}}
  ],
  "guardrails": {"maxChangePct": "10", "minChangePct": "1", "endings": [".00", ".50", "x9.00"]}
}
```

Read: premium starts above 2.0000 AED/ml, i.e. above 100.00 for this 50 ml pack. The 10 % clamp
stops at 99.00, so the suggestion is honest that it falls short of the band.

`status` is `ok` whenever a band exists, including the outcomes `already_in_band`,
`below_min_change` and `no_allowed_price`, because those are answers. It is `not_enough_data`
with `not_applicable`, `not_in_scope` or `cohort_too_small` otherwise, and `data` is still
present with the price fields `null`.

## 7. Wiring later (Deep Coder)

This PR changes no shared enum, no `pi_api` route and no `metricVersion`. When the endpoint is
wired:

* Routes, e.g. `GET /v1/price-position?product=&context=&peers=` and
  `GET /v1/price-suggestion?...&target=&cohort=&aim=&maxChangePct=&minChangePct=&ending[]=`.
  Guardrail limits: `maxChangePct` in (0, 50], `minChangePct` ≥ 0, at least one ending; anything
  else is `422 invalid_request`.
* A `metricVersion` bump and a decision-log entry, as for every metric definition.
* OpenAPI: `rationale[].params` and the threshold strings are numbers-as-text, not source text.
  No field is retailer-authored except what `ProductCard` already carries. `key` is a folded
  category or brand, so it is source text (`x-pi-source-text`) for the assistant's sanitiser.
* The web card shows the label verbatim, the cohort n and basis, the rationale steps, and "not
  enough data" when there is no band. It never shows a projected sales or revenue figure.
* Admin and viewer see the same output; there are no admin-only fields.

## 8. Limits and open items

* **One retailer today:** with Sephora only, `competitors` has no peers and every band is a
  within-catalogue band. The label and the cohort description say "market offers", not
  "competitors".
* **No identity claim:** peers are cohort members, not matched items. Matching across
  retailers is the compare metric's job (exact edges only).
* **Promotions:** the observed selling price is used as is, so an offer on promotion is
  positioned at its promotional price. A `regular`-price basis is a possible later option.
* **KPI-26..30: TODO.** The requirements register is not in this public repository, so these KPIs
  are cited by ID only. The coordinator maps them; no register wording is copied here.

## 9. Pair suggestions: beat or match one rival (API 1.13.0)

Task 01a1005d adds a second, separate rule, `pi_metrics.pair_pricing`, served by
`GET /api/v1/price-suggestions?subject=&rival=` and the assistant tool `price_suggestions`. It
does not change the cohort rule above.

* **Pairs:** a product the subject offers counts only if compare's pair ladder accepts it:
  an exact match, approved or locked, same size, both priced, not early, in one currency. Every
  other product has a `reason` (`no_match`, `match_unreviewed`, `size_mismatch`, `unpriced`, ...).
* **Down only:** `aim` is `beat` (default; land strictly below the rival) or `match`. The cut is
  clamped to `maxChangePct` (default 10) and rounded to the guardrail endings, using
  `allowed_prices` from §5. An outcome is `suggested`, `already_competitive` (the gap is still
  returned as data), `below_min_change` or `no_allowed_price`. A clamped cut that stays above
  the rival has `reachesRival` false and the rationale `short_of_rival`.
* **Staleness:** `STALE_DAYS = 7`, echoed as `staleDays`. A side whose last collection is
  older is `stale_observation`. The route reads the observed dataset, never `latest`, which
  carries a stale source's last price forward.
* **One-off imports:** only the subject may be served from a one-off import. That is detected
  from the loaded data (`Loaded.imported`), never from a retailer id. Such a row's subject has
  `basis: imported_snapshot`, `observedOn` = the import date, and `ageDays`, which can be
  negative when the import postdates the crawl. The envelope carries the import caveat. The UI and
  the assistant say "<retailer> price from the <date> import". An imported rival is always
  `stale_observation`, and the envelope reason is `retailer_partial`.
* **Assistant:** the tool cites each row as a product token, quotes `suggested`, `changePct`
  and the rationale as given, and never claims a sales, revenue or margin effect. The refusal
  eval covers that.
* **Web view:** FE builds it after this merges (b3).
