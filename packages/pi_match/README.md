# pi_match: first-pass product matching (demo stage)

A deterministic, stdlib-only first pass at blueprint §8 for the Ulta ↔ Sephora demo. It is a
precursor to the full pipeline (blocking + Splink + embeddings + judge + review) and does not
replace it. It has no network and no model calls.

## Run

```sh
# 1. Export each snapshot from the local pi_db (or supply JSONL from a loader directly).
#    DRAFT dev helper, not the contract: sql/export_snapshot.sql is for local demo runs only.
#    The shared export is pi.dataset/v1 (owned by the connector/export owner); don't build on it.
psql "$PI_DATABASE_URL" -v source=ulta_ae    -At -f packages/pi_match/sql/export_snapshot.sql > ulta.jsonl
psql "$PI_DATABASE_URL" -v source=sephora_me -At -f packages/pi_match/sql/export_snapshot.sql > sephora.jsonl
# 2. Match
uv run pi-match --left ulta.jsonl --right sephora.jsonl --out out/match --cutoff 2026-09-30
```

Each JSONL line is a `ProductRecord`:
- required: `source`, `source_key`, `brand` and `name`;
- optional: `url`, `size`, `shade`, `gtin`, `category`, `price` (a decimal string), `currency`
  and `aggregate` (default `false`).

`aggregate: true` marks a product-level row that groups other rows (its variants). Such rows are
skipped before matching and in the brand overlap, and `summary.json` counts them in
`aggregates_skipped`. Skipping is in memory only: nothing is written back. No PI loader sets
it; the draft export SQL reads `labels.aggregate_parent` when an import wrote it, and treats
only JSON `true` or the text `'true'` as true.

`size` and `shade` may be a list: a JSON array (kept as a list), or list text such as
`"['100'] ['ML']"` (one or more flat lists side by side, each parsed with `json`, else
`ast.literal_eval`; at most 512 characters). A list gives a value only when it holds exactly
one: one distinct item, or for sizes one distinct number beside one distinct unit. Several
sizes, units or shades are ambiguous and give none (never the first), as does any parse failure
or other shape. An ambiguous size list never falls back to a size in the name.

A list whose only group is a number and then its unit (`[50, "ml"]`) is that size. A leading
bracketed label that is not a literal (`"[Limited] 50ml"`) is plain text, not a list.

A bad line fails the run and names the line number.

## Unit price (`pi_match.unit_price`)

`derive_unit_price(price, size_text)` gives the price per 100 ml, per 100 g or per unit
(`BasePrice(amount, basis)`, rounded half-even to 0.0001), using `parse_size` above or a piece
count ("60 capsules"). It gives None rather than guess when:

- the price is missing or not positive;
- the size is missing, unparsed or ambiguous (a list of several sizes);
- the label is a multi-pack ("2 x 50 ml", "pack of 3", "duo"), because the published size is
  per item, not per pack;
- the label holds both a size and a piece count.

`price_per_base(price, size, count=, pack=)` takes the parsed parts. Both are pure: nothing calls
them yet, and nothing is written. `UnitPrice` in `MatchPair` (per 1 ml or 1 g) is unchanged.

## Outputs (`--out`)

| File | Contents |
|---|---|
| `matches.json` | One-to-one pairs with bucket, score, reasons, prices, unit prices and the price gap |
| `brand_overlap.json` | Brand keys found in both snapshots, only-left and only-right |
| `summary.json` | Counts per bucket, brand overlap sizes, pairs with a comparable price, and skipped aggregate rows |
| `precision_sample.csv` | Up to 50 pairs, round-robin across buckets and hash-ordered, for **hand** labelling (`label` = correct / wrong / unsure). Nothing is pre-labelled |

Identical inputs give byte-identical outputs. `--cutoff` is a label, never a clock.

## How it matches

1. **Brand key.** Brands are case- and diacritic-folded, `&`/`+` becomes `and`, apostrophes are
   dropped, and aliases apply (`BRAND_ALIASES`, e.g. `YSL Beauty` → `yves saint laurent`). The aliases are
   data, not code: `src/pi_match/brand_aliases.json`, `{canonical: [aliases]}` in the shape of
   `brand.aliases`, folded and sorted (a test checks both). A
   trailing `cosmetics`/`makeup`/`skincare`/`paris`/`london`/`new york` is dropped. Pairs are
   only considered within the same brand key.
2. **Hard rules** (§8.4):
   - Kind (regular / mini / refill / set) must agree.
   - A known concentration (EDP / EDT / parfum / EDC / body mist) must agree. Known on one side
     only, it caps the pair at `probable` (reason `concentration_unknown_one_side`), unless the
     GTINs are equal.
   - GTINs (check digit verified, padded to 14). Two valid GTINs that differ never match. Two
     valid, equal GTINs make an exact match only when the rules above and size/shade agree;
     otherwise the pair is kept as `candidate` with reasons `gtin_equal`, `gtin_conflict` and
     the conflict (`kind_differs`, `concentration_differs`, `size_differs`, `shade_differs`).
3. **Name score.** 0.6 × token Jaccard + 0.4 × `difflib` ratio of the sorted tokens. Brand
   words, sizes, bare numbers and attribute words (eau, parfum, spray, …) are removed first, and
   `SPF 10` is glued to `spf10`.
4. **Buckets.**
   - `exact`: the name score is ≥ 0.85, the size is the same, and the shade is equal (code,
     else name) or absent on both sides. **Size tolerance:** two sizes are the same when they are
     in the same base unit (ml or g, after fl oz / oz conversion) and within **±3%** of each
     other, so 1 fl oz = 30 ml. ml and g are never compared.
   - `probable`: the name score is ≥ 0.70 and nothing conflicts.
   - `candidate`: the name score is ≥ 0.50, or the size or shade differs. A size or shade
     difference also adds the reason `family_only`.
5. **One-to-one.** Pairs are assigned greedily: best bucket first, then highest score, then keys.
6. **Price.** Prices are compared only in the same currency:
   - per ml or g when both unit prices are known in the same unit (`price_basis=unit`);
   - else per item when the sizes are the same (`item`);
   - else per item when neither size is known (`item_size_unknown`; flagged, the sizes may
     differ);
   - else not compared (null): ml vs g, only one size known, a missing price or another currency.
7. **Mapping to `pi_db` `match_class`** (for the writer, when it lands):

   | Bucket | `match_class` | `review_state` |
   |---|---|---|
   | `exact` | `exact` | `proposed` (the DB default; auto-approval waits for calibration) |
   | `probable` | `exact` | `proposed`, reviewed first |
   | `candidate` with `family_only` | `family` | `proposed` |
   | `candidate` otherwise (incl. `gtin_conflict`) | not written; review queue only | — |

   The writer never overwrites an edge whose `review_state` is `rejected` or `locked`.

## Limits (by design, first pass)

- There are no embeddings, images or Arabic names yet.
- Aliases are a short hand-kept list; extend `BRAND_ALIASES` from `brand_overlap.json`.
- Thresholds are not calibrated. The 50-pair labelled sample is the first precision read, not
  the §8.3 gold set.
