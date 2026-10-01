# ADR-0008: Vertical profiles on the wire: portion as Size, channel as an offer dimension, per-vertical attribute sets

- Status: proposed (drafted by the Deep Coder on the coordinator's brief, 1 Oct 2026)
- Date: 2026-10-01
- Extends: ADR-0007 §4 (vertical profiles), §5 (matching) and §6 (dataset contract v2 and UI)
- Applies to: `pi_dataset` (`pi.dataset/v2`), `pi_metrics`, `pi_api`, the dashboard, and the
  `VerticalProfile` plugins of PR-E (task 01a0f47a-9d64)
- Carries over unchanged: ADR-0006 (access rulings), the service-layer metric ruling (one metric
  implementation in the service layer; Decimal money; counted pairs are exact and
  approved/locked; n ≥ 5; explicit `not_enough_data` states)

## Context
ADR-0007 decided **where** vertical data lives in the database:
- `variant.attributes jsonb` with a versioned per-vertical schema;
- `VerticalProfile` plugins;
- food portions in `size_value`/`size_unit` plus `attributes.portion_label`;
- channel in `source_context.channel`;
- branch in `location_context`.

It did not decide how that data reaches the published snapshot, the metric layer and the API.
The serving stack that has landed since then is beauty-shaped:

- **Size.** `Size` is `{value, unit}`, both required. A food item published only as "Medium" or
  "Large" has no value, so it would be `size: null`. Every food pair would then be excluded as
  `size_unknown`, and a burger chain could never show a counted comparison.
- **Channel.** `Product.offers` is keyed by retailer id, so there is exactly one offer per
  retailer. A restaurant brand priced differently on delivery, on pickup and per branch can't be
  represented without picking one price and dropping the others. ADR-0007 forbids that ("prices
  are never averaged across branches"; dine-in only with evidence).
- **Attributes.** `Product.attributes` is a free `dict[str, JsonValue]`, and `Offer` has no
  attributes at all. Nothing tells a client which keys exist, what type they are, how to label
  them, or which ones are facets. The owner's Phase 2 brief asks for config-driven vertical modules
  (Beauty, Food, Fashion) with drill-down to variant, history and evidence. Without a declared
  attribute set the dashboard would have to hard-code per-vertical keys, and the ADR-0007 §6
  literal guard forbids that.
- **Capabilities.** `Capabilities.shades` is beauty-only. Other verticals need the same "explicit,
  never guessed from absence" signal for their own attributes.

## Decision

### 1. Portion is a Size
A food portion and an apparel size are the same wire concept as a beauty pack size: **the size of
the thing being priced**. `Size` gains two optional fields and relaxes one rule:

```text
Size {
  value:  decimal string | null   # published measure, e.g. "250"
  unit:   string | null           # "ml", "g", "pcs"; required iff value is set
  label:  string | null           # published label as shown, e.g. "Medium", "M", "9 pcs"
  system: string | null           # label namespace when it matters: "alpha", "eu", "uk", "us"
}
```

Validation:
- At least one of `value` or `label` is set.
- `value` and `unit` are set together or not at all.
- `system` needs `label`.
- A count is a measure: "9 pieces" is `{value: "9", unit: "pcs", label: "9 pcs"}`.
- Nothing is converted. Mass vs volume, alpha vs numeric and EU vs UK stay as published (ADR-0007
  §4.1, §4.3).

**Same-size rule** (`pi_metrics.view.same_size`, used by every counted pair):

| Base side | Other side | Result |
|---|---|---|
| Measure | Measure | Equal iff `Decimal(value)` and case-folded `unit` are equal (today's rule, unchanged) |
| Label only | Label only | Equal iff the folded `label` and `system` are equal **and** the profile marks labels comparable (below) |
| Measure | Label only | `size_unknown`: a measure is never inferred from a label |
| Both carry measure and label | — | The measure decides; the label is display only |
| Either `null` | — | `size_unknown` (today) |

Label equality is safe only inside an exact edge, and that is the only place it is used. An exact
edge already requires the same brand and item (ADR-0007 §5), so "Medium" is compared only with the
same brand's "Medium". It is **never** compared across brands: McDonald's "Medium" vs Burger King
"Medium" is a `substitute` edge, which compare doesn't count.

Each profile declares `size_labels_comparable`:
- `beauty`: false. Beauty sizes must be measured; a label-only beauty size stays `size_unknown`.
- `food_menu`: true.
- `apparel`: true, with `system` required.

Unit prices (per piece, per 100 g) are derived only from a measure, never from a label. They are
the `size_normalized` basis, which is out of scope for counted exact pairs.

### 2. Channel and location are an offer dimension: the selling context
A **context** is one priced place an item is sold: a retailer (register `source_key`), a channel,
and optionally a location. The snapshot lists contexts explicitly, and offers are keyed by context
id instead of retailer id.

```text
contexts[] {
  id:       SourceKey-shaped slug, unique in the snapshot
  retailer: retailers[].id
  channel:  pi_core Channel (online, marketplace, delivery, pickup, dine_in_evidenced, offline_audit)
  location: { id, label, city, area } | null   # no coordinates on the wire
  label:    LocalizedText                      # "Dubai Marina, delivery"
}
Product.offers: dict[context id, Offer]
```

**Beauty stays byte-identical in meaning.** A retailer with one context gets the context id equal
to its retailer id, with `channel = online` and `location = null`. Every existing key (`ulta_ae`,
`sephora_ae`) is still a valid offer key. If a v2 producer omits `contexts`, the validator derives
exactly these defaults. So current snapshots and the #55 goldens stay valid.

**Rules:**
- **Context identity.**
  - Two contexts of the **same retailer** price the same variant. This is the ADR-0007 §5 rule
    "same variant under different contexts, not a match edge". Their pair is counted with no match
    edge, subject to the same-size rule.
  - Two contexts of **different retailers** need that retailer pair's exact, approved or locked
    edge, as today. Edges stay keyed by retailer, because identity doesn't depend on channel.
- **No silent channel mixing.** A compare whose two sides have different channels is allowed:
  delivery vs dine-in markup is a real question. The response carries a `channel_differs` caveat
  naming both channels. The API never picks a channel for a client. Retailer-level views (coverage,
  product cards) list every context separately.
- **No averaging.** A summary over several contexts reports each context. Nothing is averaged
  across branches or channels, and a product card shows a price range across contexts only when it
  also says how many contexts it covers.
- **Dine-in only with evidence.** The producer emits a `dine_in_evidenced` context only for prices
  from the brand's own dine-in menu or a menu document it publishes. A missing dine-in price is
  `not_observed`, never copied from delivery.
- **Fees are not price.** Delivery, service and minimum-order fees go in
  `Offer.attributes.fees` as `MoneyValue`s. They are shown next to the price and never folded into
  `series.price`, a gap or an index.
- **Status lives on the retailer.** `blocked`/`partial` stays on `retailers[]`. A context inherits
  it; a per-context run state, if a source needs one, is a later additive field.

**API surface (S3):**
- `meta.contexts` lists the contexts.
- `compare`, `index`, `promotions` and `availability` take **context** ids for `base`/`other`.
  A retailer id still works, because it is its own default context. If a retailer id has more than
  one context, the request fails with 422 `ambiguous_context`, never a silent pick.
- Product search takes `channel` and `location` filters, which narrow the offers shown.
- `products/{id}` returns one offer view per context.

### 3. Per-vertical attribute sets are declared in the snapshot
The profile, not the client, declares its attributes. The snapshot carries the declaration, so the
dashboard and the API are config-driven without importing profile code:

```text
meta.profile = { name: "food_menu", version: 1 }       # replaces the bare meta.vertical
meta.attributeSet[] {
  key:        SourceKey-shaped, e.g. "portion_label", "daypart", "colour_family"
  level:      "product" | "offer"
  type:       "text" | "enum" | "decimal" | "money" | "bool" | "text_list" | "object"
  values:     [ { id, label: LocalizedText } ] | null  # enum only; closed
  label:      LocalizedText
  facet:      bool          # usable as a filter and a facet count
  block:      "summary" | "size_run" | "swatches" | "nutrition" | "combo" | "fees" | "channel" | null
  capability: bool          # collected in this snapshot; false → explicit not collected, never absent
}
Product.attributes: { key: value }   # product-level keys only
Offer.attributes:   { key: value }   # new; offer-level keys only (fees, daypart, size run stock)
```

**Validation** (`pi_dataset` validator, run by every producer, the upload validator and the API
loader):
- Every attributes key must be declared, at its level, with a value of its type. An unknown key
  fails validation, so new keys need a profile version bump.
- Enum values come from the closed list.
- `money` values are `MoneyValue`s, so they are never floats.
- A key with `capability: false` must not appear on any product or offer.

**Profiles own the declaration.** Each `VerticalProfile` (PR-E) exports its `attributeSet` from its
versioned pydantic attribute model (`beauty@1`, `food_menu@1`, `apparel@1`). The producer copies
it into the snapshot, so the snapshot and the database share one source. The beauty profile
declares its existing fields (shade family, finish, concentration). `Capabilities.shades` and
`Capabilities.sizes` stay as they are for v2 readers.

**API and dashboard:**
- **Facets.** The product-search facet engine adds one facet per `facet: true` key, using today's
  rule (a facet ignores its own filter). The filter syntax is `attr=<key>:<value>`, repeatable, at
  most 25, and a key must be declared, otherwise 422 `invalid_query`.
- **Product page.** The product page groups attributes by `block`. The dashboard renders the
  blocks it knows and shows the rest as a plain key/value list. An unknown block is never an
  error, so a new profile renders before its UI module exists.
- **Labels.** Labels come only from `attributeSet`. The ADR-0007 literal guard extends to
  attribute keys: a declared key must not appear as a literal in `apps/web` or `pi_api` outside
  fixtures and contracts.

**Metric applicability.** Each metric states the profiles it applies to. A metric requested on a
snapshot whose profile it doesn't apply to (for example, a shade-count metric on `food_menu`)
returns `not_enough_data` with a new reason `not_applicable`, not a 4xx and not zeros. Adding the
reason bumps `metricVersion` and adds a decision-log row.

### 4. Versioning and compatibility
- **Schema version.** Every change above is additive to `pi.dataset/v2`: new optional fields with
  defaults, and `Size` loosened only for non-beauty profiles. The schema id stays
  `pi.dataset/v2`.
- **Reader contract.** The validator rejects a label-only `Size`, a non-default context and a
  non-`beauty` profile on snapshots whose `meta.profile.name` is `beauty`. So a v2 reader that only
  knows beauty never meets them. The dashboard must handle them before it opens a non-beauty
  snapshot.
- **Wire money** is unchanged: `{amount: decimal string at the ISO 4217 exponent, minor: int,
  currency}`.
- **Metric changes** go through `metricVersion` and the decision log:
  - the same-size rule for labels;
  - the context pair rule;
  - the `channel_differs` caveat;
  - the `not_applicable` reason.
- **OpenAPI.** Every change regenerates `docs/contracts/pi-api.openapi.json` and the goldens.
  The OpenAPI drift test is the guard.

## Migration path
The PRs are small, and each one keeps beauty output byte-identical on the existing fixtures and
goldens.

| Step | Scope | Gate |
|---|---|---|
| 1 | `pi_dataset`: `Size.label`/`system`, `contexts[]` with derived defaults, `meta.profile`, `meta.attributeSet`, `Offer.attributes`, and validator rules. JSON Schema regenerated | This ADR accepted |
| 2 | PR-E: `VerticalProfile` registry (`beauty@1` first, exporting its attribute set); `variant.attributes_schema` append-only migration; brand aliases as data (ADR-0007 §4) | Step 1 |
| 3 | `pi_metrics`: context-keyed pairs, label same-size rule, `channel_differs`, `not_applicable`; `metricVersion` bump | Step 1 |
| 4 | `pi_api` S3: context ids on metric endpoints, `ambiguous_context`, `channel`/`location`/`attr` filters, attribute facets and blocks | Steps 1, 3 |
| 5 | `food_menu@1` and `apparel@1` profiles with synthetic fixtures (no live sources) | Step 2 |
| 6 | Dashboard modules driven by `attributeSet` blocks | Step 4 |

The first real non-beauty source still needs the owner's go, its own register entry and recon
(ADR-0007 follow-up). Nothing here authorises collection.

## Consequences
- **Food comparisons become possible.**
  - A brand's delivery vs pickup vs branch prices are first-class.
  - Same-brand label portions count as same size.
  - Cross-brand food stays `substitute`-only and is never counted as exact.
- **Clients stay thin.** Facets, labels and product-page blocks are data, so a new vertical needs
  a profile and fixtures, not dashboard or API code. Code is needed only when it wants a bespoke
  block renderer.
- **Snapshots get larger.** Many-branch restaurant snapshots multiply offers by contexts. The
  256 MiB loader cap and the per-scope layout (`datasets/<market>/<scope>/`) bound this; a brand
  with many branches is sliced by city scope.
- **Some cost moves to the API.** A retailer id that maps to several contexts now needs an
  explicit context. That is deliberate friction against silently mixing channels.
- **Validation tightens.** An undeclared attribute key now fails validation instead of passing
  through.

## Alternatives considered
| Alternative | Why not |
|---|---|
| A separate `portion` field next to `size` | Two fields for one concept. Every metric would need a vertical-specific "which one is the size" rule, which is exactly the hard-coding ADR-0007 removes |
| Compare labels across brands ("Medium" = "Medium") | False precision: portion labels are brand-defined. The cross-brand relation is `substitute`, which is human-approved (ADR-0007 §5) |
| Keep offers keyed by retailer and add `Offer.channel`, choosing one offer per retailer | Drops real prices or forces a choice the API would hide. ADR-0007 forbids averaging or collapsing branches |
| `offers: dict[retailer, list[Offer]]` | Breaks every v2 reader at once, and leaves offers with no stable id to compare, page or link evidence to |
| Composite keys (`ulta_ae~delivery~marina`) without a `contexts[]` list | Clients would parse ids to get labels and channels, and labels would leak into keys |
| Undeclared attributes, with the dashboard hard-coding keys per vertical | Violates the ADR-0007 literal guard. A typo'd key passes silently, and a new vertical needs UI code before it can render |
| `pi.dataset/v3` now | No reader needs a break: every addition defaults to today's beauty meaning. A v3 waits for a change that can't be additive |
