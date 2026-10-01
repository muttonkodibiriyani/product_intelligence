"""Behaviour of schema v1 against a real PostgreSQL 16 + pgvector database."""

import os
import shutil
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

import psycopg
import pytest
from alembic import command
from psycopg import errors
from sqlalchemy.engine import make_url

import pi_core
from pi_db import APP_ROLE, IMAGE_EMBEDDING_DIM, TEXT_EMBEDDING_DIM, alembic_config
from pi_db.migrations.versions.v0001_schema_v1 import APPEND_ONLY_TABLES, SCHEMA_ENUMS, TABLES
from pi_db.migrations.versions.v0003_offline_import import NEW_FETCH_METHODS

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
        " VALUES (%s, 'AE', 'online', 'en-AE', 'Asia/Dubai') RETURNING id",
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
        " availability_state, field_state, quality_status)"
        " VALUES (%s, %s, %s, %s, %s, now(), %s, 'full', 'AED', 'in_stock', %s::jsonb,"
        " 'accepted')"
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


OBS_DEFAULTS: dict[str, object] = {
    "price_current": Decimal("129.5000"),
    "price_type": "full",
    "currency": "AED",
    "availability_state": "in_stock",
    "field_state": "{}",
    "quality_status": "accepted",
}


def _obs(conn: Conn, seed: dict[str, object], **cols: object) -> object:
    """Insert one observation, overriding OBS_DEFAULTS; a None override omits the column.

    Returns the new observation_id."""
    values = {
        "idempotency_key": f"k-{sorted(cols.items())}",
        "crawl_run_id": seed["run"],
        "source_context_id": seed["context"],
        "source_listing_id": seed["listing"],
        "observed_at": datetime(2026, 10, 1, tzinfo=UTC),
        "ingested_at": datetime(2026, 10, 1, tzinfo=UTC),
        **OBS_DEFAULTS,
        **cols,
    }
    values = {k: v for k, v in values.items() if v is not None}
    names = ", ".join(values)
    marks = ", ".join("%s::jsonb" if k == "field_state" else "%s" for k in values)
    sql = f"INSERT INTO offer_observation ({names}) VALUES ({marks}) RETURNING observation_id"
    return _one(conn, sql, tuple(values.values()))


def _rejected(
    conn: Conn, error: type[Exception], sql: str, params: tuple[object, ...] = ()
) -> None:
    conn.execute("SAVEPOINT s")
    with pytest.raises(error):
        conn.execute(sql, params)
    conn.execute("ROLLBACK TO SAVEPOINT s")


def _history(conn: Conn) -> dict[str, object]:
    """One row in every append-only table (evidence still inside its retention window)."""
    seed = _seed(conn)
    at = datetime(2026, 10, 1, tzinfo=UTC)
    _observe(conn, seed, at)
    observation = _one(conn, "SELECT observation_id FROM offer_observation")
    conn.execute(
        "INSERT INTO evidence (crawl_run_id, url, content_hash, storage_uri, retrieved_at,"
        " ladder_rung_used, fetch_method, retention_until)"
        " VALUES (%s, 'u', 'h1', 'gs://b/1', %s, 0, 'site_api', now() + interval '1 year')",
        (seed["run"], at),
    )
    conn.execute(
        "INSERT INTO listing_content (listing_id, observed_at, content_hash) VALUES (%s, %s, 'c')",
        (seed["listing"], at),
    )
    conn.execute(
        "INSERT INTO review_summary (listing_id, observed_at) VALUES (%s, %s)",
        (seed["listing"], at),
    )
    promotion = _one(
        conn,
        "INSERT INTO promotion (source_context_id, mechanic, first_seen_at, last_seen_at)"
        " VALUES (%s, 'percent_off', %s, %s) RETURNING id",
        (seed["context"], at, at),
    )
    conn.execute(
        "INSERT INTO offer_promotion (observation_id, observed_at, promotion_id)"
        " VALUES (%s, %s, %s)",
        (observation, at, promotion),
    )
    conn.execute("INSERT INTO audit_log (actor, action) VALUES ('pipeline', 'load')")
    conn.execute("INSERT INTO decision_log (decided_by, subject, decision) VALUES ('o', 's', 'd')")
    return seed


# ------------------------------------------------------------------ enums and types


