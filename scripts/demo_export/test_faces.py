"""Faces UAE (``faces_ae``) as a third retailer: v2/v3 only, partial, its own per-source file."""

from __future__ import annotations

# ruff: noqa: S101
import argparse
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest

from pi_dataset import RetailerStatus, dump_dataset, load_any, load_dataset
from pi_metrics import ProductFilter, launches, view
from scripts.demo_export.export import (
    ListingRow,
    UltaContext,
    build_dataset,
    build_v1,
    export_slots,
    group_rows,
    pair_groups,
    slot,
)
from scripts.demo_export.history import Coverage, RunSpan, build_history_v2
from scripts.demo_export.test_export import match, row
from scripts.demo_export.test_history import D1, D2, D3, NOTE, at, span
from scripts.demo_export.test_history import NOW as LATER
from scripts.demo_export.test_v2 import build
from scripts.demo_export.v2 import RETAILERS, build_dataset_v2, to_v3

FACES, SEPHORA, ULTA = "faces_ae", "sephora_me", "ulta_ae"
NOW = datetime(2026, 9, 30, 22, 0, tzinfo=UTC)
BLOCKED = UltaContext(blocked_since=datetime(2026, 9, 30, 20, 55, tzinfo=UTC))
IMAGE = "https://www.faces.ae/media/catalog/product/a.jpg"


def faces(variant: int = 300, family: int = 30, **kw: Any) -> ListingRow:
    """A Faces import row as pi_db holds it: no stock read, a partial run and context."""
    base = row(source=FACES, family=family, variant=variant, availability="not_observed", **kw)
    return replace(base, run_status="partial", coverage_status="partial", image=IMAGE)


def doc(rows: list[ListingRow], matches: list[Any] | None = None, **kw: Any) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(build(rows, matches, **kw))
    return loaded


def test_faces_is_a_slot_and_the_register_key_faces_ae() -> None:
    assert slot("faces_ae") == "f"
    assert RETAILERS["f"] == ("faces_ae", "Faces UAE")


def test_a_faces_only_file_lists_faces_alone_partial_with_its_offers() -> None:
    d = doc([faces(), faces(variant=301, family=31)], slots=("f",))
    assert [(r["id"], r["status"]) for r in d["meta"]["retailers"]] == [(FACES, "partial")]
    assert d["notObserved"] == []  # Ulta's blocked window belongs to the Ulta/Sephora file
    assert {tuple(p["offers"]) for p in d["products"]} == {(FACES,)}


def test_faces_is_partial_even_when_its_runs_say_succeeded() -> None:
    ok = replace(faces(), run_status="succeeded", coverage_status="supported")
    (shop,) = doc([ok], slots=("f",))["meta"]["retailers"]
    assert shop["status"] == "partial"


def test_by_default_a_faces_only_export_lists_faces_alone() -> None:
    d = doc([faces()])
    assert [r["id"] for r in d["meta"]["retailers"]] == [FACES]


def test_faces_availability_is_never_published_even_if_a_row_has_one() -> None:
    d = doc([replace(faces(), availability="out_of_stock")], slots=("f",))
    (offer,) = d["products"][0]["offers"].values()
    assert offer["series"]["availability"] == [None]
    assert d["meta"]["fields"]["stock"] == "not_collected"


def test_faces_stated_was_prices_are_published_as_regular() -> None:
    d = doc([faces(price="80", regular="100")], slots=("f",))
    (offer,) = d["products"][0]["offers"].values()
    assert offer["series"]["regular"] == [{"amount": "100.00", "minor": 10000, "currency": "AED"}]
    assert d["meta"]["capabilities"]["promotions"] is True


def test_faces_images_only_from_www_faces_ae() -> None:
    d = doc([faces()], slots=("f",))
    assert d["products"][0]["image"] == IMAGE
    other = replace(faces(), image="https://img-product.sephora.me/a.jpg")
    assert doc([other], slots=("f",))["products"][0]["image"] is None


def test_three_retailers_keep_every_ulta_sephora_product_unchanged() -> None:
    ulta = row(source=ULTA, family=20, variant=200)
    sephora = row(family=10, variant=100)
    lone = row(family=11, variant=110)
    two = doc([ulta, sephora, lone], [match(200, 100, "0.9")])
    three = doc([ulta, sephora, lone, faces()], [match(200, 100, "0.9")])
    assert [r["id"] for r in three["meta"]["retailers"]] == [ULTA, SEPHORA, FACES]
    assert three["meta"]["retailers"][:2] == two["meta"]["retailers"]
    by_id = {p["id"]: p for p in three["products"]}
    for product in two["products"]:
        assert by_id.pop(product["id"]) == product
    assert [tuple(p["offers"]) for p in by_id.values()] == [(FACES,)]  # only additions


