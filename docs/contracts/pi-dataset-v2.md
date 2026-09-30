# `pi.dataset/v2`: the published dataset contract

`pi.dataset/v2` is the snapshot that producers publish and every consumer reads: the read API
(`docs/design/service-layer.md`), exports and, until they move to the API, the dashboard and the
assistant. It replaces `pi.dataset/v1`, whose two fixed retailer slots (`u`/`s`) and single
implied market can't carry more than one brand, market or retailer set (ADR-0007 §6).

| Artifact | Where |
|---|---|
| Models (the definition) | `packages/pi_dataset/src/pi_dataset/models.py` |
| JSON Schema, draft 2020-12 (generated; do not edit) | `docs/contracts/pi-dataset-v2.schema.json` |
| Validator library | `pi_dataset.load_dataset`, `pi_dataset.dump_dataset` |
| CLI | `uv run pi-dataset validate FILE...`, `pi-dataset schema`, `pi-dataset examples DIR` |
| Synthetic examples (generated; do not edit) | `docs/contracts/examples/*.json` |

CI fails if the committed schema or examples differ from what the library generates. To
regenerate:

```sh
uv run pi-dataset schema > docs/contracts/pi-dataset-v2.schema.json
uv run pi-dataset examples docs/contracts/examples
```

## Who uses what

- **Producers** (`demo_export`, later the pipeline) build a `pi_dataset.Dataset` and write it with
  `dump_dataset`. Building the model runs every rule below, so a producer can't write an invalid
  document.
- **The publisher** (`infra/scripts/publish_dataset.py`) calls `load_dataset(raw)` before
  uploading, and refuses on `DatasetError`.
