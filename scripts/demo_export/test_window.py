"""Crawl windows in the exporter (``--run``, ADR-0013): explicit run identity, values from the
window, stock from the price capture's run and Dubai day (option A), retained listings marked and
covered, and each retailer's own window, fields and capabilities."""

from __future__ import annotations

# ruff: noqa: S101
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from pi_core.enums import NotObservedReason
from pi_dataset import DatasetV3, OfferV3, dump_dataset, load_any
from scripts.demo_export.export import ListingRow, UltaContext, parse_runs, window_report
from scripts.demo_export.test_export import row
from scripts.demo_export.test_v2 import NOTE
from scripts.demo_export.v2 import build_dataset_v2, crawl_windows, to_v3

SEPHORA, ULTA, OUNASS = "sephora_me", "ulta_ae", "ounass_ae"
BLOCKED = UltaContext(blocked_since=datetime(2026, 9, 30, 20, 55, tzinfo=UTC))


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def seen(
    listing: ListingRow,
    price_at: datetime,
    *,
    run: int = 7,
    stock_at: datetime | None = None,
    stock_run: int | None = None,
) -> ListingRow:
    """``listing`` with its price captured at ``price_at`` and its stock at ``stock_at`` (else
    with the price), both by ``run`` unless ``stock_run`` says otherwise."""
    stock_at = price_at if stock_at is None else stock_at
    return replace(
        listing,
        observed_at=max(price_at, stock_at),
        evidence_retrieved_at=max(price_at, stock_at),
        run_id=run,
        price_observed_at=price_at,
        price_evidence_retrieved_at=price_at,
        price_run_id=run,
        stock_observed_at=stock_at,
        stock_evidence_retrieved_at=stock_at,
        stock_run_id=run if stock_run is None else stock_run,
    )


def export(listing: list[ListingRow], runs: dict[str, tuple[int, ...]] | None = None) -> DatasetV3:
    """What ``main`` does with ``--run``: windows, v2, v3, then the publisher's strict load."""
    windows = crawl_windows(listing, runs)
    v2 = build_dataset_v2(
        listing,
        [],
        generated_at=max(w.end for w in windows.values()) + timedelta(hours=1),
        ulta=BLOCKED,
        ulta_note=NOTE,
        windows=windows,
    )
    v3 = load_any(dump_dataset(to_v3(v2, listing, [], windows)))
    assert isinstance(v3, DatasetV3)
    return v3


def offers(ds: DatasetV3, retailer: str) -> dict[str, OfferV3]:
    return {o.sku or "": o for p in ds.products for cid, o in p.offers.items() if cid == retailer}


def stock(ds: DatasetV3, retailer: str = SEPHORA) -> dict[str | None, str | None]:
    return {
        o.sku: (o.series.availability or (None,))[0]
        for p in ds.products
        for cid, o in p.offers.items()
        if cid == retailer
    }


# Run identity is explicit.


def test_two_undeclared_runs_of_one_retailer_fail() -> None:
    listing = [
        seen(row(variant=101), at("2026-10-05T08:00"), run=7),
        seen(row(variant=102, family=11), at("2026-10-05T09:00"), run=8),
    ]
    with pytest.raises(ValueError, match=r"sephora_me: values from runs \[7, 8\]; one run"):
        crawl_windows(listing)


def test_two_runs_on_adjacent_days_are_never_merged() -> None:
    listing = [
        seen(row(variant=101), at("2026-10-04T19:00"), run=7),  # Dubai 10-04 23:00
        seen(row(variant=102, family=11), at("2026-10-04T20:30"), run=8),  # Dubai 10-05 00:30
    ]
    with pytest.raises(ValueError, match="one run per retailer"):
        crawl_windows(listing)
    with pytest.raises(ValueError, match=r"runs \[8\] outside the declared \[7\]"):
        crawl_windows(listing, {SEPHORA: (7,)})


def test_another_runs_stock_read_is_never_a_value_of_the_window() -> None:
    """The Sephora run-2 shape: price by run 1, a same-day stock read by run 2."""
    listing = [seen(row(), at("2026-10-05T08:00"), run=1, stock_run=2)]
    with pytest.raises(ValueError, match=r"runs \[2\] outside the declared \[1\]"):
        crawl_windows(listing, {SEPHORA: (1,)})


def test_declared_segments_hold_to_the_window_and_are_recorded() -> None:
    listing = [
        seen(row(variant=101), at("2026-10-05T08:00"), run=1),
        seen(row(variant=102, family=11), at("2026-10-06T08:00"), run=2),
    ]
    ds = export(listing, {SEPHORA: (1, 2)})
    (shop,) = (r for r in ds.meta.retailers if r.id == SEPHORA)
    assert shop.window is not None
    assert (shop.window.run_id, shop.window.segments) == ("1", ("2",))
    assert (shop.window.start, shop.window.end) == (at("2026-10-05T08:00"), at("2026-10-06T08:00"))
    assert all(o.series.price[0] is not None for o in offers(ds, SEPHORA).values())


