"""Behaviour of schema v1 against a real PostgreSQL 16 + pgvector database."""

from datetime import UTC, datetime
from decimal import Decimal

import psycopg
import pytest
from psycopg import errors

import pi_core
from pi_db import APP_ROLE, IMAGE_EMBEDDING_DIM, TEXT_EMBEDDING_DIM

pytestmark = pytest.mark.db

Conn = psycopg.Connection[tuple[object, ...]]

PI_CORE_ENUMS = {
    "availability_state": pi_core.AvailabilityState,
    "field_state": pi_core.FieldState,
    "price_type": pi_core.PriceType,
    "tax_status": pi_core.TaxStatus,
    "channel": pi_core.Channel,
    "match_class": pi_core.MatchClass,
    "review_state": pi_core.ReviewState,
    "quality_status": pi_core.QualityStatus,
    "coverage_status": pi_core.CoverageStatus,
}


def _one(conn: Conn, sql: str, params: tuple[object, ...] = ()) -> object:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return row[0]


def _seed(conn: Conn) -> dict[str, object]:
    """Minimal parent rows an observation needs."""
    source = _one(conn, "INSERT INTO source (name, kind) VALUES ('Sephora ME', 'web') RETURNING id")
    context = _one(
        conn,
        "INSERT INTO source_context (source_id, country, channel, locale, time_zone)"
        " VALUES (%s, 'SA', 'online', 'en-SA', 'Asia/Riyadh') RETURNING id",
        (source,),
    )
    run = _one(
        conn,
        "INSERT INTO crawl_run (source_context_id, connector_version, ladder_rung_used, started_at)"
        " VALUES (%s, '0.1.0', 0, now()) RETURNING id",
        (context,),
    )
    listing = _one(
        conn,
        "INSERT INTO source_listing (source_id, source_listing_key, url, name_original,"
        " first_seen_at, last_seen_at) VALUES (%s, 'P123', 'https://example.test/p/123',"
        " 'Lipstick', now(), now()) RETURNING id",
        (source,),
    )
    return {"run": run, "context": context, "listing": listing}


def _observe(
    conn: Conn,
    seed: dict[str, object],
    observed_at: datetime,
    key: str = "k1",
    field_state: str = "{}",
    on_conflict: str = "",
) -> object:
    row = conn.execute(
        "INSERT INTO offer_observation (idempotency_key, crawl_run_id, source_context_id,"
        " source_listing_id, observed_at, ingested_at, price_current, price_type, currency,"
        " availability_state, field_state)"
        " VALUES (%s, %s, %s, %s, %s, now(), %s, 'full', 'SAR', 'in_stock', %s::jsonb)"
        f" {on_conflict} RETURNING tableoid::regclass::text",
        (
            key,
            seed["run"],
            seed["context"],
            seed["listing"],
            observed_at,
            Decimal("129.5000"),
            field_state,
        ),
    ).fetchone()
    return None if row is None else row[0]


# ------------------------------------------------------------------ enums and types


@pytest.mark.parametrize(("pg_type", "enum"), PI_CORE_ENUMS.items())
def test_db_enum_matches_pi_core(conn: Conn, pg_type: str, enum: type[pi_core.FieldState]) -> None:
    labels = _one(conn, f"SELECT enum_range(NULL::{pg_type})::text[]")
    assert labels == [m.value for m in enum]


@pytest.mark.parametrize(
    ("current", "max_allowed"), [(0, 1), (1, 0)], ids=["max_allowed", "current"]
)
def test_ladder_rung_range_matches_pi_core(conn: Conn, current: int, max_allowed: int) -> None:
    top = max(pi_core.LadderRung)
    source = _one(conn, "INSERT INTO source (name, kind) VALUES ('s', 'web') RETURNING id")
    sql = (
        "INSERT INTO source_context (source_id, country, channel, locale, time_zone,"
        " ladder_rung_current, ladder_rung_max_allowed)"
        " VALUES (%s, 'AE', 'online', 'en-AE', 'Asia/Dubai', %s, %s)"
    )
    conn.execute(sql, (source, top, top))
    with pytest.raises(errors.CheckViolation):
        conn.execute(sql, (source, top + current, top + max_allowed))


def test_vector_dimensions(conn: Conn) -> None:
    rows = conn.execute(
        "SELECT attrelid::regclass::text || '.' || attname, atttypmod FROM pg_attribute"
        " JOIN pg_class c ON c.oid = attrelid"
        " WHERE atttypid = 'vector'::regtype AND attnum > 0 AND c.relkind = 'r'"
    ).fetchall()
    assert {row[0]: row[1] for row in rows} == {
        "image.embedding": IMAGE_EMBEDDING_DIM,
        "variant.text_embedding": TEXT_EMBEDDING_DIM,
    }


def test_money_columns_are_numeric_18_4(conn: Conn) -> None:
    rows = conn.execute(
        "SELECT column_name, numeric_precision, numeric_scale FROM information_schema.columns"
        " WHERE table_name = 'offer_observation' AND data_type = 'numeric'"
        " AND column_name LIKE 'price\\_%'"
    ).fetchall()
    assert {r[0] for r in rows} == {
        "price_current",
        "price_regular_stated",
        "price_promo",
        "price_member",
    }
    assert {(r[1], r[2]) for r in rows} == {(18, 4)}


def test_price_requires_currency(conn: Conn) -> None:
    seed = _seed(conn)
    with pytest.raises(errors.CheckViolation):
        conn.execute(
            "INSERT INTO offer_observation (idempotency_key, crawl_run_id, source_context_id,"
            " source_listing_id, observed_at, ingested_at, price_current, availability_state)"
            " VALUES ('x', %s, %s, %s, now(), now(), 1, 'unknown')",
            (seed["run"], seed["context"], seed["listing"]),
        )


