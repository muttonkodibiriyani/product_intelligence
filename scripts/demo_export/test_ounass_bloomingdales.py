"""Ounass UAE (``ounass_ae``, slot ``o``) and Bloomingdale's UAE (``bloomingdales_ae``, slot
``b``) as retailers 4 and 5: v2/v3 only, beauty and EN only, always partial, each its own
per-source file (decision log 2026-10-06 and 2026-10-07)."""

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
from scripts.demo_export.v2 import (
    IMAGE_HOSTS,
    OUNASS_IMAGE_HOST,
    RETAILERS,
    build_dataset_v2,
    to_v3,
)

OUNASS, BLOOMINGDALES = "ounass_ae", "bloomingdales_ae"
FACES, SEPHORA, ULTA = "faces_ae", "sephora_me", "ulta_ae"
NOW = datetime(2026, 9, 30, 22, 0, tzinfo=UTC)
BLOCKED = UltaContext(blocked_since=datetime(2026, 9, 30, 20, 55, tzinfo=UTC))
BLM_IMAGE = (
    "https://prodheadless.atgwasl.com/on/demandware.static/-/Sites-bloomingdales-master-catalog"
    "/default/dw0a1b2c3d/images/a.jpg"
)
#: Any URL, on any host: Ounass has no verified image host yet, so none may be published.
OUNASS_IMAGE = "https://www.ounass.ae/media/a.jpg"
SHOPS = {"o": OUNASS, "b": BLOOMINGDALES}


def shop_row(source: str, variant: int = 400, family: int = 40, **kw: Any) -> ListingRow:
    """An Ounass or Bloomingdale's import row as pi_db holds it: the page's own stock, no rating
    (neither page carries one), a partial run and context."""
    kw.setdefault("availability", "in_stock")
    base = row(source=source, family=family, variant=variant, **kw)
    image = BLM_IMAGE if source == BLOOMINGDALES else OUNASS_IMAGE
    return replace(
        base,
        run_status="partial",
        coverage_status="partial",
        image=image,
        rating=None,
        rating_scale=None,
        rating_count=None,
    )


def doc(rows: list[ListingRow], matches: list[Any] | None = None, **kw: Any) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(build(rows, matches, **kw))
    return loaded


def only_offer(d: dict[str, Any]) -> dict[str, Any]:
    (offer,) = d["products"][0]["offers"].values()
    return offer  # type: ignore[no-any-return]


def test_slots_and_register_keys() -> None:
    assert slot("ounass_ae") == "o"
    assert slot("bloomingdales_ae") == "b"
    assert RETAILERS["o"] == (OUNASS, "Ounass UAE")
    assert RETAILERS["b"] == (BLOOMINGDALES, "Bloomingdale's UAE")
    assert list(RETAILERS) == ["u", "s", "f", "o", "b"]  # meta.retailers order


@pytest.mark.parametrize(("shop", "source"), sorted(SHOPS.items()))
def test_a_one_shop_file_lists_that_shop_alone_partial(shop: str, source: str) -> None:
    d = doc([shop_row(source), shop_row(source, variant=401, family=41)], slots=(shop,))
    assert [(r["id"], r["status"]) for r in d["meta"]["retailers"]] == [(source, "partial")]
    assert d["notObserved"] == []  # Ulta's blocked window belongs to the Ulta/Sephora file
    assert {tuple(p["offers"]) for p in d["products"]} == {(source,)}
    assert [r["id"] for r in doc([shop_row(source)])["meta"]["retailers"]] == [source]


@pytest.mark.parametrize("source", [OUNASS, BLOOMINGDALES])
def test_partial_even_when_its_runs_say_succeeded(source: str) -> None:
    ok = replace(shop_row(source), run_status="succeeded", coverage_status="supported")
    (listed,) = doc([ok])["meta"]["retailers"]
    assert listed["status"] == "partial"


@pytest.mark.parametrize("source", [OUNASS, BLOOMINGDALES])
@pytest.mark.parametrize("state", ["in_stock", "out_of_stock"])
def test_the_stock_the_page_states_is_published(source: str, state: str) -> None:
    """Unlike Faces (export side pending), an out-of-stock page stays an offer, published out of
    stock (decision log 2026-10-06)."""
    d = doc([shop_row(source, availability=state)])
    assert len(d["products"]) == 1
    assert only_offer(d)["series"]["availability"] == [state]
    assert d["meta"]["fields"]["stock"] == "ok"
    assert d["meta"]["capabilities"]["stock"] is True


@pytest.mark.parametrize("source", [OUNASS, BLOOMINGDALES])
def test_unknown_stock_stays_unknown(source: str) -> None:
    """The feed leaves a page whose two statements disagree ``not_observed``: never a guess."""
    d = doc([shop_row(source, availability="not_observed")])
    assert only_offer(d)["series"]["availability"] == [None]
    assert d["meta"]["fields"]["stock"] == "not_collected"


