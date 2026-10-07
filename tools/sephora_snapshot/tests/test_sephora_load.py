"""Loader contract on synthetic snapshot folders, against a throwaway migrated database.

Needs PI_DATABASE_URL (``make up``); skips when unset or unreachable, except in CI.
"""

import json
import os
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from sephora_snapshot.load import MARKETS, BundleCountryError, Loader, market_from_args
from sephora_synth import details, pdp_rec, trpc_rec, write_part
from sqlalchemy.engine import make_url

from pi_db import DATABASE_URL_ENV, alembic_config


def _libpq(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


@pytest.fixture(scope="module")
def db() -> Iterator[str]:
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        pytest.skip(f"{DATABASE_URL_ENV} not set; run `make up` and export it")
    try:
        psycopg.connect(_libpq(url), connect_timeout=3).close()
    except psycopg.OperationalError:
        if os.environ.get("CI"):
            raise
        pytest.skip("database unreachable (run `make up`)")
    name = f"pi_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(_libpq(url), autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    test_url = make_url(url).set(database=name).render_as_string(hide_password=False)
    try:
        command.upgrade(alembic_config(test_url), "head")
        yield _libpq(test_url)
    finally:
        with psycopg.connect(_libpq(url), autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


def _folder(root: Path, progress: dict[str, Any]) -> Path:
    root.mkdir(parents=True)
    started = {"started": "2026-09-30T21:00:00+00:00", "updated": "2026-09-30T23:00:00+00:00"}
    (root / "progress.json").write_text(json.dumps({**started, **progress}))
    return root


def _load(conn: psycopg.Connection[Any], root: Path, *, finish: bool = True) -> dict[str, int]:
    ld = Loader(conn, root, f"gs://test-bucket/{root.name}")
    stats = ld.load()
    if finish:
        ld.finish()
    return stats


def _runs(conn: psycopg.Connection[Any], name: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT manifest_uri, status FROM crawl_run WHERE manifest_uri LIKE %s",
        (f"gs://test-bucket/{name}/%",),
    ).fetchall()
    return {uri.rsplit("=", 1)[1]: status for uri, status in rows}


FULL: dict[str, Any] = {
    "stopped": "complete",
    "mode": "full",
    "limit": 0,
    "trpc": True,
    "counts": {
        "sitemap_ok": 80,
        "seed_pids": 2,
        "seed_en": 2,
        "seed_ar": 0,
        "pdp_en_ok": 2,
        "trpc_http_200": 2,
    },
}


def _full_folder(root: Path, **changes: Any) -> Path:
    counts = {**FULL["counts"], **changes.pop("counts", {})}
    root = _folder(root, {**FULL, **changes, "counts": counts})
    write_part(root, "pdp_en", [pdp_rec("P100", "en"), pdp_rec("P101", "en")])
    write_part(root, "trpc", [trpc_rec("P100"), trpc_rec("P101", in_stock=False)])
    return root


def test_full_run_loads_prices_then_stock_and_replays_idempotently(db: str, tmp_path: Path) -> None:
    root = _full_folder(tmp_path / "full")
    write_part(root, "pdp_en", [pdp_rec("P100", "en"), pdp_rec("P101", "en")])
    write_part(root, "trpc", [trpc_rec("P100"), trpc_rec("P101", in_stock=False)])
    with psycopg.connect(db) as conn:
        assert _load(conn, root) == {"pdp_en": 2, "trpc": 2}
        states: dict[str, str] = dict(
            conn.execute(
                "SELECT l.source_listing_key, o.availability_state FROM offer_observation o"
                " JOIN source_listing l ON l.id=o.source_listing_id WHERE o.price_current IS NULL"
            ).fetchall()
        )
        assert states == {"1001": "in_stock", "1011": "out_of_stock"}
        price = conn.execute(
            "SELECT price_current, price_regular_stated, availability_state FROM offer_observation"
            " WHERE price_current IS NOT NULL LIMIT 1"
        ).fetchone()
        assert price is not None
        assert (float(price[0]), float(price[1]), price[2]) == (80.0, 100.0, "not_observed")
        assert _runs(conn, "full") == {"en": "succeeded"}  # no AR rows: no AR crawl_run
        # replay after the ledger is lost: nothing is duplicated
        (root.parent / ".loaded-full.json").unlink()
        _load(conn, root)
        n = conn.execute("SELECT count(*) FROM offer_observation").fetchone()
        assert n == (4,)


@pytest.mark.parametrize(
    "changes",
    [
        {"limit": 50},  # LIMIT run
        {"trpc": False},  # no stock pass
        {"mode": None, "limit": None, "trpc": None},  # written before these were recorded
        {"stopped": "sigterm"},
        {"stopped": "cutoff"},
        {"counts": {"sitemap_fail": 1}},
        {"counts": {"transport_error": 1}},
        {"counts": {"block_rate_limited": 1}},  # a 429 backoff skipped an item
        {"counts": {"pdp_en_http_404": 1}},
        {"counts": {"pdp_en_parse_error": 1}},
        {"counts": {"trpc_http_500": 1}},
        {"counts": {"hop_host_refused": 1}},  # a redirect left the storefront host
        {"counts": {"hop_robots_refused": 1}},
        {"counts": {"host_refused": 1}},  # a seed URL off the storefront, never requested
        {"counts": {"too_large": 1}},  # a page over its byte cap was dropped
        {"counts": {"seed_en": 3}},  # a seeded page never fetched
        {"counts": {"trpc_http_200": 1}},  # a stock read missing
    ],
)
def test_succeeded_is_strict(db: str, tmp_path: Path, changes: dict[str, Any]) -> None:
    name = f"strict-{uuid.uuid4().hex[:8]}"
    root = _full_folder(tmp_path / name, **changes)
    with psycopg.connect(db) as conn:
        _load(conn, root)
        assert _runs(conn, name) == {"en": "partial"}


def test_stock_for_an_unloaded_listing_keeps_the_part_for_a_retry(db: str, tmp_path: Path) -> None:
    root = _folder(tmp_path / "late", {"stopped": "cutoff"})
    write_part(root, "trpc", [trpc_rec("P400")])
    with psycopg.connect(db) as conn:
        assert _load(conn, root, finish=False) == {"trpc": 0, "trpc_missing_listing": 1}
        ledger = root.parent / ".loaded-late.json"
        assert not ledger.exists() or "trpc/part-0000.jsonl.gz" not in ledger.read_text()
        write_part(root, "pdp_en", [pdp_rec("P400", "en")])
        assert _load(conn, root) == {"pdp_en": 1, "trpc": 1}
        assert "trpc/part-0000.jsonl.gz" in ledger.read_text()


def test_price_without_currency_is_unknown_not_aed(db: str, tmp_path: Path) -> None:
    d = details("P500")
    del d["currency"]
    d["c_variantsInfo"][0]["c_price"] = 99.95
    root = _folder(tmp_path / "nocur", {"stopped": "cutoff"})
    write_part(root, "pdp_en", [pdp_rec("P500", "en", d)])
    with psycopg.connect(db) as conn:
        assert _load(conn, root)["price_without_currency"] == 1
        row = conn.execute(
            "SELECT o.price_current, o.currency, o.field_state ->> 'price_current'"
            " FROM offer_observation o JOIN source_listing l ON l.id = o.source_listing_id"
            " WHERE l.source_listing_key = '5001'"
        ).fetchone()
        assert row == (None, None, "unknown")


@pytest.mark.parametrize(
    ("pid", "sale", "expected"),
    [
        ("P701", "$undefined", (Decimal("99.95"), None, "full", "AED", None)),
        ("P702", "$83:props:offers", (None, None, None, None, "unknown")),
        ("P703", "on sale", (None, None, None, None, "unknown")),
        ("P704", {"value": 80}, (None, None, None, None, "unknown")),
        ("P705", [80], (None, None, None, None, "unknown")),
    ],
)
def test_a_reduced_price_left_as_a_reference_makes_the_price_unknown(
    db: str, tmp_path: Path, pid: str, sale: Any, expected: tuple[Any, ...]
) -> None:
    d = details(pid)
    d["currency"] = "AED"
    d["c_variantsInfo"][0] |= {"c_price": 99.95, "c_salesPrice": sale}
    root = _folder(tmp_path / "ref", {"stopped": "cutoff"})
    write_part(root, "pdp_en", [pdp_rec(pid, "en", d)])
    with psycopg.connect(db) as conn:
        stats = _load(conn, root)
        assert stats.get("sale_price_unreadable", 0) == (0 if expected[4] is None else 1)
        row = conn.execute(
            "SELECT o.price_current, o.price_promo, o.price_type, o.currency,"
            " o.field_state ->> 'price_current'"
            " FROM offer_observation o JOIN source_listing l ON l.id = o.source_listing_id"
            " WHERE l.source_listing_key = %s",
            (f"{pid[1:]}1",),
        ).fetchone()
        assert row == expected


def test_prices_are_read_as_exact_decimals(db: str, tmp_path: Path) -> None:
    d = details("P600")
    d["c_variantsInfo"][0] |= {"c_price": 1234.5678, "c_salesPrice": None}
    root = _folder(tmp_path / "dec", {"stopped": "cutoff"})
    write_part(root, "pdp_en", [pdp_rec("P600", "en", d)])
    with psycopg.connect(db) as conn:
        _load(conn, root)
        row = conn.execute(
            "SELECT o.price_current FROM offer_observation o JOIN source_listing l"
            " ON l.id = o.source_listing_id WHERE l.source_listing_key = '6001'"
        ).fetchone()
        assert row is not None
        assert str(row[0]) == "1234.5678"


def test_plan_run_is_partial_even_when_complete(db: str, tmp_path: Path) -> None:
    progress = {"stopped": "complete", "counts": {"plan_pids": 1, "pdp_ar_ok": 1}}
    root = _folder(tmp_path / "plan", progress)
    write_part(root, "pdp_ar", [pdp_rec("P200", "ar")])
    with psycopg.connect(db) as conn:
        _load(conn, root)
        assert _runs(conn, "plan") == {"ar": "partial"}


def test_blocked_run_is_partial(db: str, tmp_path: Path) -> None:
    progress = {"stopped": "challenge: marker at x", "counts": {"block_challenge": 1}}
    root = _folder(tmp_path / "blocked", progress)
    write_part(root, "pdp_en", [pdp_rec("P300", "en")])
    with psycopg.connect(db) as conn:
        _load(conn, root)
        assert _runs(conn, "blocked") == {"en": "partial"}
        blocked = conn.execute(
            "SELECT blocked_count FROM crawl_run WHERE manifest_uri LIKE 'gs://test-bucket/blocked/%'"
        ).fetchone()
        assert blocked == (1,)


def test_variant_without_a_stock_state_is_counted_not_observed(db: str, tmp_path: Path) -> None:
    root = _folder(tmp_path / "nostate", {"stopped": "cutoff"})
    write_part(root, "pdp_en", [pdp_rec("P700", "en")])
    write_part(root, "trpc", [trpc_rec("P700", in_stock=None)])
    with psycopg.connect(db) as conn:
        assert _load(conn, root) == {"pdp_en": 1, "trpc": 0, "trpc_instock_unknown": 1}


def test_stock_read_with_null_data_records_nothing_and_blocks_succeeded(
    db: str, tmp_path: Path
) -> None:
    name = f"null-{uuid.uuid4().hex[:8]}"
    root = _full_folder(tmp_path / name)
    null = trpc_rec("P101")
    null["json"][0]["result"]["data"]["json"] = None  # what sephora.me sends for some products
    write_part(root, "trpc", [trpc_rec("P100"), null])
    with psycopg.connect(db) as conn:
        stats = _load(conn, root)
        assert (stats["trpc"], stats["trpc_no_data"]) == (1, 1)
        assert _runs(conn, name) == {"en": "partial"}
        ledger = root.parent / f".loaded-{name}.json"
        assert "trpc/part-0000.jsonl.gz" not in ledger.read_text()


def test_product_level_claims_are_kept_in_labels(db: str, tmp_path: Path) -> None:
    d = details("P800")
    d |= {
        "c_responsibleBeauty": ["clean"],
        "c_moreInformation": "These products are vegan.",
        "c_notes": "musk and vanilla",
    }
    root = _folder(tmp_path / "claims", {"stopped": "cutoff"})
    write_part(root, "pdp_en", [pdp_rec("P800", "en", d)])
    with psycopg.connect(db) as conn:
        _load(conn, root)
        rows = conn.execute(
            "SELECT c.labels FROM listing_content c JOIN source_listing l"
            " ON l.id = c.listing_id WHERE l.source_listing_key = %s",
            ("8001",),
        ).fetchall()
        assert [(r["responsible_beauty"], r["more_information"], r["notes"]) for (r,) in rows] == [
            (["clean"], "These products are vegan.", "musk and vanilla")
        ]


def test_a_brand_row_another_source_owns_is_never_written(db: str, tmp_path: Path) -> None:
    """Owner rule (2026-10-01): a Sephora load never updates a row another source (ulta_ae)
    created, not even with identical values; xmin catches a no-op rewrite."""
    root = _folder(tmp_path / "clash", {"stopped": "cutoff"})
    shared = details("P900", brand="Clash Brand")
    write_part(root, "pdp_en", [pdp_rec("P900", "en", shared)])
    write_part(root, "pdp_ar", [pdp_rec("P900", "ar", shared)])
    with psycopg.connect(db) as conn:
        conn.execute(
            "INSERT INTO brand (name, aliases) VALUES ('Clash Brand', ARRAY['ulta_ae:Clash Brand'])"
        )
        conn.commit()
        query = "SELECT xmin::text, name, name_ar, aliases FROM brand WHERE name = 'Clash Brand'"
        before = conn.execute(query).fetchall()
        stats = _load(conn, root)
        conn.commit()
        assert conn.execute(query).fetchall() == before
        assert stats["brand_name_clash"] == 1
        assert conn.execute("SELECT count(*) FROM brand WHERE name = 'Clash Brand'").fetchone() == (
            1,
        )


def test_a_sephora_brand_is_created_once_and_reused(db: str, tmp_path: Path) -> None:
    root = _folder(tmp_path / "own", {"stopped": "cutoff"})
    write_part(
        root,
        "pdp_en",
        [pdp_rec(p, "en", details(p, brand="Own Brand")) for p in ("P910", "P911")],
    )
    with psycopg.connect(db) as conn:
        stats = _load(conn, root)
        rows = conn.execute("SELECT aliases FROM brand WHERE name = 'Own Brand'").fetchall()
        assert rows == [(["sephora_me:b1"],)]
        assert "brand_name_clash" not in stats


def _en_then_ar(conn: psycopg.Connection[Any], root: Path, pid: str, d: dict[str, Any]) -> int:
    """An EN load, then a separate AR load (as production runs them); returns the AR skips."""
    write_part(_folder(root / "en", {"stopped": "cutoff"}), "pdp_en", [pdp_rec(pid, "en", d)])
    _load(conn, root / "en")
    write_part(_folder(root / "ar", {"stopped": "cutoff"}), "pdp_ar", [pdp_rec(pid, "ar", d)])
    stats = _load(conn, root / "ar")
    conn.commit()
    return stats.get("brand_name_ar_skipped", 0)


def test_a_brand_row_shared_with_another_source_is_never_written(db: str, tmp_path: Path) -> None:
    """A row carrying both a sephora_me: and a ulta_ae: alias (the Ulta loader merges aliases on
    a name clash) gets no AR name and no new row version from Sephora loads."""
    d = details("P920", brand="Shared Brand") | {"c_brand": {"id": "b920", "name": "Shared Brand"}}
    with psycopg.connect(db) as conn:
        conn.execute(
            "INSERT INTO brand (name, aliases) VALUES"
            " ('Shared Brand', ARRAY['sephora_me:b920', 'ulta_ae:Shared Brand'])"
        )
        conn.commit()
        query = "SELECT xmin::text, name, name_ar, aliases FROM brand WHERE name = 'Shared Brand'"
        before = conn.execute(query).fetchall()
        assert _en_then_ar(conn, tmp_path, "P920", d) == 1
        assert conn.execute(query).fetchall() == before
        assert before[0][2] is None


def test_a_sephora_only_brand_gets_its_arabic_name_once(db: str, tmp_path: Path) -> None:
    d = details("P930", brand="Solo Brand") | {"c_brand": {"id": "b930", "name": "Solo Brand"}}
    with psycopg.connect(db) as conn:
        assert _en_then_ar(conn, tmp_path / "1", "P930", d) == 0
        query = "SELECT xmin::text, name_ar FROM brand WHERE name = 'Solo Brand'"
        first = conn.execute(query).fetchall()
        assert first[0][1] == "Solo Brand"
        assert _en_then_ar(conn, tmp_path / "2", "P930", d) == 1
        assert conn.execute(query).fetchall() == first


# ---------------------------------------------------------------- Saudi storefront (--country SA)


def _load_sa(conn: psycopg.Connection[Any], root: Path) -> dict[str, int]:
    ld = Loader(conn, root, f"gs://test-bucket/{root.name}", MARKETS["SA"])
    stats = ld.load()
    ld.finish()
    return stats


def _sar(pid: str, brand: str = "Acme Beauty") -> dict[str, Any]:
    return details(pid, brand=brand) | {"currency": "SAR"}


def test_a_saudi_load_is_its_own_source_and_never_touches_uae_listings(
    db: str, tmp_path: Path
) -> None:
    """The same variant id on both storefronts: two listings, two contexts, UAE rows unchanged."""
    ae = _folder(tmp_path / "ae", {"stopped": "cutoff"})
    write_part(ae, "pdp_en", [pdp_rec("P700", "en")])
    sa = _folder(tmp_path / "sa", {"stopped": "cutoff", "country": "SA"})
    write_part(sa, "pdp_en", [pdp_rec("P700", "en", _sar("P700"))])
    with psycopg.connect(db) as conn:
        _load(conn, ae)
        conn.commit()
        uae = (
            "SELECT l.xmin::text, l.last_seen_at FROM source_listing l JOIN source s"
            " ON s.id = l.source_id WHERE s.name = 'sephora_me' AND l.source_listing_key = '7001'"
        )
        before = conn.execute(uae).fetchall()
        assert _load_sa(conn, sa)["pdp_en"] == 1  # the shared brand row is a counted clash
        conn.commit()
        assert conn.execute(uae).fetchall() == before
        rows = conn.execute(
            "SELECT s.name, c.country, c.locale, c.time_zone, o.currency, o.price_current"
            " FROM offer_observation o JOIN source_context c ON c.id = o.source_context_id"
            " JOIN source s ON s.id = c.source_id JOIN source_listing l"
            " ON l.id = o.source_listing_id WHERE l.source_listing_key = '7001' ORDER BY s.name"
        ).fetchall()
        assert [r[:5] for r in rows] == [
            ("sephora_me", "AE", "en-AE", "Asia/Dubai", "AED"),
            ("sephora_sa", "SA", "en-SA", "Asia/Riyadh", "SAR"),
        ]
        (sa.parent / ".loaded-sa.json").unlink()
        _load_sa(conn, sa)  # replay after the ledger is lost: nothing new
        n = conn.execute(
            "SELECT count(*) FROM offer_observation o JOIN source_listing l"
            " ON l.id = o.source_listing_id WHERE l.source_listing_key = '7001'"
        ).fetchone()
        assert n == (2,)


def test_a_price_in_another_currency_is_unknown_in_a_saudi_load(db: str, tmp_path: Path) -> None:
    root = _folder(tmp_path / "sa-aed", {"stopped": "cutoff", "country": "SA"})
    write_part(root, "pdp_en", [pdp_rec("P710", "en")])  # an AED page
    with psycopg.connect(db) as conn:
        assert _load_sa(conn, root)["price_currency_mismatch"] == 1
        row = conn.execute(
            "SELECT o.price_current, o.currency, o.field_state ->> 'price_current'"
            " FROM offer_observation o JOIN source_listing l ON l.id = o.source_listing_id"
            " WHERE l.source_listing_key = '7101'"
        ).fetchone()
        assert row == (None, None, "unknown")


def test_a_saudi_load_never_writes_a_uae_brand_row(db: str, tmp_path: Path) -> None:
    """A brand the UAE load created is not the Saudi source's row: counted, never rewritten."""
    ae = _folder(tmp_path / "bae", {"stopped": "cutoff"})
    write_part(ae, "pdp_en", [pdp_rec("P720", "en", details("P720", brand="Gulf Brand"))])
    sa = _folder(tmp_path / "bsa", {"stopped": "cutoff", "country": "SA"})
    write_part(sa, "pdp_en", [pdp_rec("P720", "en", _sar("P720", brand="Gulf Brand"))])
    write_part(sa, "pdp_ar", [pdp_rec("P720", "ar", _sar("P720", brand="Gulf Brand"))])
    with psycopg.connect(db) as conn:
        _load(conn, ae)
        conn.commit()
        query = "SELECT xmin::text, name_ar, aliases FROM brand WHERE name = 'Gulf Brand'"
        before = conn.execute(query).fetchall()
        assert _load_sa(conn, sa)["brand_name_clash"] == 1
        conn.commit()
        assert conn.execute(query).fetchall() == before


def test_a_saudi_only_brand_carries_the_saudi_alias(db: str, tmp_path: Path) -> None:
    root = _folder(tmp_path / "bsolo", {"stopped": "cutoff", "country": "SA"})
    write_part(root, "pdp_en", [pdp_rec("P730", "en", _sar("P730", brand="Riyadh Brand"))])
    with psycopg.connect(db) as conn:
        stats = _load_sa(conn, root)
        assert "brand_name_clash" not in stats
        rows = conn.execute("SELECT aliases FROM brand WHERE name = 'Riyadh Brand'").fetchall()
        assert rows == [(["sephora_sa:b1"],)]


@pytest.mark.parametrize(
    ("args", "source"),
    [([], "sephora_me"), (["--finish"], "sephora_me"), (["--country", "sa"], "sephora_sa")],
)
def test_country_flag(args: list[str], source: str) -> None:
    assert market_from_args(args).source == source


@pytest.mark.parametrize("args", [["--country"], ["--country", "KW"]])
def test_an_unknown_country_is_refused(args: list[str]) -> None:
    with pytest.raises(SystemExit):
        market_from_args(args)


def _sources(conn: psycopg.Connection[Any]) -> int:
    row = conn.execute("SELECT count(*) FROM source").fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.parametrize(
    ("recorded", "market"),
    [({"country": "SA"}, "AE"), ({"country": "AE"}, "SA"), ({}, "SA")],
)
def test_a_bundle_from_another_storefront_is_refused_before_any_write(
    db: str, tmp_path: Path, recorded: dict[str, str], market: str
) -> None:
    root = _folder(
        tmp_path / f"mismatch-{market}-{len(recorded)}", {"stopped": "cutoff", **recorded}
    )
    write_part(root, "pdp_en", [pdp_rec("P740", "en", _sar("P740"))])
    with psycopg.connect(db) as conn:
        before = _sources(conn)
        with pytest.raises(BundleCountryError, match="nothing was written"):
            Loader(conn, root, f"gs://test-bucket/{root.name}", MARKETS[market])
        assert _sources(conn) == before
        conn.rollback()


def test_a_bundle_without_a_recorded_country_still_loads_as_uae(db: str, tmp_path: Path) -> None:
    root = _folder(tmp_path / "legacy-ae", {"stopped": "cutoff"})
    write_part(root, "pdp_en", [pdp_rec("P750", "en")])
    with psycopg.connect(db) as conn:
        assert _load(conn, root)["pdp_en"] == 1


def _coverage(conn: psycopg.Connection[Any], locale: str) -> str:
    row = conn.execute(
        "SELECT coverage_status::text FROM source_context sc JOIN source s ON s.id = sc.source_id"
        " WHERE s.name = 'sephora_me' AND sc.country = 'AE' AND sc.locale = %s"
        " AND sc.valid_to IS NULL",
        (locale,),
    ).fetchone()
    assert row is not None
    return str(row[0])


def _reset_coverage(conn: psycopg.Connection[Any]) -> None:
    """The module shares one database, so each coverage test starts from 'partial'."""
    conn.execute(
        "UPDATE source_context SET coverage_status = 'partial' WHERE source_id ="
        " (SELECT id FROM source WHERE name = 'sephora_me')"
    )
    conn.commit()


def test_a_complete_full_run_makes_its_context_supported(db: str, tmp_path: Path) -> None:
    name = f"cov-{uuid.uuid4().hex[:8]}"
    root = _full_folder(tmp_path / name)
    with psycopg.connect(db) as conn:
        _load(conn, root, finish=False)  # creates the contexts
        _reset_coverage(conn)
        Loader(conn, root, f"gs://test-bucket/{name}").finish()
        assert _runs(conn, name) == {"en": "succeeded"}
        assert _coverage(conn, "en-AE") == "supported"
        assert _coverage(conn, "ar-AE") == "partial"  # no AR run in this folder


def test_a_complete_full_run_with_arabic_pages_supports_both_contexts(
    db: str, tmp_path: Path
) -> None:
    name = f"cov-ar-{uuid.uuid4().hex[:8]}"
    root = _full_folder(tmp_path / name, counts={"seed_ar": 1, "pdp_ar_ok": 1})
    write_part(root, "pdp_ar", [pdp_rec("P100", "ar")])
    with psycopg.connect(db) as conn:
        _load(conn, root, finish=False)
        _reset_coverage(conn)
        Loader(conn, root, f"gs://test-bucket/{name}").finish()
        assert _runs(conn, name) == {"en": "succeeded", "ar": "succeeded"}
        assert (_coverage(conn, "en-AE"), _coverage(conn, "ar-AE")) == ("supported", "supported")


@pytest.mark.parametrize(
    "changes",
    [
        {"counts": {"block_challenge": 1}, "stopped": "challenge: marker at x"},  # blocked
        {"counts": {"seed_en": 3}},  # part of the sitemap never fetched
        {"stopped": "cutoff"},  # cut short
        {"limit": 50},  # a sample, not the whole sitemap
    ],
)
def test_a_run_short_of_the_full_sitemap_leaves_coverage_partial(
    db: str, tmp_path: Path, changes: dict[str, Any]
) -> None:
    name = f"cov-short-{uuid.uuid4().hex[:8]}"
    root = _full_folder(tmp_path / name, **changes)
    with psycopg.connect(db) as conn:
        _load(conn, root, finish=False)
        _reset_coverage(conn)
        Loader(conn, root, f"gs://test-bucket/{name}").finish()
        assert _runs(conn, name) == {"en": "partial"}
        assert _coverage(conn, "en-AE") == "partial"


def test_a_partial_run_after_a_complete_one_keeps_supported_and_is_itself_partial(
    db: str, tmp_path: Path
) -> None:
    full, short = f"cov-a-{uuid.uuid4().hex[:8]}", f"cov-b-{uuid.uuid4().hex[:8]}"
    with psycopg.connect(db) as conn:
        _load(conn, _full_folder(tmp_path / full), finish=False)
        _reset_coverage(conn)
        _load(conn, tmp_path / full)
        assert _coverage(conn, "en-AE") == "supported"
        _load(conn, _full_folder(tmp_path / short, stopped="cutoff"))
        assert _runs(conn, short) == {"en": "partial"}
        assert _coverage(conn, "en-AE") == "supported"


# ---------------------------------------------------------------- price decision (no database)

_D = Decimal


@pytest.mark.parametrize(
    ("market", "variant", "currency", "expected", "counter"),
    [
        ("AE", {"c_price": 100}, "AED", (_D(100), _D(100), None, False, None), None),
        (
            "AE",
            {"c_price": 100, "c_salesPrice": 80},
            "AED",
            (_D(80), _D(100), _D(80), True, None),
            None,
        ),
        # a sale at or above the regular price is no promotion: the regular price is paid
        (
            "AE",
            {"c_price": 100, "c_salesPrice": 100},
            "AED",
            (_D(100), _D(100), _D(100), False, None),
            None,
        ),
        (
            "AE",
            {"c_price": 100, "c_salesPrice": "$undefined"},
            "AED",
            (_D(100), _D(100), None, False, None),
            None,
        ),
        (
            "AE",
            {"c_price": 100, "c_salesPrice": "$83:props:offers"},
            "AED",
            (None, None, None, False, "unknown"),
            "sale_price_unreadable",
        ),
        # the unreadable sale wins over a missing currency: one counter per variant
        (
            "AE",
            {"c_price": 100, "c_salesPrice": "$83:props:offers"},
            None,
            (None, None, None, False, "unknown"),
            "sale_price_unreadable",
        ),
        (
            "AE",
            {"c_price": 100},
            None,
            (None, None, None, False, "unknown"),
            "price_without_currency",
        ),
        (
            "AE",
            {"c_price": 100},
            "",
            (None, None, None, False, "unknown"),
            "price_without_currency",
        ),
        (
            "SA",
            {"c_price": 100},
            "AED",
            (None, None, None, False, "unknown"),
            "price_currency_mismatch",
        ),
        ("SA", {"c_price": 100}, "SAR", (_D(100), _D(100), None, False, None), None),
        ("AE", {}, "AED", (None, None, None, False, "not_published"), None),
        ("AE", {}, None, (None, None, None, False, "not_published"), None),
    ],
)
def test_the_price_decision_stores_no_price_it_is_unsure_of(
    market: str,
    variant: dict[str, Any],
    currency: str | None,
    expected: tuple[Any, ...],
    counter: str | None,
) -> None:
    loader = Loader.__new__(Loader)  # _prices reads only the market and bumps stats
    loader.market, loader.stats = MARKETS[market], {}
    assert loader._prices(variant, currency) == expected
    assert loader.stats == ({counter: 1} if counter else {})