@pytest.mark.parametrize(("pg_type", "enum"), PI_CORE_ENUMS.items())
def test_db_enum_matches_pi_core(conn: Conn, pg_type: str, enum: type[StrEnum]) -> None:
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
        "price_range_min",
        "price_range_max",
    }
    assert {(r[1], r[2]) for r in rows} == {(18, 4)}


def test_price_requires_currency(conn: Conn) -> None:
    seed = _seed(conn)
    with pytest.raises(errors.CheckViolation):
        conn.execute(
            "INSERT INTO offer_observation (idempotency_key, crawl_run_id, source_context_id,"
            " source_listing_id, observed_at, ingested_at, price_current, availability_state,"
            " quality_status) VALUES ('x', %s, %s, %s, now(), now(), 1, 'unknown', 'accepted')",
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
    ],
)
def test_partition_routing(conn: Conn, observed_at: datetime, partition: str) -> None:
    assert _observe(conn, _seed(conn), observed_at) == partition


def test_there_is_no_default_partition(conn: Conn) -> None:
    assert _one(conn, "SELECT count(*) FROM pg_partitioned_table WHERE partdefid <> 0") == 0


@pytest.mark.parametrize(
    "observed_at",
    [datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC), datetime(2028, 1, 1, tzinfo=UTC)],
    ids=["before", "after"],
)
def test_row_outside_partitions_fails_loudly(conn: Conn, observed_at: datetime) -> None:
    seed = _seed(conn)
    with pytest.raises(errors.CheckViolation, match="no partition"):
        _observe(conn, seed, observed_at)


def test_backfill_month_is_created_then_routed(conn: Conn) -> None:
    """SRC-15: pre-2026 history keeps its real dates in its own month."""
    seed = _seed(conn)
    at = datetime(2025, 6, 14, 9, tzinfo=UTC)
    conn.execute(f"SET ROLE {APP_ROLE}")
    name = _one(conn, "SELECT pi_ensure_offer_observation_partition(%s::date)", (at,))
    assert name == "offer_observation_p202506"
    assert _observe(conn, seed, at) == name


def test_new_partition_keeps_history_protection(conn: Conn) -> None:
    name = _one(conn, "SELECT pi_ensure_offer_observation_partition(date '2028-05-01')")
    _observe(conn, _seed(conn), datetime(2028, 5, 2, tzinfo=UTC))
    for statement in (f"UPDATE {name} SET quality_status = 'warning'", f"TRUNCATE {name} CASCADE"):
        conn.execute("SAVEPOINT s")
        with pytest.raises(errors.InsufficientPrivilege, match=f"{name} is append-only"):
            conn.execute(statement)
        conn.execute("ROLLBACK TO SAVEPOINT s")


def test_ensure_partition_is_race_safe(migrated_db: str) -> None:
    """Two loaders asking for the same new month: the second waits, then reuses it."""
    url = make_url(migrated_db).set(drivername="postgresql").render_as_string(hide_password=False)
    # A backfill month: never pre-created, and always inside the permitted window.
    ensure = "SELECT pi_ensure_offer_observation_partition(date '2003-03-01')"
    with psycopg.connect(url) as first, psycopg.connect(url) as second:
        first.execute(f"SET ROLE {APP_ROLE}")
        second.execute(f"SET ROLE {APP_ROLE}")
        first.execute(ensure)  # holds the advisory lock until commit
        with ThreadPoolExecutor(1) as pool:
            waiting = pool.submit(lambda: second.execute(ensure).fetchone())
            with pytest.raises(TimeoutError):
                waiting.result(timeout=0.5)
            first.commit()
            assert waiting.result(timeout=10) == ("offer_observation_p200303",)
        second.commit()


