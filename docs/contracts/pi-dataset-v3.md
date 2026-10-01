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
  **`meta.attributeSet`** must equal the declaration exactly.
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
  or an unkeyed canonical url belongs to one product. A retailer with several contexts needs
  `itemKey` or `url` on every offer.
- **`notObserved[].context`**: null means the whole retailer.

## Upgrading v2

`upgrade(v2, profile)` gives every retailer one online context whose id is the retailer id, so
every v2 offer key stays valid. It raises `UpgradeError` if the vertical isn't the profile's or a
product carries an attribute key the profile doesn't declare.

## Literal guard

A key or enum value declared by any committed profile must not appear as a quoted literal in
`pi_api`, `pi_metrics` or `apps/web` (`packages/pi_dataset/tests/test_literal_guard.py`). The
dashboard's `FAMS` and `CATS` constants are the allowlisted beauty exceptions until migration
step 6.
