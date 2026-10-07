# `pi.dataset/v3`: vertical profiles, sizes and selling contexts

`pi.dataset/v3` is `pi.dataset/v2` plus per-vertical profiles, label sizes and selling contexts.
The decision record, with the reasoning and every rule, is
[ADR-0008](../adr/0008-vertical-profiles-on-the-wire.md). This page lists the artifacts and how to
use them. `pi.dataset/v2` ([pi-dataset-v2.md](pi-dataset-v2.md)) is frozen; a test pins its
models.

| Artifact | Where |
|---|---|
| Models and validator | `packages/pi_dataset/src/pi_dataset/v3.py` |
| Profile declarations (data) | `packages/pi_dataset/src/pi_dataset/contracts/profiles/<name>@<version>.json` |
| v2 → v3 | `pi_dataset.upgrade(v2, profile)` in `upgrade.py` |
| JSON Schema, draft 2020-12 (generated; do not edit) | `docs/contracts/pi-dataset-v3.schema.json` |
| Loader | `pi_dataset.load_any` (v2 or v3); `load_dataset` stays v2-only |
| CLI | `uv run pi-dataset validate --v3 FILE...`, `pi-dataset schema --v3` |

CI fails if the committed schema differs from the models. To regenerate:

```sh
uv run pi-dataset schema --v3 > docs/contracts/pi-dataset-v3.schema.json
```

## Reading

- **The schema id is checked first.** `load_any` reads `schema` before anything else and fails
  with `unsupported schema <id>` for an id it doesn't accept, instead of a list of field errors.
  The v2 loader does the same, so a v2-only reader fails clearly on a v3 document.
- **Strict, as in v2.** No coercion, no floats, no credentials in URLs.

## What v3 adds (ADR-0008 §4)

- **`meta.profile`** `{name, version, sizeLabelsComparable, sizeSystemRequired}`, with
  `meta.vertical` = `meta.profile.name`. For a committed profile, the flags and
  **`meta.attributeSet`** must equal the declaration exactly, except that a key may be turned off
  (see below). Committed profiles: `beauty@1`, `beauty@2`.
- **`meta.attributeSet`**: every key in `Product.attributes` and the new `Offer.attributes` is
  declared, at its level, with a value of its type (`text`, `enum`, `decimal`, `money`, `bool`,
  `text_list`, `object`). Money anywhere inside an attribute is checked: offer-level against the
  offer currency, product-level against the market currencies.
- **Sizes**: `value` + `unit` (set together, positive), a `label`, or both. A label's `system`
  names its namespace; a profile can require measured sizes or a system for every label.
- **`meta.contexts`**: offers are keyed by context id. A context id equals its retailer's id if
  and only if it is that retailer's only context; when a retailer gains a second context the bare
  id is retired and requests using it get `422 ambiguous_context`.
- **Identity** (rules (a)–(c)): offers of one retailer in one product share one
  `evidence.itemKey`; an unkeyed offer is its retailer's only offer in the product; a keyed item
  or an unkeyed canonical url belongs to one product, and an unkeyed offer never sits on a url
  that is a keyed offer's in another product (same retailer). A retailer with several contexts needs
  `itemKey` or `url` on every offer.
- **`notObserved[].context`**: null means the whole retailer.
- **`Offer.listingCount`** (optional, additive, 2026-10-01): how many of the retailer's listings
  the producer grouped into the offer (for example the shades of one size), an integer ≥ 1;
  `null` or absent when the producer doesn't say. It is a count of listings, not of sizes or
  shades (`shadeCount` stays the distinct shade names).

- **`Offer.content`** (optional, additive, 2026-10-03): what the retailer's page says beyond
  price and stock. `captured` lists the fields (`description`, `ingredients`, `images`, `shade`,
  `gtin`) the offer's source carries anywhere in the snapshot, each once. A listed field that is
  null or empty on an offer is one the retailer did not publish there; an unlisted field is not
  captured from that source, and must be empty. `images` is the page gallery in page order, only
  on the retailer's own image hosts. `variants` holds every listing grouped into the offer
  (`sku`, `shade`, `gtin`); a `gtin` must pass the GS1 check digit (GTIN-8/12/13/14), so a
  producer drops an invalid barcode rather than publish it. `family` is the retailer's own
  product family id: offers of one context that share it are sizes of one product. `content`
  absent (every snapshot before 2026-10-03) states nothing, and `pi_api` serves every field as
  `not_captured`.
- **`Product.attributeEvidence`, `Offer.attributeEvidence`** (optional, additive, 2026-10-06;
  ADR-0008 §5): per attribute key at that level, where its value was read: `{source, field,
  excerpt, rule}`. `source` is `page` (a structured page field), `text_rule` (a deterministic
  rule on free text) or `model`. `rule` names the rule or model, and is null exactly for `page`.
  `excerpt` is the retailer's text (at most 120 characters): untrusted, so it is shown as plain
  text only. Evidence for a key that isn't in `attributes` fails validation. From `beauty@2` on,
  every attribute value has evidence.
- **Collected or not, per snapshot** (2026-10-06): a snapshot may declare a committed key with
  `capability: false` (a key below the precision gate is published as not collected, with no
  values). It never turns on a key that the committed profile declares off, and nothing else in
  the declaration may differ.

## Upgrading v2

`upgrade(v2, profile)` gives every retailer one online context whose id is the retailer id, so
every v2 offer key stays valid. Each offer's v2 `sku` becomes `evidence.itemKey` (kind `sku`; both
`null` without a sku), so size variants that share one page `url` stay distinct items under
identity rule (a). `listingCount` is `null` and `content` is absent (v2 states neither). It raises `UpgradeError` if the vertical isn't the profile's, a product carries
an attribute key the profile doesn't declare, or the result breaks a v3 rule (for example one sku
in two products of a retailer).

## Literal guard

A key or enum value declared by any committed profile must not appear as a quoted literal in
`pi_api`, `pi_metrics` or `apps/web` (`packages/pi_dataset/tests/test_literal_guard.py`). The
dashboard's `FAMS` and `CATS` constants are the allowlisted beauty exceptions until migration
step 6.
