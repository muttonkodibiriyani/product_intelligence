# Demo dataset exporter

This read-only script converts the latest AED observations in a local `pi_db` into the
frontend's `pi.dataset/v1` snapshot and, with `--output-v2`, the same snapshot as
`pi.dataset/v2` (`v2.py`, contract in `docs/contracts/pi-dataset-v2.md`). It performs no retailer
or Algolia requests.

The export grain is product family × pack size. Shade variants collapse into one offer and
the representative variant is the lowest-priced in-stock variant (or the lowest-priced
variant when stock is unknown). Ulta aggregate-parent listings (latest content `labels.aggregate_parent`
JSON true or text `'true'`) repeat their variants. One is left out iff at least one of its
`labels.resolved_children` is exported in the same snapshot as a non-parent listing of the same
source. A parent with no such child stays, and a reference to another parent doesn't count.
Sephora listings are never dropped this way. Current match edges pair Ulta and Sephora groups greedily by
highest confidence; excess many-to-one edges remain unmatched.

Run from the repository root, as a module (`--output-v2` imports `scripts.demo_export.v2`, so the
file-path form `python scripts/demo_export/export.py` fails with `No module named 'scripts'`):

```sh
uv run python -m scripts.demo_export.export \
  --database-url "$PI_DATABASE_URL" \
  --output "$OUTPUT_PATH" \
  --output-v2 "$OUTPUT_V2_PATH" --producer-commit "$(git rev-parse HEAD)"
```

The v2 file is built from the same rows, groups and pairs as v1 (same product ids), built as
`pi_dataset` models and re-read with the strict `load_dataset` before anything is written; an
invalid v2 document fails the whole export. `--scope` (default `beauty`) names the storage folder
`datasets/ae/<scope>/`. v1 stays the dashboard's input until it moves to v2 (ADR-0007 §6).

`--output-v3 PATH` (opt-in; `--output-v2` stays the default published file) also writes that v2
snapshot upgraded to `pi.dataset/v3` under `beauty@1`, with each collected offer's
`listingCount`: the listing rows grouped into it (one family, one pack size; an early recon offer
states none) and its `content`: the representative listing's description, ingredients and
gallery (description and ingredients fall back to the first other listing, by sku, that has
them), and every grouped listing as a variant with its shade and GTIN. A barcode that fails the
GS1 check digit is dropped. `captured` is, per retailer, the fields any of its exported listings
carries, so a missing field reads *not published* for a retailer that has it elsewhere and *not
captured* for one that never has it. It is re-read with the strict `load_any` before anything is
written. Publishing v3 instead of v2 is the owner's call at re-export.

v2 and v3 are written as compact JSON. The v3 body has a 90 MB budget (`V3_MAX_BYTES` =
90,000,000 compact bytes). `pi_api` holds the parsed snapshot in memory, and the budget is sized
from pi_api's measured resident memory at 3Gi (`docs/runbooks/pi-api-deploy.md` §6,
`packages/pi_api/tests/test_content_memory.py`). The
exporter prints the written bytes by group (`prices`, `attributes`,
`description+ingredients`, summing to the total) and refuses, writing nothing, above the budget.
There is no override flag.

By default v2 has one date, the cutoff's calendar day in Dubai. A price (and its regular price) or a stock
value captured on any other day is published as `null`, never carried forward (contract rule 6),
and `meta.fields.price` / `regular` / `stock` say `partial`. Stock has its own capture time (the
newest row that observed a stock state, carried as `stock_*` like `price_*`), separate from the
price capture. An offer's evidence is its price
capture when the price is published, else its stock observation. Ulta's `blocked` status and window
come from the owner's statement (`--ulta-blocked-since` and the notes), not from whether Ulta rows
exist; pass `--ulta-unblocked` once Ulta is collected again.

`--history` (with `--output-v2` or `--output-v3`; not with `--ulta-early-fixture`) builds a
multi-date v2 instead (`history.py`). It reads every succeeded or partial en-AE run per retailer,
files each observation under its Dubai market day (`Asia/Dubai`, so 21:30Z is the next day, never
the UTC date) and lists in `meta.dates` every day that has rows. Each day's offer values come from
that day's observations only; a day without an observation is `null`, never carried forward, and
no date is added that has no rows. A day is *complete* for a retailer only when every one of its
contexts had a `succeeded` run that started and ended on that market day on a context marked
`coverage_status = supported`; every other date gets a `notObserved` window ("not collected" or
"incomplete"), so a product missing on a partial or blocked day is neither a removal nor a launch.
A retailer whose latest date is complete is `supported` from its first complete day (`since`);
otherwise it keeps its snapshot status, because the status is read at the latest date. A blocked
retailer keeps the owner's statement and window, and every other date of it that is not complete
gets a window too. `capabilities.history` is true only with at least 2 dates. Product ids,
names and pairing come from each listing's latest row through the snapshot's own grouping, so ids
match the single-day export. Without `--history` the output is unchanged.

For the pilot, ulta.ae is blocked (owner decision, 2026-09-30): the Ulta status line is
`--ulta-blocked-note` / `--ulta-blocked-note-ar`, defaulting to "ulta.ae: blocked by site security
(Cloudflare) via Gulf datacenter and UAE residential; 0 products". Pass both notes or neither;
neither may be empty. No recon products or recon
sentence are exported unless the recon arguments below are passed.

Inputs are the read-only local `pi_db` URL plus optional reviewed Ulta recon metadata. The output
is the plain JSON file at `OUTPUT_PATH` (plus `OUTPUT_V2_PATH` when given); use a scratch path outside the repository. This is
a one-shot command: it reads each UAE source context's newest crawl run, writes atomically, prints
the cutoff and SHA-256, then exits. It never polls or waits for a crawl.

Only after the reviewed Ulta fixture is present on `main`, an early recon sample may be added:

```sh
uv run python -m scripts.demo_export.export \
  --database-url "$PI_DATABASE_URL" \
  --output "$OUTPUT_PATH" \
  --ulta-early-fixture /path/to/committed/ulta_ae_pdp_trimmed.html \
  --ulta-captured-at 2026-09-30T20:42:00Z \
  --ulta-fixture-commit <main-commit-containing-reviewed-fixture> \
  --ulta-recon-observed-count 3 \
  --ulta-recon-source 'docs/recon/gulf_probe_results.md @ <main-commit>'
```

The three Ulta fixture arguments are optional and must be supplied together. Only use a fixture
that is present on `main` after its redaction and robots review; the commit is embedded in the
evidence label. If that review has not merged, omit the fixture. The timestamp must be the capture
time, not the export time. Fixture observations are marked `early: true`; real Ulta rows loaded
into `pi_db` are exported normally and inherit the source's partial/complete status. Recon samples
are excluded from product coverage, matching and price comparison totals. The recon observed count
is never inferred: when supplied, it must include the report path and commit as its source.

The exporter reads money as `Decimal` and accepts AED values with at most two fractional digits.
The v1 JSON uses JSON numbers because JSON has no decimal scalar; values are never emitted as
strings or synthesized from missing data. Only observations from each UAE source context's newest
crawl run are exported, so an older observation cannot appear under the current cutoff date.
v2 has no floats at all: money is a decimal string plus integer minor units, ratings keep the
retailer's own scale, and a zero or negative price is "not observed" (reported as
`parse_failure`/`partial` in `meta.fields.price`), never a price.

Validate the result with the frontend-owned validator before handoff:

```sh
node /path/to/contract/validate.js /path/to/dataset.json
```
