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
| Every price (`price_*`, `unit_price_derived`, `min_spend`, instalment) is `None` or `> 0`; missing is never zero | `types.PositiveAmount` | DQ-02, PRC-16 |
| `price_type=range` ⇔ `price_range_min`/`max` set, `0 < min <= max`, and no `price_current` | `observation` | PRC-01, PRC-13 |
| `field_state["availability_state"]` in {blocked, parse_failure, unknown} ⇒ not `out_of_stock` | `observation.NO_STOCK_CLAIM_REASONS` | DAT-06 |
| `(availability_state = low_stock) = (low_stock_flag IS TRUE)` | `observation` | DAT-06 |
| `rating_value`/`rating_scale` both set or both null, `numeric(7,2)`, `0 <= value <= scale` | `observation` | — |
| Rung 3 (`STEALTH_BROWSER`) is forbidden regardless of any cap; rung 1 is plain HTTP, normal headers | `enums.FORBIDDEN_RUNGS` | ADR-0003, owner ruling |
| One `currency` per record; `money()` returns `Money` in it; the context's currency comes from its market | `observation`, `context` | PRC-03, PRC-07 |
| Datetimes must be timezone-aware and are normalised to UTC | `types.UtcDatetime` | DAT-03 |
| A tracked field is `None` exactly when `field_state` gives a reason | `base.FieldStateModel` | DQ-02, DAT-06 |
| Rung and fetch method always agree; the rung may not exceed the context's cap (paid is opt-in) | `context.check_rung` | ADR-0003 |
| `field_state` keys are tracked fields, plus `availability_state` as a qualifier | `base.FieldStateModel` | DQ-02 |
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

## Contract with the DB schema (pi_db, #5)

Names and constraints match `pi_db` migration 0001 per the coordinator's cross-PR contract:
positive prices, range bounds, no false stock-outs, low-stock agreement, evidence
`ladder_rung_used`/`fetch_method` (`NOT NULL`, per request), `promotion.min_spend_currency`,
nullable `quality_status` with no default, rating `numeric(7,2)` + `rating_scale`, rung 3
refused. `FetchMethod` values are locked: `site_api`, `embedded_json`, `sitemap` (0),
`plain_http` (1), `playwright` (2), `egress_variation` (4), `residential_proxy` (5).

Deliberate model-only differences:

- `Evidence.retention_until` is optional here; the pipeline fills it from the retention policy
  before insert.
- `ListingRecord.category_path_source` is a tuple; it is joined on write while the column is
  `text`.