def test_ensure_partition_is_not_public(conn: Conn) -> None:
    conn.execute("CREATE ROLE pi_test_nobody NOLOGIN")
    conn.execute("SET ROLE pi_test_nobody")
    with pytest.raises(errors.InsufficientPrivilege):
        conn.execute("SELECT pi_ensure_offer_observation_partition(date '2029-01-01')")


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
        "TRUNCATE offer_observation_p202610 CASCADE",
        "TRUNCATE crawl_run CASCADE",
        "UPDATE evidence SET content_hash = 'tampered'",
        "DELETE FROM evidence",
        "UPDATE listing_content SET description = 'x'",
        "DELETE FROM review_summary",
        "DELETE FROM offer_promotion",
        # Plain TRUNCATE already fails on foreign keys; CASCADE is the real risk.
        *(f"TRUNCATE {table} CASCADE" for table in APPEND_ONLY_TABLES),
        "UPDATE audit_log SET actor = 'x'",
        "DELETE FROM decision_log",
    ],
)
def test_owner_cannot_rewrite_history(conn: Conn, statement: str) -> None:
    _history(conn)
    with pytest.raises(errors.InsufficientPrivilege, match="append-only"):
        conn.execute(statement)


def test_evidence_past_retention_can_be_deleted(conn: Conn) -> None:
    ids = _history(conn)
    conn.execute(
        "INSERT INTO evidence (crawl_run_id, url, content_hash, storage_uri, retrieved_at,"
        " ladder_rung_used, fetch_method, retention_until) VALUES (%s, 'u', 'h2', 'gs://b/2',"
        " now() - interval '2 years', 2, 'playwright', now() - interval '1 day')",
        (ids["run"],),
    )
    deleted = conn.execute("DELETE FROM evidence WHERE retention_until < now()").rowcount
    assert deleted == 1


def test_missing_price_needs_a_reason(conn: Conn) -> None:
    seed = _seed(conn)
    sql = (
        "INSERT INTO offer_observation (idempotency_key, crawl_run_id, source_context_id,"
        " source_listing_id, observed_at, ingested_at, availability_state, quality_status,"
        " field_state) VALUES (%s, %s, %s, %s, now(), now(), 'blocked', 'accepted', %s::jsonb)"
    )
    params = (seed["run"], seed["context"], seed["listing"])
    conn.execute(sql, ("with-reason", *params, '{"price_current": "blocked"}'))
    with pytest.raises(errors.CheckViolation):
        conn.execute(sql, ("silent", *params, "{}"))


def test_quality_status_is_null_until_gated(conn: Conn) -> None:
    """No default: an ungated row is NULL, never silently 'accepted' (PR10 sets it)."""
    observation = _obs(conn, _seed(conn), quality_status=None)
    status = _one(
        conn,
        "SELECT quality_status FROM offer_observation WHERE observation_id = %s",
        (observation,),
    )
    assert status is None


@pytest.mark.parametrize(
    ("rating", "scale", "ok"),
    [("4.5", "5", True), ("87", "100", True), ("6", "5", False), ("4.5", None, False)],
)
def test_ratings_carry_their_scale(conn: Conn, rating: str, scale: str | None, ok: bool) -> None:
    listing = _seed(conn)["listing"]
    sql = (
        "INSERT INTO review (listing_id, source_review_id, rating, rating_scale)"
        " VALUES (%s, 'r1', %s::numeric, %s::numeric)"
    )
    if ok:
        conn.execute(sql, (listing, rating, scale))
    else:
        with pytest.raises(errors.CheckViolation):
            conn.execute(sql, (listing, rating, scale))


def test_correction_chain_is_indexed(conn: Conn) -> None:
    definition = _one(
        conn,
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'offer_observation_correction_idx'",
    )
    assert "(correction_of) WHERE (correction_of IS NOT NULL)" in str(definition)


def test_correction_is_a_new_row(conn: Conn) -> None:
    seed = _seed(conn)
    at = datetime(2026, 10, 1, tzinfo=UTC)
    _observe(conn, seed, at)
    original = _one(conn, "SELECT observation_id FROM offer_observation")
    conn.execute(
        "INSERT INTO offer_observation (idempotency_key, crawl_run_id, source_context_id,"
        " source_listing_id, observed_at, ingested_at, availability_state, quality_status,"
        " field_state, correction_of) VALUES ('k1-fix', %s, %s, %s, %s, now(), 'out_of_stock',"
        ' \'corrected\', \'{"price_current": "not_applicable",'
        ' "availability_state": "observed"}\', %s)',
        (seed["run"], seed["context"], seed["listing"], at, original),
    )
    assert _one(conn, "SELECT count(*) FROM offer_observation") == 2


def _variants(conn: Conn) -> tuple[object, object]:
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
    return a, b


