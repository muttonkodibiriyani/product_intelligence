# pi_core record models

Frozen pydantic v2 models that connectors emit and the DB schema mirrors. Blueprint v1.1 §5
is the source of truth for names; each module's docstring maps its fields to requirement IDs.

| Model | Module | Blueprint table | Requirements |
|---|---|---|---|
| `Source` | `context` | `source` | SRC-01 |
| `SourceContext` | `context` | `source_context` | SRC-02, SCP-02, SCP-06, SCP-08, DAT-07, SRC-16, ADR-0003/0004 |
| `CollectionContext` | `context` | `crawl_run` (subset) | SRC-02, SRC-09, ADR-0003 |
| `Evidence` | `evidence` | `evidence` | DAT-04, DAT-10, ADR-0003 |
| `ListingRecord`, `ImageRef` | `listing` | `source_listing`, `variant`, `listing_image` | CAT-01, CAT-02, CAT-03, CAT-05, CAT-06, CAT-07, SRC-13 |
| `OfferObservation`, `InstallmentPlan` | `observation` | `offer_observation` | DAT-01/02/03/06/09, PRC-01..05, PRC-13, SRC-12, DQ-02, DQ-05 |
| `PromotionRecord` | `promotion` | `promotion`, `offer_promotion` | PRC-09, PRC-15 |

## Shared rules

| Rule | Where | Requirements |
|---|---|---|
| Amounts are `Decimal`, fit `numeric(18,4)`; floats, bools, NaN and infinity are refused | `types.Amount` | PRC-03, DQ-03 |
| One `currency` per record; `money()` returns `Money` in it; the context's currency comes from its market | `observation`, `context` | PRC-03, PRC-07 |
| Datetimes must be timezone-aware and are normalised to UTC | `types.UtcDatetime` | DAT-03 |
| A tracked field is `None` exactly when `field_state` gives a reason | `base.FieldStateModel` | DQ-02, DAT-06 |
| Rung and fetch method always agree; the rung may not exceed the context's cap (paid is opt-in) | `context.check_rung` | ADR-0003 |
| Unknown keys are rejected; records are immutable | `base.PiModel` | DAT-01 |

## Ids and logical keys

Row ids are `bigint` identity values assigned by the database (`types.DbId`, always ≥ 1); the
models carry foreign ids but never invent their own. Idempotency comes from logical keys
(`pi_core.ids.logical_key`, SHA-256 hex over a length-prefixed, UTC-normalised encoding):

| Key | Natural key | DB |
|---|---|---|
| `OfferObservation.idempotency_key` | `source_context_id`, `source_listing_id`, `seller_id`, `observed_at`, `correction_of` | `UNIQUE (idempotency_key, observed_at)` |
| `ListingRecord.natural_key` | `source_id`, `source_listing_key` | `UNIQUE (source_id, source_listing_key)` |

The crawl run is not part of the observation key: a retried run that re-observes the same
instant is the same fact (DAT-09). `source_context` covers channel, location and cohort.

## Differences from the DB schema (PR4)

Names match `pi_db` migration 0001. Where they deliberately differ:

- `Evidence.ladder_rung_used` / `fetch_method` have no column yet. A run can escalate part-way,
  so the method belongs on each evidence row (ADR-0003); proposed for a follow-up migration.
- `Evidence.retention_until` is optional here; the pipeline fills it from the retention policy
  before insert (the column is `NOT NULL`).
- `OfferObservation.quality_status` is `None` until the quality gate runs; the pipeline must set
  it explicitly rather than rely on the column default.
- `ListingRecord.category_path_source` is a tuple; the column is `text`, so it is joined on write
  unless the column becomes `text[]`.
- Prices may be negative here so the quality gate can see and quarantine them; the table's
  `CHECK (>= 0)` is the last line of defence.