# ------------------------------------------------------------------ field_state


def test_field_state_accepts_known_reasons(conn: Conn) -> None:
    seed = _seed(conn)
    state = '{"price_member": "not_published", "rating_value": "parse_failure"}'
    assert _observe(conn, seed, datetime(2026, 10, 1, tzinfo=UTC), field_state=state)


@pytest.mark.parametrize("state", ['{"price_member": "missing"}', '{"a": 1}', "[]"])
def test_field_state_rejects_unknown_reasons(conn: Conn, state: str) -> None:
    seed = _seed(conn)
    with pytest.raises(errors.CheckViolation):
        _observe(conn, seed, datetime(2026, 10, 1, tzinfo=UTC), field_state=state)


# ------------------------------------------------------------------ partitions and idempotency


@pytest.mark.parametrize(
    ("observed_at", "partition"),
    [
        (datetime(2026, 1, 1, tzinfo=UTC), "offer_observation_p202601"),
        (datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC), "offer_observation_p202610"),
        (datetime(2027, 12, 15, tzinfo=UTC), "offer_observation_p202712"),
        (datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC), "offer_observation_default"),
        (datetime(2028, 1, 1, tzinfo=UTC), "offer_observation_default"),
    ],
)
def test_partition_routing(conn: Conn, observed_at: datetime, partition: str) -> None:
    assert _observe(conn, _seed(conn), observed_at) == partition


def test_ensure_partition_creates_new_month(conn: Conn) -> None:
    name = _one(conn, "SELECT pi_ensure_offer_observation_partition(date '2028-02-10')")
    assert name == "offer_observation_p202802"
    assert _one(conn, "SELECT pi_ensure_offer_observation_partition(date '2028-02-01')") == name
    assert _observe(conn, _seed(conn), datetime(2028, 2, 29, tzinfo=UTC)) == name


def test_replay_is_idempotent(conn: Conn) -> None:
    seed = _seed(conn)
    at = datetime(2026, 11, 5, 8, tzinfo=UTC)
    replay = "ON CONFLICT (idempotency_key, observed_at) DO NOTHING"
    assert _observe(conn, seed, at, on_conflict=replay) is not None
    assert _observe(conn, seed, at, on_conflict=replay) is None
    assert _one(conn, "SELECT count(*) FROM offer_observation") == 1
    with pytest.raises(errors.UniqueViolation):
        _observe(conn, seed, at)


# ------------------------------------------------------------------ append-only


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE offer_observation SET price_current = 1",
        "DELETE FROM offer_observation",
        "TRUNCATE offer_observation",
        "UPDATE audit_log SET actor = 'x'",
    ],
)
def test_app_role_cannot_rewrite_history(conn: Conn, statement: str) -> None:
    _observe(conn, _seed(conn), datetime(2026, 10, 1, tzinfo=UTC))
    conn.execute(f"SET ROLE {APP_ROLE}")
    with pytest.raises(errors.InsufficientPrivilege):
        conn.execute(statement)


def test_app_role_can_insert_and_read_observations(conn: Conn) -> None:
    seed = _seed(conn)
    conn.execute(f"SET ROLE {APP_ROLE}")
    assert _observe(conn, seed, datetime(2026, 10, 1, tzinfo=UTC)) == "offer_observation_p202610"
    assert _one(conn, "SELECT count(*) FROM offer_observation") == 1
    conn.execute("INSERT INTO audit_log (actor, action) VALUES ('pipeline', 'load')")
    conn.execute("UPDATE source SET notes = 'registers stay editable'")


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE offer_observation SET quality_status = 'corrected'",
        "DELETE FROM offer_observation",
    ],
)
def test_owner_cannot_rewrite_observations(conn: Conn, statement: str) -> None:
    _observe(conn, _seed(conn), datetime(2026, 10, 1, tzinfo=UTC))
    with pytest.raises(errors.InsufficientPrivilege, match="append-only"):
        conn.execute(statement)


def test_correction_is_a_new_row(conn: Conn) -> None:
    seed = _seed(conn)
    at = datetime(2026, 10, 1, tzinfo=UTC)
    _observe(conn, seed, at)
    original = _one(conn, "SELECT observation_id FROM offer_observation")
    conn.execute(
        "INSERT INTO offer_observation (idempotency_key, crawl_run_id, source_context_id,"
        " source_listing_id, observed_at, ingested_at, availability_state, quality_status,"
        " correction_of) VALUES ('k1-fix', %s, %s, %s, %s, now(), 'out_of_stock',"
        " 'corrected', %s)",
        (seed["run"], seed["context"], seed["listing"], at, original),
    )
    assert _one(conn, "SELECT count(*) FROM offer_observation") == 2


def test_match_edge_is_canonically_ordered(conn: Conn) -> None:
    brand = _one(conn, "INSERT INTO brand (name) VALUES ('NARS') RETURNING id")
    family = _one(
        conn,
        "INSERT INTO product_family (brand_id, name_normalized) VALUES (%s, 'blush') RETURNING id",
        (brand,),
    )
    a, b = (
        _one(conn, "INSERT INTO variant (family_id) VALUES (%s) RETURNING id", (family,))
        for _ in range(2)
    )
    with pytest.raises(errors.CheckViolation):
        conn.execute(
            "INSERT INTO match_edge (variant_a, variant_b, match_class, algo_version)"
            " VALUES (%s, %s, 'exact', 'v1')",
            (b, a),
        )