def test_one_current_match_edge_per_pair(conn: Conn) -> None:
    """MAT-07: a rejected pair cannot get a competing current proposal."""
    a, b = _variants(conn)
    insert = (
        "INSERT INTO match_edge (variant_a, variant_b, match_class, algo_version, review_state)"
        " VALUES (%s, %s, %s, 'v1', %s) RETURNING id"
    )
    rejected = _one(conn, insert, (a, b, "exact", "rejected"))
    conn.execute("SAVEPOINT s")
    with pytest.raises(errors.UniqueViolation):
        conn.execute(insert, (a, b, "substitute", "proposed"))
    conn.execute("ROLLBACK TO SAVEPOINT s")
    conn.execute(
        "UPDATE match_edge SET valid_to = now() + interval '1 second' WHERE id = %s", (rejected,)
    )
    assert _one(conn, insert, (a, b, "family", "approved"))


def test_match_edge_is_canonically_ordered(conn: Conn) -> None:
    a, b = _variants(conn)
    with pytest.raises(errors.CheckViolation):
        conn.execute(
            "INSERT INTO match_edge (variant_a, variant_b, match_class, algo_version)"
            " VALUES (%s, %s, 'exact', 'v1')",
            (b, a),
        )


# ------------------------------------------------------------------ cross-PR contract (#5/#6)


@pytest.mark.parametrize(
    "column",
    ["price_current", "price_regular_stated", "price_promo", "price_member", "unit_price_derived"],
)
def test_prices_are_never_zero(conn: Conn, column: str) -> None:
    """Missing is NULL plus a reason, never 0."""
    seed = _seed(conn)
    with pytest.raises(errors.CheckViolation):
        _obs(conn, seed, **{column: Decimal(0)})


def test_min_spend_is_positive_and_has_currency(conn: Conn) -> None:
    context = _seed(conn)["context"]
    sql = (
        "INSERT INTO promotion (source_context_id, mechanic, min_spend, min_spend_currency,"
        " first_seen_at, last_seen_at) VALUES (%s, 'spend_get', %s, %s, now(), now())"
    )
    conn.execute(sql, (context, Decimal(200), "AED"))
    _rejected(conn, errors.CheckViolation, sql, (context, Decimal(0), "AED"))
    _rejected(conn, errors.CheckViolation, sql, (context, Decimal(200), None))


NO_CURRENT = '{"price_current": "not_applicable"}'


@pytest.mark.parametrize(
    ("price_type", "low", "high", "ok"),
    [
        ("range", "10", "20", True),
        ("range", "15", "15", True),
        ("range", "20", "10", False),
        ("range", "0", "10", False),
        ("range", None, None, False),
        ("range", "10", None, False),
        ("full", "10", "20", False),
    ],
)
def test_range_price_bounds(
    conn: Conn, price_type: str, low: str | None, high: str | None, ok: bool
) -> None:
    """PRC-13: a range keeps both bounds, 0 < min <= max, and only for price_type range."""
    seed = _seed(conn)
    cols = {
        "price_type": price_type,
        "price_range_min": None if low is None else Decimal(low),
        "price_range_max": None if high is None else Decimal(high),
    }
    if price_type == "range":
        cols |= {"price_current": None, "field_state": NO_CURRENT}
    if ok:
        assert _obs(conn, seed, **cols)
    else:
        with pytest.raises(errors.CheckViolation):
            _obs(conn, seed, **cols)


@pytest.mark.parametrize(
    ("price_type", "current", "ok"),
    [
        ("range", None, True),
        ("quote_only", None, True),
        ("range", "129.5", False),
        ("quote_only", "129.5", False),
        ("full", "129.5", True),
    ],
)
def test_range_and_quote_only_have_no_current_price(
    conn: Conn, price_type: str, current: str | None, ok: bool
) -> None:
    """Contract (b): price_current IS NULL for range and quote_only prices."""
    seed = _seed(conn)
    cols: dict[str, object] = {
        "price_type": price_type,
        "price_current": None if current is None else Decimal(current),
        "field_state": NO_CURRENT if current is None else "{}",
    }
    if price_type == "range":
        cols |= {"price_range_min": Decimal(10), "price_range_max": Decimal(20)}
    if ok:
        assert _obs(conn, seed, **cols)
    else:
        with pytest.raises(errors.CheckViolation):
            _obs(conn, seed, **cols)


