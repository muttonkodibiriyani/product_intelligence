# ADR-0008: Vertical profiles on the wire (`pi.dataset/v3`): portion as Size, selling contexts, declared attribute sets

- Status: proposed (drafted by the Deep Coder on the coordinator's brief, 1 Oct 2026). Revision 3:
  rewritten on the coordinator's v3 ruling and the Reviewer's #57 findings (rounds 1 and 2)
- Date: 2026-10-01
- Extends: ADR-0007 §4 (vertical profiles), §5 (matching) and §6 (dataset contract v2 and UI)
- Applies to: `pi_dataset`, `pi_metrics`, `pi_api`, the dashboard, the publisher, and the
  `VerticalProfile` plugins of PR-E (task 01a0f47a-9d64)
- Carries over unchanged:
  - ADR-0006 (access rulings);
  - the service-layer metric ruling: one metric implementation, in the service layer; Decimal
    money; counted pairs are exact and approved/locked; n ≥ 5; explicit `not_enough_data` states.

## Context
ADR-0007 decided **where** vertical data lives in the database:
- `variant.attributes jsonb` with a versioned per-vertical schema;
- `VerticalProfile` plugins;
- food portions in `size_value`/`size_unit` plus `attributes.portion_label`;
- channel in `source_context.channel`;
- branch in `location_context`.

It did not decide how that data reaches the published snapshot, the metric layer and the API.
The serving contract that has landed since then, `pi.dataset/v2`, is beauty-shaped:

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

**v2 can't absorb these changes additively.** `ContractModel` is `extra="forbid"`, and
`Size.value`/`unit` and `Meta.vertical` are required. Every deployed v2 reader rejects a document
that carries any new key or a label-only size:
- the publisher's upload validator;
- the `pi_api` loader;
- the demo export check.

They fail closed, which is safe, but it makes any such change a breaking one. Revision 1 of this
ADR claimed otherwise, and that was wrong (Reviewer, #57 MUST 1).

## Decision

### 0. A new contract id: `pi.dataset/v3`. v2 is frozen
- **`pi.dataset/v2` is frozen as of this ADR.** No field is added, removed or loosened. Beauty
  keeps publishing v2, byte-identical to today, until every consumer reads v3 (migration step 4).
- **Every new shape in §1–§3 exists only under `schema: "pi.dataset/v3"`.** A v2 reader that meets
  a v3 document refuses it on the schema id, with a clear error (`unsupported schema
  pi.dataset/v3`), not on a field-level failure deep in the document.
- **Readers.** A new reader accepts both ids and parses each with its own model. `pi_dataset`
  exposes `load_any() -> DatasetV2 | DatasetV3`, plus `upgrade(v2, profile) -> v3`. Consumers
  compute on v3 only.
- **Schema id first.** `load_any`, and from step 1 the v2 loader too, read `schema` before any
  model validation and refuse an unknown id with one error: `unsupported schema <id>; this
  reader accepts <ids>`. Today a v2 reader reports the id mismatch as one Literal error buried
  among dozens of extra-key errors.
- **`upgrade` is pure and deterministic, but not total.** It is the only path from v2 to v3, and
  it fails loudly instead of dropping data: a v2 attribute key that the profile doesn't declare
  raises `UpgradeError`, and nothing is emitted.
- **Where `upgrade` gets the profile.** It takes a `ProfileDeclaration`: the attribute set plus
  the size flags. That declaration is data, committed in `pi_dataset` as
  `contracts/profiles/<name>@<version>.json`, so `pi_dataset` never imports PR-E code.
  - Step 1 ships `beauty@1.json`, written from today's v2 beauty keys.
  - From step 2, a PR-E test asserts that each `VerticalProfile` exports exactly its committed
    JSON, so the profile code and the file can't drift.
- **Dual-write, then retire.**
  - Once `pi_api`, `pi_metrics` and the dashboard read v3, Infra's publisher writes both a v2 and a
    v3 document per generation for a transition window.
  - A test pins the v3 document to `upgrade(v2)`.
  - v2 retires only by a later ADR, which names the date and confirms no v2 reader remains.
  - Non-beauty profiles publish v3 only. They never had a v2 form.
- **`meta.vertical` is kept in v3.** It is still required and still a `SourceKey`, and it must
  equal `meta.profile.name`. `meta.profile` adds to it and doesn't replace it, so code that only
  reads `meta.vertical` keeps working on v3.

### 1. Portion is a Size
A food portion and an apparel size are the same wire concept as a beauty pack size: **the size of
the thing being priced**. In v3 `Size` is:

```text
Size {
  value:  decimal string | null   # published measure, e.g. "250"
  unit:   string | null           # "ml", "g", "pcs"; required iff value is set
  label:  string | null           # published label as shown, e.g. "Medium", "M", "9 pcs"
  system: string | null           # label namespace when it matters: "alpha", "eu", "uk", "us"
}
```

**Validation:**
- At least one of `value` or `label` is set.
- `value` and `unit` are set together or not at all, and `value` > 0 (as in v2).
- `system` needs `label`. If the profile has `sizeSystemRequired`, every `label` needs a `system`.
- If the profile has `sizeLabelsComparable: false`, `value` is required. This keeps beauty sizes
  measured.
- A count is a measure: "9 pieces" is `{value: "9", unit: "pcs", label: "9 pcs"}`.
- Nothing is converted. Mass vs volume, alpha vs numeric and EU vs UK stay as published (ADR-0007
  §4.1, §4.3).

**The profile flags are on the wire** (SHOULD 4). `meta.profile` carries `sizeLabelsComparable`
and `sizeSystemRequired`, so `pi_metrics` applies the same-size rule from the snapshot alone,
without importing profile code. The snapshot and the metric layer therefore can't disagree on
which profile version is in force.

**Folding** (SHOULD 5):
- `fold(s)` = Unicode NFKC, then `casefold()`, then runs of whitespace collapsed to one space and
  trimmed.
- Nothing is translated or transliterated, so Arabic "وسط" and "Medium" stay different, and the
  pair is `size_unknown`. That fails safe: an unknown size withholds a pair and never miscounts
  one.
- Units fold the same way; no unit is converted.

**The same-size rule** (`pi_metrics.view.same_size`, used by every counted pair) is **symmetric**:
swapping base and other never changes the result.

| One side | Other side | Result |
|---|---|---|
| Measure | Measure | Equal iff `Decimal(value)` and `fold(unit)` are equal (the v2 rule, unchanged) |
| Measure + label | Measure + label, equal measures, `fold(label)` differs | Equal, with the caveat `size_labels_differ` naming both labels: never silent |
| Label only | Label only | Equal iff `fold(label)` and `system` are equal **and** `meta.profile.sizeLabelsComparable` |
| Label only | Measure (with or without label) | `size_unknown`, whichever side is base: a measure is never inferred from a label |
| Either `null` | — | `size_unknown` (v2 rule) |

**Where labels are compared.** Labels are compared only inside an **exact** edge (or a
same-retailer stable-key group, §2). An exact edge already requires the same brand and item
(ADR-0007 §5), so "Medium" meets only the same item's "Medium". Labels are **never** compared:
- across brands: McDonald's "Medium" vs Burger King "Medium" is a `substitute` edge, and compare
  doesn't count those;
- between two products linked only by `substitute` or `family`, **even within one brand**.

**Profile settings:**

| Profile | `sizeLabelsComparable` | `sizeSystemRequired` |
|---|---|---|
| `beauty@1` | false | false |
| `food_menu@1` | true | false |
| `apparel@1` | true | true |

Unit prices (per piece, per 100 g) are derived only from a measure, never from a label. They are
the `size_normalized` basis, which is out of scope for counted exact pairs.

### 2. Channel and location are an offer dimension: the selling context
A **context** is one priced place an item is sold: a retailer (register `source_key`), a channel
and, optionally, a location. A v3 snapshot lists its contexts explicitly, and offers are keyed by
context id.

```text
meta.contexts[] {
  id:       SourceKey-shaped slug, unique in the snapshot (collision rule below)
  retailer: meta.retailers[].id
  channel:  pi_core Channel (online, marketplace, delivery, pickup, dine_in_evidenced, offline_audit)
  location: { id, label: LocalizedText, city, area } | null   # no coordinates on the wire
  label:    LocalizedText                                      # "Dubai Marina, delivery"
}
Product.offers: dict[context id, Offer]
```

**The context id collision rule** (MUST 3; a validator rule):
- A context's id equals its retailer's id **if and only if** it is that retailer's only context.
- A retailer with two or more contexts has none whose id is the bare retailer id.
- No context id equals **another** retailer's id, and context ids are unique in the snapshot.
- So a retailer id names a context exactly when the retailer has one. An API request that uses a
  retailer id with several contexts gets a deterministic `422 ambiguous_context`, never a silent
  pick.
- `upgrade(v2)` gives every retailer exactly one context `{id: <retailer id>, channel: online,
  location: null}`. So every v2 offer key is a valid v3 context id, and beauty results don't
  change.
- **Ids are stable across generations and never reused** (round 2, nit 3).
  - The same `(retailer, channel, location.id)` keeps the same context id in every generation.
  - A retired context's id is never reassigned to a different `(retailer, channel, location)`.
  - The producer derives ids from a per-source context register (data, next to the source
    register).
  - The publisher compares each new generation's `meta.contexts` with the previous published
    one, and refuses an id whose `(retailer, channel, location.id)` changed.
  - This is what lets a cursor, a saved view or a history series name a context safely.

**Identity across contexts** (MUST 2):
- **Same retailer, several contexts.** The producer puts several contexts of one retailer under
  one product **only** when the source's own **stable item key** says they are the same item: the
  same menu-item id across delivery, pickup and branches, or the same SKU.
  - Each such offer records that key in `evidence.itemKey`, and its kind in `evidence.itemKeyKind`
    (`sku`, `menu_item_id`, `source_product_id`).
  - Within a product, all offers of one retailer must share one `itemKey`. This is a validator
    rule.
  - Pairs inside that group are counted with **no** match edge, subject to the same-size rule.
    This is ADR-0007 §5's "same variant under different contexts, not a match edge", now with a
    stated basis.
- **Without a stable key, nothing is grouped.** If the source has no stable item key, or the
  connector would have to group by name, by fuzzy similarity or across separate channel apps that
  don't share ids, each context's item is **its own product**. Grouping by name is an identity
  decision, and identity decisions are reviewed.
  - Two items of one retailer in **different** products are never compared. Match edges are
    retailer-keyed (`a < b`) and live inside one product, so no edge can link them on the wire.
    Linking them would need a product-level identity record that v3 doesn't have; it is out of
    scope, and the fail-safe result is that the pair simply doesn't exist (round 2, MUST).
- **Different retailers** need that retailer pair's exact, approved or locked edge, as in v2.
  Edges stay keyed by retailer (`a`, `b` are retailer ids), because identity doesn't depend on
  channel. Within a product, the edge links retailer A's offers to retailer B's offers. Rule (c)
  below keeps "A's offers" unambiguous.

**Validator rules for identity** (round 2, MUST). These make the rules above checkable on the
wire. Each one is enforced by the `pi_dataset` v3 validator, and the metric layer also applies the
fail-safe reading, so a document that slipped past validation still can't miscount.

- **(a) One source item, one product.**
  - A keyed source item, `(retailer, evidence.itemKey)`, appears in exactly one product. A second
    product carrying the same pair is a validation error.
  - For unkeyed offers, the producer must emit each source listing once. The validator rejects
    two unkeyed offers of one retailer with the same canonical `url` in different products.
  - Without this rule, one item could be counted twice in promotions, availability and assortment
    gaps, and two A items could share one B identity.
- **(b) Same-retailer pairs need a shared key.**
  - Two offers of one retailer in one product are compared only when both carry the same
    `itemKey`. Otherwise the pair is `no_match`.
  - With rule (c) this can't arise in a valid document; the metric layer still applies it.
- **(c) An unkeyed offer is its retailer's sole offer in the product.**
  - An offer with no `itemKey` may appear in a product only as its retailer's **only** offer
    (context) in that product. The validator rejects anything else.
  - So a cross-retailer edge always names either one keyed group or one unkeyed offer per side,
    never a guess between several.
  - Fail-safe: if the metric layer ever sees an unkeyed offer next to another offer of the same
    retailer in one product, every pair involving that retailer in that product is `no_match`.
- **No transitive identity.**
  - An edge from retailer A's delivery item to B doesn't give A's pickup item a B identity. That
    happens only if A's own `itemKey` links the two A contexts in one product.
  - A–C plus B–C doesn't make A–B. That is the v2 rule, unchanged.

**Coverage per context** (SHOULD 6; the no-false-removal rule):
- **A context missing from a run is `not_observed`.** Its series entries for that date are `null`,
  and a `notObserved` window names it. It is never a removal or an out-of-stock.
- **`notObserved[]` gains an optional `context`** (null means the whole retailer, as in v2). This
  lets one branch or channel be marked unobserved while the others were crawled.
- **Coverage lists contexts.** The coverage view lists, for each retailer, every context and
  whether it was observed on each date. A `partial` retailer therefore shows *which* contexts were
  covered, not just "partial".
- **Retailer status still lives on `retailers[]`.** A context can't be better than its retailer: a
  `blocked` retailer blocks every context, whatever the per-context windows say.

**Rules carried over from revision 1:**
- **No silent channel mixing.** A compare whose two sides have different channels is allowed:
  delivery vs dine-in markup is a real question. The response carries a `channel_differs` caveat
  naming both channels. The API never picks a channel for a client.
- **No averaging.** A summary over several contexts reports each context. Nothing is averaged
  across branches or channels, and a product card shows a price range across contexts only when it
  also says how many contexts it covers.
- **Dine-in only with evidence.** The producer emits a `dine_in_evidenced` context only for prices
  from the brand's own dine-in menu or a menu document it publishes. A missing dine-in price is
  `not_observed`, never copied from delivery.
- **Fees are not price** (SHOULD 8).
  - Delivery, service and minimum-order fees go in `Offer.attributes.fees` as `MoneyValue`s **in
    the offer's currency**. The validator rejects any other currency, as it already does for
    series money.
  - The currency check walks **into** values (round 2, nit 4): every `MoneyValue` anywhere under
    `Offer.attributes` is checked, including inside an `object`-typed value such as `fees`
    (`{delivery, service, minimumOrder}`) and inside lists. Product-level money attributes are
    checked against the market currency.
  - Fees are shown next to the price, and are never folded into `series.price`, a gap or an index.

**API surface (when `pi_api` reads v3; migration step 4):**
- `meta.contexts` lists the contexts.
- `retailers=<base>,<other>` on `compare` and `index` accepts **context** ids. A retailer id is
  accepted only when it is its own (sole) context; otherwise the request fails with `422
  ambiguous_context`.
- `promotions`, `availability` and `coverage` report per context.
- Product search takes `channel` and `location` filters, which narrow the offers shown.
- `products/{id}` returns one offer view per context, and its `pairs[]` (S3) are context pairs.

### 3. Per-vertical attribute sets are declared in the snapshot
The profile, not the client, declares its attributes. The v3 snapshot carries the declaration,
so the dashboard and the API are config-driven without importing profile code:

```text
meta.vertical = "food_menu"                              # kept; equals meta.profile.name
meta.profile = {
  name: "food_menu", version: 1,
  sizeLabelsComparable: true, sizeSystemRequired: false  # §1
}
meta.attributeSet[] {
  key:        SourceKey-shaped, e.g. "portion_label", "daypart", "colour_family"
  level:      "product" | "offer"
  type:       "text" | "enum" | "decimal" | "money" | "bool" | "text_list" | "object"
  values:     [ { id, label: LocalizedText } ] | null  # enum only; closed
  label:      LocalizedText
  facet:      bool          # usable as a filter and a facet count
  block:      "summary" | "size_run" | "swatches" | "nutrition" | "combo" | "fees" | "channel" | null
  capability: bool          # collected in this snapshot; false → explicitly not collected, never absent
}
Product.attributes: { key: value }   # product-level keys only
Offer.attributes:   { key: value }   # new; offer-level keys only (fees, daypart, size-run stock)
```

**Validation** (`pi_dataset` v3 validator, run by every producer, the upload validator and the
API loader):
- Every attribute key must be declared, at its level, with a value of its type. An unknown key
  fails validation, so new keys need a profile version bump.
- Enum values come from the closed list.
- `money` values are `MoneyValue`s, so they are never floats, and they are in the offer's
  currency.
- A key with `capability: false` must not appear on any product or offer.
- **When `meta.profile.name` is `beauty`, the validator rejects:**
  - label-only sizes;
  - contexts with a channel other than `online` or with a location;
  - attribute keys outside the `beauty@N` set.

  This restates revision 1's circular sentence (Reviewer, #57 MUST 1).

**Profiles own the declaration.** Each `VerticalProfile` (PR-E) exports its `attributeSet` and
its two size flags from its versioned pydantic attribute model (`beauty@1`, `food_menu@1`,
`apparel@1`).
- The producer copies them into the snapshot, so the snapshot and the database share one source.
- The beauty profile declares its existing fields (shade family, finish, concentration).
- `Capabilities.shades` and `Capabilities.sizes` stay in v3, unchanged in meaning.

**API and dashboard:**
- **Facets.** The product-search facet engine adds one facet per `facet: true` key, using today's
  rule (a facet ignores its own filter). The filter syntax is `attr=<key>:<value>`, repeatable, at
  most 25. A key must be declared, otherwise the request fails with `422 invalid_query`.
- **Product page.** The product page groups attributes by `block`. The dashboard renders the
  blocks it knows and shows the rest as a plain key/value list. An unknown block is never an
  error, so a new profile renders before its UI module exists.
- **Labels.** Labels come only from `attributeSet`.
- **The literal guard** (SHOULD 7):
  - The ADR-0007 literal guard extends to attribute keys and enum values. A declared key must not
    appear as a literal in `pi_api`, `pi_metrics` or `apps/web` outside fixtures and contracts.
  - Today's dashboard hard-codes the beauty shade families (`FAMS` in `apps/web/src/data.js`) and
    the category list. The guard's allowlist names exactly those two constants, as **beauty
    exceptions**, from the step that extends the guard (step 1) until step 6.
  - Step 6 replaces both with `attributeSet` and `meta.taxonomy` data and deletes the allowlist
    entries. CI fails if an entry outlives the constant it covers.

**Metric applicability.**
- Each metric states the profiles it applies to.
- A metric requested on a snapshot whose profile it doesn't apply to returns `not_enough_data`
  with a new reason, `not_applicable`. It never returns a 4xx or zeros. Example: a shade-count
  metric on `food_menu`.
- Per the coordinator's ruling, `not_applicable` ships **with** the `metricVersion` bump for v3
  (step 3), together with these other v3 rule changes:
  - the label same-size rule;
  - `size_labels_differ`;
  - context pairs;
  - `channel_differs`.
- That bump adds one decision-log row.

### 4. Exactly what v3 adds and changes relative to v2
v3 = v2 plus the rows below. Nothing else in v2 changes: wire money (`{amount, minor, currency}`),
series, ratings, match edges, the field statuses and capabilities are all identical.

| Location | v2 | v3 | `upgrade(v2)` sets |
|---|---|---|---|
| `schema` | `"pi.dataset/v2"` | `"pi.dataset/v3"` | `"pi.dataset/v3"` |
| `meta.vertical` | required `SourceKey` | **kept**, required, must equal `meta.profile.name` | unchanged |
| `meta.profile` | — | **new, required**: `{name, version, sizeLabelsComparable, sizeSystemRequired}` | `{name: <vertical>, version: 1, false, false}` |
| `meta.attributeSet` | — | **new, required** (may be empty) | `ProfileDeclaration.attributeSet` (from `contracts/profiles/beauty@1.json` for beauty) |
| `meta.contexts` | — | **new, required**, ≥ 1 per retailer, collision rule §2 | one `{id: <retailer id>, retailer, channel: online, location: null, label: <retailer name>}` per retailer |
| `Size.value`, `Size.unit` | required | nullable, set together (§1) | unchanged |
| `Size.label`, `Size.system` | — | **new**, nullable | `null` |
| `Product.offers` keys | retailer id | **context** id | unchanged (retailer id = sole context id) |
| `Product.attributes` | free `dict[str, JsonValue]` | declared keys only (§3) | unchanged; a key the `ProfileDeclaration` doesn't declare raises `UpgradeError` |
| `Offer.attributes` | — | **new**, declared offer-level keys; `fees` in the offer currency | `{}` |
| `Offer.evidence.itemKey`, `itemKeyKind` | — | **new**, nullable; required when a retailer has more than one context in a product; rules (a)–(c) of §2 | `null` (each v2 retailer has one offer per product, so rule (c) holds) |
| `notObserved[].context` | — | **new**, nullable (null = whole retailer) | `null` |
| `MatchEdge.a`, `.b` | retailer ids | retailer ids (unchanged) | unchanged |

**Pinning `upgrade(v2)`:**
- The function is defined by this table and tested against every v2 fixture and golden.
- `pi_metrics` results on `upgrade(v2)` must equal today's results on v2, except for
  `meta.metricVersion`.
- That equality is the guard that beauty doesn't move.

**Contract artifacts:**
- v3 gets its own JSON Schema (`docs/contracts/pi-dataset-v3.schema.json`) next to the frozen v2
  one.
- The OpenAPI and the `pi_api` goldens regenerate when `pi_api` switches to v3. The drift tests are
  the guard.

## Migration path
Small PRs. Until step 5, beauty production output stays byte-identical v2.

| Step | Scope | Gate |
|---|---|---|
| 1 | `pi_dataset`: the `DatasetV3` models and validator (§1–§4, identity rules (a)–(c)), the schema-id-first check in `load_any` and the v2 loader, `upgrade(v2, profile)`, `contracts/profiles/beauty@1.json`, the v3 JSON Schema; the v2 model frozen by a test. Literal-guard allowlist for `FAMS`/categories | This ADR accepted |
| 2 | PR-E: `VerticalProfile` registry (`beauty@1` first, exporting its attribute set and size flags); `variant.attributes_schema` append-only migration; brand aliases as data (ADR-0007 §4) | Step 1 |
| 3 | `pi_metrics` on v3: context pairs with the stable-key rule, the symmetric label same-size rule, `size_labels_differ`, `channel_differs`, `not_applicable`; one `metricVersion` bump; beauty equality test on `upgrade(v2)` | Step 1 |
| 4 | Consumers read v3: `pi_api` (`load_any` + `upgrade`, context ids, `ambiguous_context`, `channel`/`location`/`attr` filters, per-context coverage) and the dashboard client | Steps 1, 3 |
| 5 | Infra: the publisher dual-writes v2 + v3 per generation; a test pins v3 = `upgrade(v2)`; the context-id stability check against the previous generation | Step 4 deployed |
| 6 | `food_menu@1` and `apparel@1` with synthetic fixtures (no live sources); dashboard modules driven by `attributeSet` blocks; `FAMS`/categories allowlist removed | Steps 2, 4 |
| 7 | Retire v2 | A later ADR |

The first real non-beauty source still needs the owner's go, its own register entry and recon
(ADR-0007 follow-up). Nothing here authorises collection.

## Consequences
- **Old readers fail cleanly.** A v2 reader never half-parses a v3 document: it refuses it on the
  schema id.
- **Beauty is untouched** until consumers are ready. The upgrade path is one tested function, and
  there's no flag day.
- **Food comparisons become possible.**
  - A brand's delivery, pickup and branch prices are first-class.
  - Same-item label portions count as the same size.
  - Cross-brand food stays `substitute`-only and is never counted as exact.
- **Grouping without review is narrow.** Same-retailer contexts are grouped without an edge only on
  a stable source key that the evidence records. Every other grouping goes through review.
- **Clients stay thin.** Facets, labels, size rules and product-page blocks are data, so a new
  vertical needs a profile and fixtures, not dashboard or API code. Code is needed only for a
  bespoke block renderer.
- **Snapshots get larger.** Many-branch restaurant snapshots multiply offers by contexts. The
  256 MiB loader cap and the per-scope layout (`datasets/<market>/<scope>/`) bound this; a brand
  with many branches is sliced by city scope.
- **Dual-write costs storage** for the transition window. That is roughly 2× the beauty snapshot
  bytes; small at today's sizes, and it ends when v2 retires.
- **Validation tightens.** An undeclared attribute key, a foreign-currency fee or a colliding
  context id now fails validation instead of passing through.

## Alternatives considered
| Alternative | Why not |
|---|---|
| Additive changes under `pi.dataset/v2` (revision 1) | Not additive: `extra="forbid"` and the required `Size.value`/`unit` and `Meta.vertical` make every new key a field-level failure in every deployed v2 reader (Reviewer, #57 MUST 1) |
| A single id with a lockstep, reader-first rollout | It works only if every reader ships before any producer emits a new field, and nothing enforces that ordering. A distinct id makes the mismatch a clear refusal |
| `pi.dataset/v2.1` | A minor id suggests that a v2 reader can read it, and it can't |
| Replace `meta.vertical` with `meta.profile` | Removes a required field that existing code reads; keeping both, with an equality check, costs one string |
| A separate `portion` field next to `size` | Two fields for one concept. Every metric would need a vertical-specific "which one is the size" rule, which is exactly the hard-coding ADR-0007 removes |
| Compare labels across brands ("Medium" = "Medium") | False precision: portion labels are brand-defined. The cross-brand relation is `substitute`, which is human-approved (ADR-0007 §5) |
| Group same-retailer contexts by name | That is an unreviewed identity decision. Only a stable source item key groups without an edge |
| Keep offers keyed by retailer and add `Offer.channel`, choosing one offer per retailer | Drops real prices or forces a choice the API would hide. ADR-0007 forbids averaging or collapsing branches |
| `offers: dict[retailer, list[Offer]]` | Leaves offers with no stable id to compare, page or link evidence to |
| Composite keys (`ulta_ae~delivery~marina`) without a `contexts[]` list | Clients would parse ids to get labels and channels, and labels would leak into keys |
| Undeclared attributes, with the dashboard hard-coding keys per vertical | Violates the ADR-0007 literal guard. A typo'd key passes silently, and a new vertical needs UI code before it can render |
