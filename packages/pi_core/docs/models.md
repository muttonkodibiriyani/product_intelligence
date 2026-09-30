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

## Ids

Ids are UUIDv5 from the natural key (`pi_core.ids.stable_id`, fixed namespace), exposed as
properties rather than fields, so a record cannot carry an id that contradicts its key.

| Id | Natural key |
|---|---|
| `ListingRecord.listing_id` | `source_id`, `source_listing_key` |
| `OfferObservation.observation_id` | `source_context_id`, `source_listing_id`, `seller_id`, `observed_at`, `correction_of` |
| `Evidence.id` | `crawl_run_id`, `url`, `content_hash` |
| `PromotionRecord.promotion_id` | `source_context_id`, `terms_original`, `code`, `advertised_from` |

The crawl run is not part of the observation key: a retried run that re-observes the same
instant is the same fact (DAT-09). `source_context` covers channel, location and cohort.

## Notes for the DB schema (PR4)

- Store the derived ids above as `uuid` primary keys, computed with `pi_core.ids`.
- `evidence` gains `ladder_rung_used smallint` and `fetch_method text`: a run can escalate
  part-way, so the method is recorded per evidence row, not only per `crawl_run`.
- `promotion` gains `currency char(3)`, required when `min_spend` is set.
- `source_context` has no currency column; it is derived from `country` (`SA`→SAR, `AE`→AED).
- `offer_observation.quality_status` is null until the quality gate runs.
