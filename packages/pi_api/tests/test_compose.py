"""``pi_dataset.compose``: per-source slices of same-scope files as one view (ADR-0010)."""

from __future__ import annotations

from datetime import date

import pytest

from pi_dataset import DatasetV3, FieldStatus
from pi_dataset.compose import PRODUCER, CompositionError, compose, only, source_infos
from pi_metrics import EVERYTHING, assortment_gaps, launches
from sources_fixture import SEPHORA, ULTA, days, snapshot, snapshot_doc

OLD, NEW = days("2026-09-22", 3), days("2026-09-30", 2)
BOTH = (ULTA, SEPHORA)


def combined() -> DatasetV3:
    """The older file with both sources: p1 matched, p2 Ulta only, p3 Sephora only."""
    return snapshot({"p1": BOTH, "p2": (ULTA,), "p3": (SEPHORA,)}, dates=OLD)


def sephora() -> DatasetV3:
    return snapshot({"p1": (SEPHORA,), "p4": (SEPHORA,)}, dates=NEW, price=12_000)


def test_only_keeps_the_sources_offers_contexts_and_their_own_edges() -> None:
    ulta = only(combined(), [ULTA])
    assert [r.id for r in ulta.meta.retailers] == [ULTA]
    assert [c.id for c in ulta.meta.contexts] == [ULTA]
    assert [(p.id, set(p.offers)) for p in ulta.products] == [("p1", {ULTA}), ("p2", {ULTA})]
    assert all(p.matches == () for p in ulta.products)
    both = only(combined(), BOTH)
    assert [len(p.matches) for p in both.products] == [1, 0, 0]


def test_only_refuses_a_source_the_file_lacks() -> None:
    with pytest.raises(CompositionError, match="no retailer"):
        only(sephora(), [ULTA])


def test_only_refuses_a_source_with_no_products() -> None:
    d = snapshot_doc({"p1": (SEPHORA,)}, dates=NEW)
    d["meta"]["retailers"].append(d["meta"]["retailers"][0] | {"id": ULTA})
    d["meta"]["contexts"].append(d["meta"]["contexts"][0] | {"id": ULTA, "retailer": ULTA})
    with pytest.raises(CompositionError, match="no product"):
        only(DatasetV3.model_validate(d), [ULTA])


def test_a_product_in_two_files_is_one_product_with_both_offers() -> None:
    view = compose([only(combined(), [ULTA]), only(sephora(), [SEPHORA])])
    ds = view.dataset
    assert view.merged_ids == ("p1",)
    assert [p.id for p in ds.products] == ["p1", "p4", "p2"]
    p1 = ds.products[0]
    assert set(p1.offers) == {ULTA, SEPHORA}
    # Never an edge across files: the old file's p1 edge was to the old Sephora offer.
    assert p1.matches == ()
    assert ds.meta.dates == tuple(date.fromisoformat(d) for d in (*OLD, *NEW))
    assert ds.meta.producer == PRODUCER


def test_each_source_keeps_its_own_dates_and_is_null_elsewhere() -> None:
    ds = compose([only(combined(), [ULTA]), only(sephora(), [SEPHORA])]).dataset
    p1 = ds.products[0]
    ulta = [m.minor if m else None for m in p1.offers[ULTA].series.price]
    seph = [m.minor if m else None for m in p1.offers[SEPHORA].series.price]
    assert ulta == [10_000, 10_000, 10_000, None, None]
    assert seph == [None, None, None, 12_000, 12_000]


def view() -> DatasetV3:
    return compose([only(combined(), [ULTA]), only(sephora(), [SEPHORA])]).dataset


def test_dates_a_file_lacks_are_not_observed_for_its_sources() -> None:
    windows = [(w.retailer, str(w.start), str(w.end), w.categories) for w in view().not_observed]
    assert windows == [
        (SEPHORA, "2026-09-20", "2026-09-22", None),
        (ULTA, "2026-09-29", "2026-09-30", None),
    ]