def test_a_declared_run_needs_a_capture() -> None:
    with pytest.raises(ValueError, match=r"no capture of run \[9\]"):
        crawl_windows([seen(row(), at("2026-10-05T08:00"), run=2)], {SEPHORA: (9, 2)})


# The 4-day cap, on the live Ounass boundary.

OUNASS_FIRST = at("2026-10-02T20:00")  # Dubai 10-03 00:00


@pytest.mark.parametrize(
    ("last", "ok"),
    [
        (at("2026-10-06T19:59"), True),  # Dubai 10-06 23:59: exactly 4 days
        (at("2026-10-06T20:00"), False),  # one minute later: Dubai 10-07, 5 days
    ],
)
def test_ounass_exports_at_exactly_four_dubai_days_and_fails_a_minute_over(
    last: datetime, ok: bool
) -> None:
    listing = [
        seen(row(source=OUNASS, family=30, variant=301), OUNASS_FIRST),
        seen(row(source=OUNASS, family=31, variant=302), last),
    ]
    if ok:
        (shop,) = export(listing, {OUNASS: (7,)}).meta.retailers
        assert shop.window is not None
        assert shop.window.days("Asia/Dubai") == 4
    else:
        with pytest.raises(ValueError, match="spans 5 days in Asia/Dubai, more than 4"):
            export(listing, {OUNASS: (7,)})


# Option A: stock from the price capture's run and Dubai day.


def test_stock_across_dubai_midnight_from_its_price_is_null() -> None:
    """Price at Dubai 23:59, stock at 00:01 the next day, one run: the pair straddles 20:00Z."""
    straddle = seen(
        row(variant=101, availability="in_stock"),
        at("2026-10-04T19:59"),
        stock_at=at("2026-10-04T20:01"),
    )
    same_day = seen(
        row(variant=102, family=11, availability="in_stock"),
        at("2026-10-04T10:00"),
        stock_at=at("2026-10-04T12:00"),
    )
    ds = export([straddle, same_day], {SEPHORA: (7,)})
    assert stock(ds) == {"sku-101": None, "sku-102": "in_stock"}
    assert next(r for r in ds.meta.retailers if r.id == SEPHORA).fields == {  # stock partial
        **dict.fromkeys(("price", "regular", "rating", "shades"), "ok"),
        "stock": "partial",
        "size": "ok",
        "gtin": "not_published",
        "image": "not_collected",
    }


def test_stock_from_another_day_of_the_window_is_null() -> None:
    """Case 4: price on 10-03, the stock read on 10-05, both in the window."""
    split = seen(
        row(variant=101, availability="in_stock"),
        at("2026-10-03T08:00"),
        stock_at=at("2026-10-05T08:00"),
    )
    ds = export([split], {SEPHORA: (7,)})
    (offer,) = offers(ds, SEPHORA).values()
    assert offer.series.price[0] is not None
    assert stock(ds) == {"sku-101": None}
    assert offer.evidence.captured_at == at("2026-10-03T08:00")


def test_values_from_earlier_days_of_the_window_are_published() -> None:
    """Each offer's own capture in the window, not only the cutoff's day (ADR-0013)."""
    listing = [
        seen(row(variant=101, availability="in_stock"), at("2026-10-03T08:00")),
        seen(row(variant=102, family=11, availability="in_stock"), at("2026-10-05T08:00")),
    ]
    ds = export(listing, {SEPHORA: (7,)})
    assert stock(ds) == {"sku-101": "in_stock", "sku-102": "in_stock"}
    assert ds.meta.dates == (date(2026, 10, 5),)
    assert ds.meta.fields["price"] == "ok"


# A one-day body publishes what it did before the window.


def test_a_one_day_body_publishes_the_same_values_with_or_without_its_window() -> None:
    listing = [
        seen(row(variant=101, availability="in_stock"), at("2026-10-05T05:00")),
        seen(row(variant=102, family=11, price="80"), at("2026-10-05T09:00")),
        seen(
            row(variant=103, family=12, availability="in_stock"),
            at("2026-10-05T07:00"),
            stock_at=at("2026-10-05T08:00"),
        ),
    ]
    plain = build_dataset_v2(
        listing, [], generated_at=at("2026-10-05T12:00"), ulta=BLOCKED, ulta_note=NOTE
    )
    windowed = build_dataset_v2(
        listing,
        [],
        generated_at=at("2026-10-05T12:00"),
        ulta=BLOCKED,
        ulta_note=NOTE,
        windows=crawl_windows(listing, {SEPHORA: (7,)}),
    )
    assert windowed.products == plain.products
    assert windowed.meta == plain.meta


# Retained listings: kept, marked, covered, counted.