SEEN = '"availability_state": "observed"'


@pytest.mark.parametrize(
    ("state", "field_state", "ok"),
    [
        # Negative claims are allowed only when availability itself was observed.
        ("out_of_stock", f"{{{SEEN}}}", True),
        ("removed", f"{{{SEEN}}}", True),
        ("not_deliverable", f"{{{SEEN}}}", True),
        ("out_of_stock", "{}", False),
        ("out_of_stock", '{"availability_state": "blocked"}', False),
        ("out_of_stock", '{"availability_state": "parse_failure"}', False),
        ("out_of_stock", '{"availability_state": "unknown"}', False),
        ("out_of_stock", '{"availability_state": "restricted"}', False),
        ("removed", '{"availability_state": "blocked"}', False),
        ("not_deliverable", '{"availability_state": "unknown"}', False),
        # Other fields' states do not gate availability: the page loaded, the price widget
        # failed.
        ("out_of_stock", f'{{{SEEN}, "price_current": "blocked"}}', True),
        ("out_of_stock", '{"price_current": "blocked"}', False),
        # Non-negative states need no observation qualifier.
        ("in_stock", "{}", True),
        ("blocked", '{"availability_state": "blocked"}', True),
        ("unknown", '{"availability_state": "unknown"}', True),
    ],
)
def test_no_false_stock_outs(conn: Conn, state: str, field_state: str, ok: bool) -> None:
    """DAT-06, contract point 2 v2: negative state => availability field_state = observed."""
    seed = _seed(conn)
    cols: dict[str, object] = {"availability_state": state, "field_state": field_state}
    if "price_current" in field_state:
        cols["price_current"] = None
    if ok:
        assert _obs(conn, seed, **cols)
    else:
        with pytest.raises(errors.CheckViolation):
            _obs(conn, seed, **cols)


@pytest.mark.parametrize(
    "field_state",
    [
        '{"price_current": "observed"}',
        '{"price_member": "observed"}',
        '{"rating_value": "observed"}',
    ],
)
def test_observed_is_never_a_null_reason(conn: Conn, field_state: str) -> None:
    """'observed' qualifies availability_state only; it never explains a NULL."""
    seed = _seed(conn)
    with pytest.raises(errors.CheckViolation):
        _obs(conn, seed, price_current=None, field_state=field_state)


@pytest.mark.parametrize(
    ("state", "flag", "ok"),
    [
        ("low_stock", True, True),
        ("in_stock", False, True),
        ("in_stock", None, True),
        ("low_stock", None, False),
        ("low_stock", False, False),
        ("in_stock", True, False),
    ],
)
def test_low_stock_flag_agrees(conn: Conn, state: str, flag: bool | None, ok: bool) -> None:
    """Contract (c): (availability_state = 'low_stock') = (low_stock_flag IS TRUE)."""
    seed = _seed(conn)
    cols = {"availability_state": state, "low_stock_flag": flag}
    if ok:
        assert _obs(conn, seed, **cols)
    else:
        with pytest.raises(errors.CheckViolation):
            _obs(conn, seed, **cols)


@pytest.mark.parametrize(
    ("rung", "method", "ok"),
    [
        (0, "site_api", True),
        (1, "plain_http", True),
        (2, "playwright", True),
        (4, "egress_variation", True),
        (5, "residential_proxy", True),
        (0, "offline_import", True),
        (1, "offline_import", False),
        (1, "playwright", False),
        (3, "playwright", False),
        (2, "egress_variation", False),
    ],
)
def test_evidence_records_rung_and_method(conn: Conn, rung: int, method: str, ok: bool) -> None:
    """ADR-0003: per-request rung and method agree, and rung 3 is never usable."""
    run = _seed(conn)["run"]
    sql = (
        "INSERT INTO evidence (crawl_run_id, url, content_hash, storage_uri, retrieved_at,"
        " ladder_rung_used, fetch_method, retention_until)"
        " VALUES (%s, 'u', 'h', 's', now(), %s, %s, now() + interval '1 year')"
    )
    if ok:
        conn.execute(sql, (run, rung, method))
    else:
        _rejected(conn, errors.CheckViolation, sql, (run, rung, method))


