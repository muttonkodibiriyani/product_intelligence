# pi_match: first-pass product matching (demo stage)

A deterministic, stdlib-only first pass at blueprint §8 for the Ulta ↔ Sephora demo. It is a
precursor to the full pipeline (blocking + Splink + embeddings + judge + review) and does not
replace it. It has no network and no model calls.

## Run

```sh
# 1. Export each snapshot from the local pi_db (or supply JSONL from a loader directly)
psql "$PI_DATABASE_URL" -v source=ulta_ae    -At -f packages/pi_match/sql/export_snapshot.sql > ulta.jsonl
psql "$PI_DATABASE_URL" -v source=sephora_me -At -f packages/pi_match/sql/export_snapshot.sql > sephora.jsonl
# 2. Match
uv run pi-match --left ulta.jsonl --right sephora.jsonl --out out/match --cutoff 2026-09-30
```

Each JSONL line is a `ProductRecord`:
- required: `source`, `source_key`, `brand` and `name`;
- optional: `url`, `size`, `shade`, `gtin`, `category`, `price` (a decimal string) and `currency`.

A bad line fails the run and names the line number.

## Outputs (`--out`)

| File | Contents |
|---|---|
| `matches.json` | One-to-one pairs with bucket, score, reasons, prices, unit prices and the price gap |
| `brand_overlap.json` | Brand keys found in both snapshots, only-left and only-right |
| `summary.json` | Counts per bucket, brand overlap sizes, and pairs with a comparable price |
| `precision_sample.csv` | Up to 50 pairs, round-robin across buckets and hash-ordered, for **hand** labelling (`label` = correct / wrong / unsure). Nothing is pre-labelled |

Identical inputs give byte-identical outputs. `--cutoff` is a label, never a clock.

## How it matches

1. **Brand key.** Brands are case- and diacritic-folded, `&`/`+` becomes `and`, apostrophes are
   dropped, and aliases apply (`BRAND_ALIASES`, e.g. `YSL Beauty` → `yves saint laurent`). A
   trailing `cosmetics`/`makeup`/`skincare`/`paris`/`london`/`new york` is dropped. Pairs are
   only considered within the same brand key.
2. **Hard rules** (§8.4):
   - Two valid GTINs (check digit verified, padded to 14) that are equal make an exact match.
     Two valid GTINs that differ never match.
   - Kind (regular / mini / refill / set) must agree.
   - A known concentration (EDP / EDT / parfum / EDC / body mist) must agree.
3. **Name score.** 0.6 × token Jaccard + 0.4 × `difflib` ratio of the sorted tokens. Brand
   words, sizes, bare numbers and attribute words (eau, parfum, spray, …) are removed first, and
   `SPF 10` is glued to `spf10`.
4. **Buckets.**
   - `exact`: the name score is ≥ 0.85, the size is the same (±3%, so 1 fl oz = 30 ml), and the
     shade is equal (code, else name) or absent on both sides.
   - `probable`: the name score is ≥ 0.70 and nothing conflicts.
   - `candidate`: the name score is ≥ 0.50, or the size or shade differs. A size or shade
     difference also adds the reason `family_only`.
5. **One-to-one.** Pairs are assigned greedily: best bucket first, then highest score, then keys.
6. **Price.** Prices are compared only in the same currency:
   - per ml or g when both sizes are known (`price_basis=unit`);
   - else per item (`item`);
   - else not compared (null).

## Limits (by design, first pass)

- There are no embeddings, images or Arabic names yet.
- Aliases are a short hand-kept list; extend `BRAND_ALIASES` from `brand_overlap.json`.
- Thresholds are not calibrated. The 50-pair labelled sample is the first precision read, not
  the §8.3 gold set.