def test_a_date_outside_a_file_backs_no_launch_or_gap() -> None:
    """The Reviewer's #120 probe: three false absence claims on the composed fixture."""
    ds = view()
    # Sephora's first date is not a launch: it wasn't crawled on the date before.
    assert launches(ds, (), EVERYTHING).data.items == ()
    # p2 was not "missing at Sephora" on 22 Sep, nor p4 "missing at Ulta" on 30 Sep.
    old_gaps = assortment_gaps(ds, SEPHORA, ULTA, EVERYTHING, on=date(2026, 9, 22)).data
    new_gaps = assortment_gaps(ds, ULTA, SEPHORA, EVERYTHING).data
    assert [i.id for i in old_gaps.items] == [i.id for i in new_gaps.items] == []


def test_a_merged_product_takes_the_first_sources_fields_in_any_order() -> None:
    d = snapshot_doc({"p1": (SEPHORA,)}, dates=NEW)
    d["products"][0]["name"] = "Sephora's name"
    seph, ulta = only(DatasetV3.model_validate(d), [SEPHORA]), only(combined(), [ULTA])
    one, other = compose([ulta, seph]), compose([seph, ulta])
    assert one.dataset == other.dataset
    assert one.sources == other.sources
    # ``sephora_me`` sorts before ``ulta_ae``.
    assert one.dataset.products[0].name == "Sephora's name"


def test_meta_takes_the_latest_cutoff_and_sources_keep_their_own() -> None:
    view = compose([only(combined(), [ULTA]), only(sephora(), [SEPHORA])])
    assert view.dataset.meta.cutoff.date() == date(2026, 9, 30)
    by_source = {s.source: s for s in view.sources}
    assert by_source[ULTA].cutoff.date() == date(2026, 9, 22)
    assert by_source[ULTA].last_date == date(2026, 9, 22)
    assert by_source[SEPHORA].cutoff.date() == date(2026, 9, 30)
    assert (by_source[ULTA].products, by_source[SEPHORA].products) == (2, 2)


def test_capabilities_are_or_ed_and_differing_fields_are_partial() -> None:
    a = snapshot_doc({"p1": (ULTA,)}, dates=OLD, stage="proposed", fields={"price": "ok"})
    a["meta"]["capabilities"]["images"] = True
    b = snapshot_doc({"p2": (SEPHORA,)}, dates=NEW, fields={"price": "ok", "stock": "ok"})
    b["meta"]["test"] = True
    meta = compose([DatasetV3.model_validate(a), DatasetV3.model_validate(b)]).dataset.meta
    assert meta.capabilities.images
    assert meta.fields == {"price": FieldStatus.OK, "stock": FieldStatus.PARTIAL}
    assert meta.match_stage == "reviewed+proposed"
    assert meta.test


@pytest.mark.parametrize(
    ("key", "value"),
    [("scope", "other"), ("vertical", "food_menu")],
)
def test_slices_must_share_scope_and_vertical(key: str, value: str) -> None:
    b = snapshot_doc({"p2": (SEPHORA,)}, dates=NEW)
    b["meta"][key] = value
    if key == "vertical":
        b["meta"]["profile"] |= {"name": value}
    with pytest.raises(CompositionError, match=f"meta.{key}"):
        compose([snapshot({"p1": (ULTA,)}, dates=OLD), DatasetV3.model_validate(b)])


def test_a_market_must_have_one_currency_and_time_zone() -> None:
    b = snapshot_doc({"p2": (SEPHORA,)}, dates=NEW)
    b["meta"]["markets"][0]["timeZone"] = "Asia/Riyadh"
    with pytest.raises(CompositionError, match="market AE"):
        compose([snapshot({"p1": (ULTA,)}, dates=OLD), DatasetV3.model_validate(b)])


def test_locales_of_a_shared_market_are_merged() -> None:
    b = snapshot_doc({"p2": (SEPHORA,)}, dates=NEW)
    b["meta"]["markets"][0]["locales"] = ["en", "ar"]
    a = snapshot({"p1": (ULTA,)}, dates=OLD)
    markets = compose([a, DatasetV3.model_validate(b)]).dataset.meta.markets
    assert markets[0].locales == ("en", "ar")


def test_a_retailer_in_two_slices_or_no_slice_is_refused() -> None:
    with pytest.raises(CompositionError, match="more than one slice"):
        compose([sephora(), sephora()])
    with pytest.raises(CompositionError, match="nothing"):
        compose([])


def test_source_infos_of_one_file() -> None:
    infos = source_infos(combined())
    assert [(i.source, i.products) for i in infos] == [(SEPHORA, 2), (ULTA, 2)]
