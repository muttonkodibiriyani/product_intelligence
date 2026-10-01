# offline_import

Imports a catalogue feed that a customer or partner sends us (CSV, Excel `.xlsx` or JSON) into
the same pi_db fact tables the web connectors write to. A column-mapping config says which feed
column holds which field.

```
python -m offline_import <file> --mapping <mapping.json> --dry-run --report report.json
python -m offline_import <file> --mapping <mapping.json> [--uri gs://bucket/archive/feed.csv]
```

- `--dry-run` reads and validates the file only. It never reads `PI_DATABASE_URL` and never
  opens a connection. The report counts rows, accepted rows, rejected rows with reasons, and
  warnings. It is printed as a summary and, with `--report`, written as JSON.
- A load reads `PI_DATABASE_URL` and writes everything in one transaction. `--uri` is the
  evidence `storage_uri` for the file; archive the file there first. The default is the local
  `file://` path.
- Exit codes: `0` means done (rejected rows are listed in the report); `2` means the mapping or
  file cannot be used.

## What is written

| table | rows |
|---|---|
| `source` | found by `source.name` or created (kind `offline` by default) |
| `source_context` | found by country, locale and channel, or created (rung 0, `partial`) |
| `crawl_run` | one per import, rung 0. Status is `partial`, or `succeeded` only with `complete_catalogue: true`, at least one row and no rejected row |
| `evidence` | one for the file: `content_hash` = the file's sha256, `fetch_method` = `offline_import` (rung 0) |
| `source_listing` | one per `listing_key` (the feed's SKU or variant key), upserted |
| `listing_content` | one per row. `labels` holds brand, size, shade, gtin, product_name, sku, image_url, stock_qty and import provenance |
| `offer_observation` | one per row: `price_current`, `price_regular_stated`, `price_promo`, `currency`, `availability_state`, `field_state` |

## Rules

- **Missing is data.** A blank price is NULL with `field_state.price_current = not_published`,
  never 0. A feed with no price column at all records `unknown` instead, so a stock-only import
  never blanks a crawled price in the export. A price of 0 or below is rejected.
- **Absence is not removal.** A listing missing from a feed gets no row, and the run stays
  `partial` unless the partner states the feed is the whole catalogue.
- **Availability** comes only from `availability_map`, which maps a feed value to a state and
  sets `field_state = observed`. If there is no availability value, a published `stock_qty`
  decides: `0` is out of stock, more than 0 is in stock. With neither, the state is
  `not_observed`, never out of stock. A value not in the map rejects the row. Feeds cannot
  assert `removed` or `blocked`.
- The schema has no stock-quantity column, so the quantity is kept in `listing_content.labels`.
- **Idempotent replays.** An import is identified by the file's sha256. Re-importing the same
  bytes, even from another path, reuses the first crawl_run and evidence and inserts nothing.
  `idempotency_key` = sha256(source | file sha256 | listing_key), and `observed_at` comes from
  the mapping (`observed_at`) or a column (`columns.observed_at`), never the import time.
  A naive timestamp is read in the mapping's `time_zone`.
- A row is rejected for: a missing or duplicate `listing_key`, an unparseable, zero, negative
  or over-precise price, a bad `stock_qty`, an unknown availability value, or a bad
  `observed_at`. An invalid GTIN (wrong check digit) is dropped with a warning.

## Why the fetch method is on rung 0

`offline_import` is a new `fetch_method` (pi_core `FetchMethod.OFFLINE_IMPORT`, pi_db migration
0003). Nothing is fetched from the source's site, so no ladder rung is climbed and no evasion is
involved. It sits on rung 0 (`SITE_DATA`) with the other first-party data methods.

## Mapping

The fixture `tests/fixtures/acme_mapping.json` shows every option. Extra keys are rejected.

- `source`: `name`, `kind` (default `offline`), `base_url`, `notes`.
- Context fields: `country` (ISO alpha-2), `locale` (plain tag, e.g. `en-AE`), `currency`
  (explicit; for SA/AE it must be the market's currency), `time_zone`, `channel`.
- `observed_at`, and/or `columns.observed_at`.
- `columns`: maps our field to the feed column. `listing_key` is required. The optional fields
  are `sku`, `gtin`, `url`, `name`, `name_ar`, `brand`, `category_path`, `size`, `shade`,
  `price_current`, `price_regular`, `price_promo`, `availability`, `stock_qty`, `image_url` and
  `observed_at`. Without `price_current`, the current price is the promo price, else the regular
  price.
- Readers: `format` (default: from the file suffix), `csv.delimiter`, `csv.encoding`,
  `json_items_path` (e.g. `data.items`), `xlsx_sheet`, `decimal_separator` (`.` or `,`).
- `availability_map` (case-insensitive) and `url_template` (`{listing_key}`, `{sku}`). With no
  Every listing needs an http(s) URL, from the url column or the template; the mapping is
  refused without either, and a row with a non-http(s) URL and no template is rejected.

YAML mappings need PyYAML, which is not a workspace dependency; JSON always works. XLSX is read
with the standard library and defusedxml (openpyxl is not installed). Only cell values are read:
dates stored as serial numbers are not converted, so use ISO text for `observed_at`.

Fixtures are synthetic ("Acme Beauty", GS1 restricted-circulation `2…` GTINs).

## Existing Ulta website snapshots

`python -m offline_import.ulta_feed` imports the captured Ulta UAE JSONL format through this
loader. It preserves the website-scrape provenance, brands, parent/variant relationships,
product content, image references, promotions, original price and stock capture times, and
raw values that cannot be represented as normalized prices. It does not contact the retailer.

```sh
PYTHONPATH=tools/offline_import python -m offline_import.ulta_feed prepare source.jsonl prepared/
PYTHONPATH=tools/offline_import python -m offline_import.ulta_feed load prepared/
PYTHONPATH=tools/offline_import python -m offline_import.ulta_feed export latest.json
```

The last two commands require `PI_DATABASE_URL`. Test against an isolated database before
loading the source database. Replaying the same prepared file adds no observations. Each SKU
has independent price and stock observations, with source capture times rather than import
wall time. A missing capture time fails preparation; `--capture-index captures.json` may supply
explicit per-SKU capture evidence (`retrieved_at`, basis, source file and hash). Never substitute
an ingestion time or a product's last-modified date for a capture time.

The combined export preserves other retailers, excludes configurable parent summaries when
sellable children exist, and uses the existing product/pack-size grouping. Non-positive source
prices become null; positive values finer than AED's minor unit remain exact in the database
and are withheld from the dataset. Known failed images remain null. Coverage stays partial.
The report and full feed retain exceptions for review.

The app's retailer image host configuration must include `ulta_ae=media.alshaya.com`, and its
Hosting image CSP must permit `https://media.alshaya.com`. Product evidence links use
`ulta_ae=www.ulta.ae`. Publish only after the strict dataset and API parser checks pass; preserve
an immutable rollback object and use a generation precondition when replacing `latest.json`.