- **Readers** (the API's `SnapshotSource`) call `load_dataset` on every new generation. An invalid
  document is never served.
- **`load_dataset` is strict:** it never coerces. `"12900"` is not an integer, `0` and `"false"`
  are not booleans, and `"test": "false"` is an error, not `false`. (Building models in Python
  is lax, as usual in pydantic, but the output of `dump_dataset` always passes the strict load.)
- **Non-Python consumers** can check shape with the JSON Schema. The schema can't express the
  cross-field rules, so only `load_dataset` is authoritative.

## Shape

```text
{ "schema": "pi.dataset/v2",
  "meta": { kind, cutoff, generatedAt, scope, vertical, markets[], retailers[], dates[],
            matchStage, capabilities, fields, producer, test },
  "products": [ { id, brand, name, category[], unit, offers{<retailer id>: Offer},
                  matches[], shades[], attributes{}, image } ],
  "notObserved": [ { retailer, start, end, categories, why } ] }
```

- **Wire names are camelCase**, Python names snake_case. Unknown keys are rejected everywhere.
- **Markets are data.** `meta.markets[]` lists each market's ISO 3166-1 `country`, ISO 4217
  `currency`, IANA `timeZone` and BCP 47 `locales`. Nothing in the contract assumes the Gulf, AED
  or Arabic.
- **Retailers are data.** `meta.retailers[].id` is the source-register key (ADR-0007 §2),
  `^[a-z][a-z0-9_]{1,62}$`. Offers are keyed by it; there are no fixed slots.
- **`status`** is `supported | partial | blocked | pending | retired`. Only a `supported`
  retailer can back an absence claim (an assortment gap, a removal, a launch).
- **`capabilities`** are all explicit booleans, and `fields` gives each field's status
  (`ok | partial | not_collected | not_published | parse_failure | blocked`). A consumer never
  infers a capability from a missing key.
- **`test: true`** marks synthetic data. `load_dataset` refuses it unless it is called with
  `allow_test=True`, so fixtures can't be published by accident.

## Numbers

- **Money** is `{"amount": "129.00", "minor": 12900, "currency": "AED"}`:
  - `amount` is a decimal string with **exactly** the currency's ISO 4217 exponent of decimals
    (`"3.250"` KWD, `"1500"` JPY);
  - money in a series (`price`, `regular`) is **positive**; a zero or negative price is a parse
    failure (reported in `meta.fields`), never a value;
  - `minor` is the same value in integer minor units and must agree with `amount`;
  - build it with `MoneyValue.of(Decimal, currency)`, which refuses inexact amounts.
- **No JSON floats, anywhere.** `load_dataset` rejects any JSON number with a fraction or
  exponent (and `NaN`/`Infinity`) before validation. Ratings, sizes and confidences are
  non-negative decimal strings matching `^\d+(\.\d+)?$`. Counts are integers.
- **Sizes** are positive (`value > 0`) and published as-is; the contract never converts units.
- **Ratings** carry their own `scale` (`"5"` for five stars, `"10"`, `"100"`), with
  `0 ≤ average ≤ scale`. The producer never rescales. A consumer compares averages only on the
  same scale, or after normalising `average / scale` itself.

## Cross-field rules (enforced by the models, not expressible in JSON Schema)

Every violation is reported, each with its path, in one `DatasetError`.

1. `meta.markets[].country` values are unique; `meta.retailers[].id` values are unique;
   `products[].id` values are unique.
2. Every retailer's `country` is one of `meta.markets`.
3. `meta.dates` is strictly increasing. **Dates are calendar dates in each market's `timeZone`**
   (a retailer's day is its market's day). For every market, the last date is on or before
   `meta.cutoff` converted to that market's zone: a `00:00Z` cutoff is still the previous day in
   New York. `meta.generatedAt` is on or after `meta.cutoff`.
4. Every offer is keyed by a retailer in `meta.retailers`.
5. **Currency:** an offer's `currency` is its retailer's market currency, and every money value
   in its series is in that currency. Cross-currency comparison is a consumer decision (the API
   reports `currency_mismatch`); the contract never converts.
6. **Series:** `price`, and `regular` and `availability` when present, have exactly one
   entry per `meta.dates`. `null` means not observed on that date: never zero, and never carried
   forward. That includes `availability`: `null` is the only spelling of "not observed", so the
   `not_observed` state is refused in a series. (`blocked`, `unknown` and the rest are allowed:
   they are observations of a kind.)
7. **Match edges:** `a < b` (canonical order), and both retailers have an offer on the product.
   There is at most one edge per pair. **Grouping is not identity:** offers under one product are
   grouped for presentation, and a pair is comparable only through its own edge. Nothing is
   inferred transitively: exact a–b and exact b–c edges say nothing about a–c (blueprint §8).
8. **`reviewState` is the database state verbatim:** `proposed | approved | rejected | locked`.
   The contract has no `accepted`, `auto_accepted` or `pending`; v1's `accepted` merged approved
   and locked edges. `decidedBy` (`human | auto`) is set exactly when the state isn't `proposed`
   (so a rejected edge has a decider too), and a `locked` edge is always `human`. `approved` may
   be `human` or `auto` (the auto-accept thresholds of blueprint §8.3). `confidence`, when
   present, is within 0..1.

   Producer mapping from `pi_db.match_edge`: `reviewState` = `review_state`; `decidedBy` = `null`
   for `proposed`, `human` when `reviewer` is set, else `auto` (the policy of `algo_version`);
   `confidence` = `score`. Reviewer identities are never published (SEC-06). Which states count in a metric is the metric
   layer's rule (service-layer design §7: `exact` and `approved | locked`), not the contract's.
9. `notObserved[].retailer` is a known retailer, and `start ≤ end`. `categories: null` means the
   whole catalogue.
10. **Credentials:** a document containing credential-like content (Algolia keys and headers,
    `api_key`/`app_id` keys) is refused outright, with the same patterns as the publisher's
    guard. The scan covers the whole document, scraped text (names, notes) included, and fails
    closed: a false positive blocks publication until the producer is fixed.

## Promotions

v1 carried a `promo` series, an integer percent derived from price and regular. v2 carries only
observations: `price` (the selling price) and `regular` (the stated regular price). Promotion
depth is derived by the metric layer (`pi_metrics`), which applies the rounding rule once.

## Early examples

An offer with `early: true` is a recon sample, not a collected observation. The retailer carries
`earlyExamples: true`. Consumers never count early offers in comparisons or coverage.

## Versioning

- Additive, optional fields keep `pi.dataset/v2`, and consumers ignore what they don't use.
  Validation is strict, so an older validator rejects a newer document: producers and the reader
  upgrade `pi_dataset` together.
- Removing or changing a field, or changing a rule, is `pi.dataset/v3` and needs an ADR.
- v1 → v2 for reading old snapshots is the API's read adapter (service-layer design §3), not part
  of this library.

## Not yet in the contract

- **Images:** `image` and `logo` exist, and are `null` until collection provides them. They are
  never invented.
- **FX:** there are no rates. If a rate source is approved, it arrives as a dated, sourced
  `meta.fx[]` (an additive change).