def test_an_edge_carries_its_own_two_retailers() -> None:
    sephora = row(family=10, variant=100)
    ulta = row(source=ULTA, family=20, variant=200)
    d = doc([sephora, ulta, faces()], [match(300, 100, "0.9")])
    (paired,) = [p for p in d["products"] if len(p["offers"]) == 2]
    assert sorted(paired["offers"]) == [FACES, SEPHORA]
    ((a, b),) = [(e["a"], e["b"]) for e in paired["matches"]]
    assert (a, b) == (FACES, SEPHORA)
    assert paired["name"] == "Example Product"  # Sephora names a pair, as before

    d = doc([ulta, faces()], [match(200, 300, "0.9")])
    (paired,) = d["products"]
    assert [(e["a"], e["b"]) for e in paired["matches"]] == [(FACES, ULTA)]


def test_pairs_are_other_then_namer_for_any_two_retailers() -> None:
    groups = group_rows([row(source=ULTA, family=20, variant=200), faces()])
    ((other, namer, _),) = pair_groups(groups, [match(200, 300, "0.9")])[0]
    assert (other.retailer, namer.retailer) == ("u", "f")


def test_v3_upgrade_states_faces_listing_count_and_content() -> None:
    rows = [faces()]
    v2 = build_dataset_v2(rows, [], generated_at=NOW, ulta=BLOCKED, ulta_note=NOTE, slots=("f",))
    v3 = to_v3(v2, rows, [])
    load_any(dump_dataset(v3))
    (offer,) = v3.products[0].offers.values()
    assert offer.listing_count == 1
    assert offer.content is not None


def test_v1_never_carries_faces_rows() -> None:
    sephora = row(family=10, variant=100)
    with_faces = build_dataset([sephora, faces()], [], generated_at=NOW, ulta=BLOCKED)
    without = build_dataset([sephora], [], generated_at=NOW, ulta=BLOCKED)
    assert with_faces["products"] == without["products"]


def args(*, v2: bool) -> argparse.Namespace:
    return argparse.Namespace(
        sources=(FACES,),
        output_v2="faces.json" if v2 else None,
        output_v3=None,
        ulta_blocked_since="2026-09-30T20:55:00Z",
        ulta_unblocked=False,
        ulta_recon_observed_count=None,
        ulta_recon_source=None,
        ulta_blocked_note=None,
        ulta_blocked_note_ar=None,
    )


def test_a_faces_only_export_writes_no_v1_and_needs_v2_or_v3() -> None:
    assert build_v1(args(v2=True), [faces()], [], [], NOW) is None
    with pytest.raises(SystemExit, match="has no v1"):
        build_v1(args(v2=False), [faces()], [], [], NOW)


@pytest.mark.parametrize(
    ("sources", "slots"),
    [
        ((FACES,), ("f",)),
        ((SEPHORA,), ("u", "s")),
        ((SEPHORA, FACES), ("u", "s", "f")),
    ],
)
def test_export_slots(sources: tuple[str, ...], slots: tuple[str, ...]) -> None:
    assert export_slots(sources) == slots


# ------------------------------------- history: complete only on a run that read the whole sitemap


def faces_seen(day: date, variant: int) -> ListingRow:
    moment = at(day)
    return replace(
        faces(variant=variant, family=variant), observed_at=moment, evidence_retrieved_at=moment
    )


def faces_span(day: date, status: str, *, last: datetime | None = None) -> RunSpan:
    """A Faces import run: its context keeps the importer's ``partial`` coverage."""
    return replace(
        span(day, source=FACES),
        status=status,
        coverage_status="partial",
        last_at=last or at(day, 12),
    )


DAYS = {
    D1: [faces_seen(D1, 300)],
    D2: [faces_seen(D2, 300)],
    D3: [faces_seen(D3, 300), faces_seen(D3, 301)],
}


def history(spans: list[RunSpan]) -> Any:
    cover = Coverage.of(spans)
    ds = build_history_v2(
        DAYS, cover, [], generated_at=LATER, ulta=BLOCKED, ulta_note=NOTE, slots=("f",)
    )
    load_dataset(dump_dataset(ds))
    return ds


def test_a_blocked_or_cut_short_faces_run_is_partial_and_backs_no_launch() -> None:
    spans = [faces_span(D1, "succeeded"), faces_span(D2, "partial"), faces_span(D3, "partial")]
    assert Coverage.of(spans).complete == {"f": frozenset({D1})}
    ds = history(spans)
    (shop,) = ds.meta.retailers
    assert shop.status is RetailerStatus.PARTIAL  # the latest day is not complete
    assert [(w.start, w.end) for w in ds.not_observed] == [(D2, D3)]
    found = launches(ds, (), ProductFilter())
    assert found.data.items == ()


