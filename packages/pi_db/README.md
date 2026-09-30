# pi_db — database schema (blueprint §5)

Alembic migrations (psycopg 3) for PostgreSQL 16 + pgvector. Run `make up`, export
`PI_DATABASE_URL` (see `.env.example`), then `uv run alembic -c packages/pi_db/alembic.ini upgrade head`.
DB tests are marked `db` and skip when `PI_DATABASE_URL` is unset.

## Decisions

- **Location: `packages/pi_db`, not `db/` (blueprint §14).** The migrations need importable
  constants (`IMAGE_EMBEDDING_DIM`, `TEXT_EMBEDDING_DIM`, role names) and an enum-parity test
  against `pi_core.enums`. As a uv workspace member they get the same ruff / mypy --strict /
  coverage gates as every other package, and Dagster and the API can import them. `db/` stays
  reserved for dbt when it arrives.
- **Market-agnostic.** No country, currency or time zone is hard-coded in the schema. The pilot
  market (UAE) lives in data (`source_context`), not DDL.
- **`offer_observation.correction_of` has no FK.** A foreign key into a partitioned table must
  include the partition key (`observed_at`). Corrections are validated in the loader instead.
- **Deferred to a later migration:** `alert_rule`, `alert_event`, `user_entitlement` (§5.1 alerting
  and entitlements). They land with the features that use them, together with row-level
  security by role, brand and market (SEC-02).

## Contracts for writers

- **Partitions first (DAT-13, SRC-15).** `offer_observation` has monthly UTC partitions for
  2026-01..2027-12 and **no default partition**, so a row for any other month fails with
  "no partition of relation found" instead of being parked where it could never be moved.
  Before inserting a batch, the loader calls `pi_ensure_offer_observation_partition(month)`
  for each distinct `observed_at` month. That includes pre-2026 backfill months. `pi_app`
  may call it: the function is `SECURITY DEFINER` with a fixed `search_path`, and an advisory
  lock serialises concurrent callers. Creating a partition briefly takes an ACCESS EXCLUSIVE
  lock on `offer_observation`, so a scheduled job should pre-create upcoming months rather
  than leaving it to the hot path.
- **Idempotency (DAT-09, SRC-10).** `idempotency_key` is the pipeline's hash of the logical
  observation key (DAT-02 grain). `observed_at` must come from the evidence (`retrieved_at`
  or the source's own timestamp) and must never be re-stamped with `now()` on retry. Then a
  replay hits `UNIQUE (idempotency_key, observed_at)` and `ON CONFLICT DO NOTHING` is a
  no-op. A re-stamped `observed_at` would create a duplicate logical observation.
- **Missing is data (DQ-02); money is never zero (cross-PR contract with pi_core #6).** Every
  price (`price_current`, `price_regular_stated`, `price_promo`, `price_member`,
  `unit_price_derived`, `promotion.min_spend`) is NULL or strictly > 0. A NULL `price_current`
  needs a `field_state` reason (`CHECK (price_current IS NOT NULL OR field_state ?
  'price_current')`). Any stated price needs a currency, and `min_spend` needs
  `min_spend_currency`. `price_type = 'range'` if and only if `price_range_min` and
  `price_range_max` are both set, with 0 < min <= max (PRC-13). `price_current` is NULL
  (with a `field_state` reason, e.g. `not_applicable`) when `price_type` is `range` or
  `quote_only`.
- **Quality gate.** `quality_status` is nullable with no default: NULL means "not yet
  quality-gated". The gate (PR10) sets it, so nothing is silently published as `accepted`.
- **No false stock-outs (DAT-06, contract point 2 v2).** A negative availability claim
  (`out_of_stock`, `removed`, `not_deliverable`) requires
  `field_state->>'availability_state' = 'observed'`: availability was actually seen on the
  page. It is rejected under `blocked`, `parse_failure`, `unknown`, any other state, or no
  entry. Other fields' states do not gate availability; a page-level block must set
  availability's own state to `blocked` (the connector/normaliser owns that).
  `observed` is valid only on qualified fields (`availability_state`), never as a null
  reason. `(availability_state = 'low_stock') = (low_stock_flag IS TRUE)`.
- **Append-only history (DAT-01, DAT-04).** `pi_app` has only INSERT/SELECT on `evidence`,
  `listing_content`, `review_summary`, `offer_observation`, `offer_promotion`, `audit_log`
  and `decision_log`. Owner-level triggers also reject UPDATE, DELETE and TRUNCATE
  (including `TRUNCATE ... CASCADE` and TRUNCATE of a single partition). The only exception
  is deleting `evidence` rows past `retention_until` (DAT-10). Corrections are new rows with
  `correction_of`. The owner can still DROP or DETACH objects; that is a migration, and
  migrations are reviewed.
- **Match graph (MAT-05, MAT-07, MAT-08).** There is one current edge (`valid_to IS NULL`)
  per variant pair, so a rejected or locked verdict cannot be undercut by a new proposal.
  To supersede an edge, close its `valid_to` and insert the new one.
- **Ladder audit (ADR-0003).** Every `evidence` row records `ladder_rung_used` and
  `fetch_method`, per request, because the ladder escalates request by request and the rung
  can vary within a `crawl_run`. The method determines the rung (enforced by CHECK, and equal
  to `pi_core.FetchMethod.rung`). Rung 3 (stealth browsers) is disabled program-wide: it stays
  in the numbering for audit but is rejected on `evidence`, `crawl_run` and
  `source_context.ladder_rung_current`. `ladder_rung_max_allowed` may still be 4, and
  escalation skips 3. No fetch method maps to rung 3, and rung 1 is `plain_http` (normal
  headers, no fingerprint impersonation).
- **Partition window.** `pi_ensure_offer_observation_partition()` refuses months before
  2000-01 or 24+ months ahead, so a garbled timestamp cannot mint a stray partition.
- **Ratings** are stored as published, with their `rating_scale` (5, 10, 100 …), and are
  bounded by it. Normalisation happens downstream.

## Deviations from blueprint §5.1 (additive)

- `evidence.ladder_rung_used`, `evidence.fetch_method` (+ `fetch_method` enum): per-request
  ladder audit, see above.
- `offer_observation.price_range_min` / `price_range_max`: range prices (PRC-13).
- `review.rating_scale`, `offer_observation.rating_scale`: ratings keep their source scale.

## Migration notes

`0001` creates everything on an empty database, so it takes no locks on existing data and
rewrites nothing. Downgrade drops all objects except the `pi_app` role and the `vector`
extension, which are cluster- or database-wide.

Open follow-up for the evidence retention job: `offer_observation.evidence_id` and
`promotion.evidence_id` reference `evidence`, so expired rows that are still referenced can't
be deleted. The retention job will purge the stored payload (`storage_uri`) and keep the row,
or a later migration will split the payload pointer out.
