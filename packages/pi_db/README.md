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
  and entitlements). They land with the features that use them, together with row-level security by role, brand and market.

## Migration notes

`0001` creates everything on an empty database, so it takes no locks on existing data and
rewrites nothing. Downgrade drops all objects. Partitions pre-exist for 2026-01..2027-12 plus a
default partition. `pi_ensure_offer_observation_partition()` creates later months.