def test_forbidden_rung_is_rejected_everywhere(conn: Conn) -> None:
    seed = _seed(conn)
    _rejected(
        conn,
        errors.CheckViolation,
        "INSERT INTO crawl_run (source_context_id, connector_version, ladder_rung_used,"
        " started_at) VALUES (%s, '0.1.0', 3, now())",
        (seed["context"],),
    )
    _rejected(
        conn,
        errors.CheckViolation,
        "UPDATE source_context SET ladder_rung_current = 3, ladder_rung_max_allowed = 4"
        " WHERE id = %s",
        (seed["context"],),
    )
    # The cap may sit above the forbidden rung; escalation skips it.
    conn.execute(
        "UPDATE source_context SET ladder_rung_current = 4, ladder_rung_max_allowed = 4"
        " WHERE id = %s",
        (seed["context"],),
    )


def test_fetch_method_enum_matches_migration(conn: Conn) -> None:
    labels = _one(conn, "SELECT enum_range(NULL::fetch_method)::text[]")
    # 0001's labels, then the ones 0003 appended (ALTER TYPE ... ADD VALUE appends).
    expected = SCHEMA_ENUMS["fetch_method"] + NEW_FETCH_METHODS
    assert tuple(labels) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize("month", ["1999-12-01", "2099-01-01"])
def test_ensure_partition_refuses_implausible_months(conn: Conn, month: str) -> None:
    with pytest.raises(errors.InvalidParameterValue, match="outside"):
        conn.execute("SELECT pi_ensure_offer_observation_partition(%s::date)", (month,))


# ------------------------------------------------------------------ backup and restore
def _libpq(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def _tools() -> tuple[str, str]:
    pg_dump, pg_restore = shutil.which("pg_dump"), shutil.which("pg_restore")
    if pg_dump is None or pg_restore is None:
        if os.environ.get("CI"):
            pytest.fail("pg_dump/pg_restore must be on PATH in CI")
        pytest.skip("pg_dump/pg_restore not installed")
    return pg_dump, pg_restore


def _snapshot(url: str) -> dict[str, object]:
    with psycopg.connect(_libpq(url)) as conn:
        counts: dict[str, object] = {t: _one(conn, f"SELECT count(*) FROM {t}") for t in TABLES}
        counts["partitions"] = _one(
            conn, "SELECT count(*) FROM pg_inherits WHERE inhparent = 'offer_observation'::regclass"
        )
        counts["field_state_check"] = _one(
            conn,
            "SELECT count(*) FROM pg_constraint"
            " WHERE conname = 'offer_observation_field_state_check'"
            " AND convalidated",
        )
    return counts


def test_plain_dump_restores_into_a_fresh_database(empty_db: str, server_url: str) -> None:
    """A plain ``pg_dump -Fc | pg_restore`` round-trips (pg_restore runs with search_path='').

    Regression for 0001's unqualified ``NULL::field_state`` in the inlined CHECK function, which
    failed the restore at ATTACH PARTITION (fixed in 0002).
    """
    pg_dump, pg_restore = _tools()
    command.upgrade(alembic_config(empty_db), "head")
    with psycopg.connect(_libpq(empty_db)) as conn:
        seed = _seed(conn)
        _observe(
            conn, seed, datetime(2026, 10, 1, tzinfo=UTC), field_state='{"price_was": "unknown"}'
        )
        _observe(conn, seed, datetime(2026, 11, 1, tzinfo=UTC), key="k2")
    target = f"pi_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(_libpq(server_url), autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{target}"')
    target_url = make_url(empty_db).set(database=target).render_as_string(hide_password=False)
    try:
        dump = subprocess.run(  # noqa: S603 -- fixed argv, test database only
            [pg_dump, "-Fc", f"--dbname={_libpq(empty_db)}"], check=True, capture_output=True
        )
        restore = subprocess.run(  # noqa: S603
            [pg_restore, "--exit-on-error", "--no-owner", f"--dbname={_libpq(target_url)}"],
            input=dump.stdout,
            capture_output=True,
            check=False,
        )
        assert restore.returncode == 0, restore.stderr.decode(errors="replace")
        assert _snapshot(target_url) == _snapshot(empty_db)
        assert _snapshot(target_url)["offer_observation"] == 2
    finally:
        with psycopg.connect(_libpq(server_url), autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{target}" WITH (FORCE)')