def test_faces_runs_that_read_the_whole_sitemap_back_launches() -> None:
    ds = history([faces_span(d, "succeeded") for d in (D1, D2, D3)])
    (shop,) = ds.meta.retailers
    assert (shop.status, shop.since) == (RetailerStatus.SUPPORTED, D1)
    assert ds.not_observed == ()
    found = launches(ds, (), ProductFilter())
    assert [(i.retailer, i.first_seen) for i in found.data.items] == [(FACES, D3)]


def test_a_launch_needs_the_day_before_complete_too() -> None:
    spans = [faces_span(D1, "succeeded"), faces_span(D2, "partial"), faces_span(D3, "succeeded")]
    found = launches(history(spans), (), ProductFilter())
    assert found.data.items == ()  # D2, the day before 301 appeared, was not complete


def test_a_succeeded_faces_run_over_two_market_days_is_not_a_complete_day() -> None:
    across = faces_span(D1, "succeeded", last=at(D2, 1))
    assert Coverage.of([across]).complete == {"f": frozenset()}


# A complete Faces day backs every absence claim, removals included (coordinator ruling (a),
# 2026-10-06): the gate is view.complete_run, read by launches, assortment gaps and removals.
GONE = {D1: [faces_seen(D1, 300), faces_seen(D1, 301)], D2: [faces_seen(D2, 300)]}


def gone_on_d2(spans: list[RunSpan]) -> tuple[bool, list[tuple[date, date]]]:
    """Whether D2 backs 301's absence (it was on D1, not in D2's sitemap), and the windows."""
    ds = build_history_v2(
        GONE, Coverage.of(spans), [], generated_at=LATER, ulta=BLOCKED, ulta_note=NOTE, slots=("f",)
    )
    v3 = view.as_v3(load_dataset(dump_dataset(ds)))
    (ctx,) = view.contexts_of(v3, FACES)
    (gone,) = [p for p in v3.products if not view.seen(p.offers[ctx.id], 1)]
    return view.complete_run(v3, ctx.id, gone, 1), [(w.start, w.end) for w in ds.not_observed]


def test_two_complete_faces_days_back_the_absence_of_a_product_gone_from_the_sitemap() -> None:
    backed, windows = gone_on_d2([faces_span(D1, "succeeded"), faces_span(D2, "succeeded")])
    assert (backed, windows) == (True, [])


@pytest.mark.parametrize("d2", ["partial", "blocked"])
def test_a_partial_or_blocked_second_day_backs_no_removal(d2: str) -> None:
    backed, windows = gone_on_d2([faces_span(D1, "succeeded"), faces_span(D2, d2)])
    assert (backed, windows) == (False, [(D2, D2)])


def test_a_complete_second_day_after_a_partial_first_still_backs_the_absence() -> None:
    # 301 was seen on D1 even though D1 was partial; D2 read the whole sitemap without it
    backed, _ = gone_on_d2([faces_span(D1, "partial"), faces_span(D2, "succeeded")])
    assert backed


def test_one_concentration_across_a_products_offers_is_an_attribute() -> None:
    d = doc([replace(faces(), concentration=" EDP ")], slots=("f",))
    assert d["products"][0]["attributes"]["concentration"] == "edp"
    load_any(json.dumps(d))  # beauty@1 declares it


def test_conflicting_or_absent_concentrations_publish_none() -> None:
    sephora = replace(row(family=10, variant=100), concentration="edt")
    pair = doc([sephora, replace(faces(), concentration="edp")], [match(300, 100, "0.9")])
    assert len(pair["products"]) == 1
    assert "concentration" not in pair["products"][0]["attributes"]
    assert "concentration" not in doc([faces()], slots=("f",))["products"][0]["attributes"]
    other = doc([replace(faces(), concentration="Eau Fraiche")], slots=("f",))
    assert "concentration" not in other["products"][0]["attributes"]  # not a pi_core value


def test_v3_content_carries_the_faces_description_gallery_and_gtin() -> None:
    gallery = (IMAGE, "https://www.faces.ae/media/catalog/product/b.jpg")
    rows = [replace(faces(), description="A warm amber.", images=gallery, gtin="03145891074802")]
    v2 = build_dataset_v2(rows, [], generated_at=NOW, ulta=BLOCKED, ulta_note=NOTE, slots=("f",))
    (offer,) = to_v3(v2, rows, []).products[0].offers.values()
    assert offer.content is not None
    assert offer.content.description == "A warm amber."
    assert [str(u) for u in offer.content.images] == list(gallery)
    assert [v.gtin for v in offer.content.variants] == ["03145891074802"]