def test_faces_stock_is_still_not_published_beside_them() -> None:
    faces = replace(row(source=FACES, family=30, variant=300), availability="out_of_stock")
    d = doc([faces, shop_row(OUNASS, availability="out_of_stock")])
    stock = {r: o["series"]["availability"] for p in d["products"] for r, o in p["offers"].items()}
    assert stock == {FACES: [None], OUNASS: ["out_of_stock"]}


@pytest.mark.parametrize("source", [OUNASS, BLOOMINGDALES])
def test_ratings_are_not_collected(source: str) -> None:
    d = doc([shop_row(source)])
    assert only_offer(d)["rating"] is None
    assert d["meta"]["fields"]["rating"] == "not_collected"


@pytest.mark.parametrize("source", [OUNASS, BLOOMINGDALES])
def test_stated_was_prices_are_published_as_regular(source: str) -> None:
    d = doc([shop_row(source, price="80", regular="100")])
    assert only_offer(d)["series"]["regular"] == [
        {"amount": "100.00", "minor": 10000, "currency": "AED"}
    ]
    assert d["meta"]["capabilities"]["promotions"] is True


def test_bloomingdales_images_only_from_its_own_host() -> None:
    assert IMAGE_HOSTS[BLOOMINGDALES] == frozenset({"prodheadless.atgwasl.com"})
    assert doc([shop_row(BLOOMINGDALES)])["products"][0]["image"] == BLM_IMAGE
    for foreign in ("https://img-product.sephora.me/a.jpg", "https://www.faces.ae/a.jpg"):
        other = replace(shop_row(BLOOMINGDALES), image=foreign)
        assert doc([other])["products"][0]["image"] is None
    # ...and its host is not accepted on another shop's offer
    sephora = replace(row(family=10, variant=100), image=BLM_IMAGE)
    assert doc([sephora])["products"][0]["image"] is None


def test_ounass_has_no_image_host_so_no_image_is_published() -> None:
    """TODO(ounass image host): the host is not verified, so it is never guessed."""
    assert OUNASS_IMAGE_HOST is None
    assert OUNASS not in IMAGE_HOSTS
    for url in (OUNASS_IMAGE, BLM_IMAGE, "https://img-product.sephora.me/a.jpg"):
        d = doc([replace(shop_row(OUNASS), image=url)])
        assert d["products"][0]["image"] is None
        assert d["meta"]["fields"]["image"] == "not_collected"


def test_five_retailers_keep_every_other_product_unchanged() -> None:
    ulta = row(source=ULTA, family=20, variant=200)
    sephora = row(family=10, variant=100)
    faces = row(source=FACES, family=30, variant=300)
    three = doc([ulta, sephora, faces], [match(200, 100, "0.9")])
    five = doc(
        [ulta, sephora, faces, shop_row(OUNASS), shop_row(BLOOMINGDALES, variant=500, family=50)],
        [match(200, 100, "0.9")],
    )
    assert [r["id"] for r in five["meta"]["retailers"]] == [
        ULTA,
        SEPHORA,
        FACES,
        OUNASS,
        BLOOMINGDALES,
    ]
    assert five["meta"]["retailers"][:3] == three["meta"]["retailers"]
    by_id = {p["id"]: p for p in five["products"]}
    for product in three["products"]:
        assert by_id.pop(product["id"]) == product
    assert sorted(tuple(p["offers"]) for p in by_id.values()) == [(BLOOMINGDALES,), (OUNASS,)]


@pytest.mark.parametrize(
    ("left", "right", "namer"),
    [
        (SEPHORA, OUNASS, "s"),
        (FACES, OUNASS, "f"),
        (OUNASS, BLOOMINGDALES, "o"),
        (ULTA, BLOOMINGDALES, "b"),
        (ULTA, OUNASS, "o"),
    ],
)
def test_the_namer_follows_naming_order(left: str, right: str, namer: str) -> None:
    rows = [row(source=left, family=10, variant=100), row(source=right, family=20, variant=200)]
    ((other, named, _),) = pair_groups(group_rows(rows), [match(100, 200, "0.9")])[0]
    assert named.retailer == namer
    assert {other.retailer, named.retailer} == {slot(left), slot(right)}


def test_an_edge_carries_its_own_two_retailers() -> None:
    ounass = shop_row(OUNASS)
    blm = shop_row(BLOOMINGDALES, variant=500, family=50)
    d = doc([ounass, blm], [match(400, 500, "0.9")])
    (paired,) = d["products"]
    assert [(e["a"], e["b"]) for e in paired["matches"]] == [(BLOOMINGDALES, OUNASS)]


@pytest.mark.parametrize("source", [OUNASS, BLOOMINGDALES])
def test_v3_upgrade_states_listing_count_and_content(source: str) -> None:
    rows = [shop_row(source)]
    v2 = build_dataset_v2(
        rows, [], generated_at=NOW, ulta=BLOCKED, ulta_note=NOTE, slots=(slot(source),)
    )
    v3 = to_v3(v2, rows, [])
    load_any(dump_dataset(v3))
    (offer,) = v3.products[0].offers.values()
    assert offer.listing_count == 1
    assert offer.content is not None