def test_a_listing_the_window_did_not_see_is_kept_marked_and_covered() -> None:
    listing = [
        seen(row(variant=101, availability="in_stock"), at("2026-10-05T08:00"), run=7),
        replace(
            seen(row(variant=102, family=11), at("2026-10-01T08:00"), run=6),
            price=None,
            regular=None,
            availability="not_observed",
            rating=None,
            retained=True,
        ),
    ]
    ds = export(listing, {SEPHORA: (7,)})
    kept = offers(ds, SEPHORA)
    assert set(kept) == {"sku-101", "sku-102"}  # never dropped
    old = kept["sku-102"]
    assert old.not_observed_reason is NotObservedReason.RETAINED
    assert old.series.price == (None,)
    assert old.series.availability == (None,)
    assert (old.evidence.run_id, old.evidence.captured_at) == ("6", at("2026-10-01T08:00"))
    assert kept["sku-101"].not_observed_reason is None
    (entry,) = (w for w in ds.not_observed if w.retailer == SEPHORA)
    assert (entry.retailer, entry.context, entry.categories) == (SEPHORA, SEPHORA, ("foundation",))
    assert (entry.start.isoformat(), entry.end.isoformat()) == ("2026-10-05", "2026-10-05")
    shop = next(r for r in ds.meta.retailers if r.id == SEPHORA)
    assert shop.fields is not None
    assert (shop.fields["price"], shop.fields["stock"]) == ("partial", "partial")
    assert f"window {SEPHORA}: run 7 " in window_report(ds)
    assert "notObservedReason={'retained': 1}" in window_report(ds)


def test_a_retained_listing_without_a_window_is_refused() -> None:
    listing = [
        seen(row(variant=101), at("2026-10-05T08:00")),
        replace(seen(row(variant=102, family=11), at("2026-10-01T08:00")), retained=True),
    ]
    v2 = build_dataset_v2(
        listing, [], generated_at=at("2026-10-05T12:00"), ulta=BLOCKED, ulta_note=NOTE
    )
    with pytest.raises(ValueError, match="sephora_me: offers marked retained without a crawl"):
        to_v3(v2, listing, [])


# Each retailer states its own fields and capabilities.


def test_each_retailer_states_its_own_fields_never_the_other_ones() -> None:
    """The beauty-style body: Sephora with stated regulars and stock, Ulta without either; Ulta
    never shows ``ok`` or ``true`` because of Sephora."""
    listing = [
        seen(row(variant=101, availability="in_stock"), at("2026-10-05T08:00"), run=1),
        seen(
            row(source=ULTA, family=20, variant=200, regular=None, availability="not_observed"),
            at("2026-10-04T08:00"),
            run=5,
        ),
    ]
    ds = export(listing, {SEPHORA: (1,), ULTA: (5,)})
    shops = {r.id: r for r in ds.meta.retailers}
    assert ds.meta.capabilities.promotions  # the roll-up
    assert ds.meta.fields["regular"] == "ok"
    sephora, ulta = shops[SEPHORA], shops[ULTA]
    assert sephora.capabilities is not None
    assert ulta.capabilities is not None
    assert sephora.fields is not None
    assert ulta.fields is not None
    assert (sephora.fields["regular"], sephora.capabilities.promotions) == ("ok", True)
    assert (ulta.fields["regular"], ulta.capabilities.promotions) == ("not_collected", False)
    assert (ulta.fields["stock"], ulta.capabilities.stock) == ("not_collected", False)
    assert ulta.window is not None
    assert ulta.window.run_id == "5"


def test_a_listed_retailer_with_no_rows_has_no_window() -> None:
    """Ulta blocked and listed beside Sephora: no window, nothing collected."""
    ds = export([seen(row(variant=101), at("2026-10-05T08:00"))], {SEPHORA: (7,)})
    ulta = next(r for r in ds.meta.retailers if r.id == ULTA)
    assert ulta.window is None
    assert ulta.fields is not None
    assert ulta.fields["price"] == "not_collected"


# --run


def test_run_flags_name_each_source_once_with_its_segments() -> None:
    assert parse_runs([], [SEPHORA]) is None
    runs = parse_runs([f"{SEPHORA}=1+2", f"{ULTA}=5"], [SEPHORA, ULTA])
    assert runs == {SEPHORA: (1, 2), ULTA: (5,)}


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ([f"{SEPHORA}=1"], "missing for ulta_ae"),
        ([f"{SEPHORA}=1", f"{SEPHORA}=2", f"{ULTA}=5"], "names sephora_me twice"),
        ([f"{SEPHORA}=x", f"{ULTA}=5"], "expected SOURCE=ID"),
        ([f"{SEPHORA}=0", f"{ULTA}=5"], "expected SOURCE=ID"),
        ([f"{SEPHORA}", f"{ULTA}=5"], "expected SOURCE=ID"),
        ([f"{OUNASS}=3", f"{SEPHORA}=1", f"{ULTA}=5"], "not one of --sources"),
    ],
)
def test_run_flags_are_refused_unless_every_source_has_exactly_one(
    values: list[str], message: str
) -> None:
    with pytest.raises(SystemExit, match=message):
        parse_runs(values, [SEPHORA, ULTA])


def test_a_price_on_a_retailer_without_a_stated_regular_is_still_decimal() -> None:
    """Money stays Decimal through the window path (no float on the way)."""
    ds = export([seen(row(variant=101, price="99.95"), at("2026-10-05T08:00"))], {SEPHORA: (7,)})
    (offer,) = offers(ds, SEPHORA).values()
    assert offer.series.price[0] is not None
    assert Decimal(offer.series.price[0].amount) == Decimal("99.95")