def test_v1_never_carries_their_rows() -> None:
    sephora = row(family=10, variant=100)
    with_them = build_dataset(
        [sephora, shop_row(OUNASS), shop_row(BLOOMINGDALES, variant=500, family=50)],
        [],
        generated_at=NOW,
        ulta=BLOCKED,
    )
    without = build_dataset([sephora], [], generated_at=NOW, ulta=BLOCKED)
    assert with_them["products"] == without["products"]


def args(source: str, *, v2: bool) -> argparse.Namespace:
    return argparse.Namespace(
        sources=(source,),
        output_v2="shop.json" if v2 else None,
        output_v3=None,
        ulta_blocked_since="2026-09-30T20:55:00Z",
        ulta_unblocked=False,
        ulta_recon_observed_count=None,
        ulta_recon_source=None,
        ulta_blocked_note=None,
        ulta_blocked_note_ar=None,
    )


@pytest.mark.parametrize("source", [OUNASS, BLOOMINGDALES])
def test_a_one_shop_export_writes_no_v1_and_needs_v2_or_v3(source: str) -> None:
    assert build_v1(args(source, v2=True), [shop_row(source)], [], [], NOW) is None
    with pytest.raises(SystemExit, match="has no v1"):
        build_v1(args(source, v2=False), [shop_row(source)], [], [], NOW)


@pytest.mark.parametrize(
    ("sources", "slots"),
    [
        ((OUNASS,), ("o",)),
        ((BLOOMINGDALES,), ("b",)),
        ((SEPHORA, BLOOMINGDALES), ("u", "s", "b")),
        ((BLOOMINGDALES, FACES, OUNASS), ("f", "o", "b")),
    ],
)
def test_export_slots(sources: tuple[str, ...], slots: tuple[str, ...]) -> None:
    assert export_slots(sources) == slots


# --------------------------------------- history: never a complete day, so absence infers nothing


def seen(source: str, day: date, variant: int) -> ListingRow:
    moment = at(day)
    return replace(
        shop_row(source, variant=variant, family=variant),
        observed_at=moment,
        evidence_retrieved_at=moment,
    )


def import_span(source: str, day: date, status: str = "succeeded") -> RunSpan:
    """An import run: even ``succeeded`` on one market day (what makes a Faces day complete)."""
    return replace(span(day, source=source), status=status, coverage_status="partial")


@pytest.mark.parametrize("source", [OUNASS, BLOOMINGDALES])
def test_a_succeeded_import_run_is_never_a_complete_day(source: str) -> None:
    shop = slot(source)
    spans = [import_span(source, d) for d in (D1, D2, D3)]
    assert Coverage.of(spans).complete == {shop: frozenset()}
    supported = replace(span(D1, source=source), coverage_status="supported")
    assert Coverage.of([supported]).complete == {shop: frozenset()}
    # Faces, under the same runs, is complete on each (decision log 2026-10-06)
    faces = [import_span(FACES, d) for d in (D1, D2, D3)]
    assert Coverage.of(faces).complete == {"f": frozenset({D1, D2, D3})}


@pytest.mark.parametrize("source", [OUNASS, BLOOMINGDALES])
def test_no_launch_and_no_removal_whatever_the_runs_say(source: str) -> None:
    days = {
        D1: [seen(source, D1, 400), seen(source, D1, 402)],
        D2: [seen(source, D2, 400), seen(source, D2, 402)],
        D3: [seen(source, D3, 400), seen(source, D3, 401)],  # 401 new, 402 gone
    }
    cover = Coverage.of([import_span(source, d) for d in (D1, D2, D3)])
    ds = build_history_v2(
        days, cover, [], generated_at=LATER, ulta=BLOCKED, ulta_note=NOTE, slots=(slot(source),)
    )
    ds = load_dataset(dump_dataset(ds))
    (listed,) = ds.meta.retailers
    assert listed.status is RetailerStatus.PARTIAL
    assert [(w.retailer, w.start, w.end) for w in ds.not_observed] == [(source, D1, D3)]
    assert launches(ds, (), ProductFilter()).data.items == ()
    v3 = view.as_v3(ds)
    (ctx,) = view.contexts_of(v3, source)
    (gone,) = [p for p in v3.products if not view.seen(p.offers[ctx.id], 2)]
    assert not view.complete_run(v3, ctx.id, gone, 2)
    # an out-of-stock day is the page's own statement, published as such in the series
    out = {D3: [replace(seen(source, D3, 400), availability="out_of_stock")]}
    one = build_history_v2(
        out,
        Coverage.of([import_span(source, D3)]),
        [],
        generated_at=LATER,
        ulta=BLOCKED,
        ulta_note=NOTE,
        slots=(slot(source),),
    )
    (offer,) = one.products[0].offers.values()
    assert offer.series.availability == ("out_of_stock",)
