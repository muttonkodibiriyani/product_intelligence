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
from pi_metrics import ProductFilter, launches
from pi_metrics.model import Reason
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
from scripts.demo_export.history import Coverage, build_history_v2
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


# ---------------------------------------------------------------- history: never a complete day


def faces_seen(day: date, variant: int) -> ListingRow:
    moment = at(day)
    return replace(
        faces(variant=variant, family=variant), observed_at=moment, evidence_retrieved_at=moment
    )


def test_faces_history_has_no_complete_day_so_no_launch() -> None:
    spans = [span(d, source=FACES) for d in (D1, D2, D3)]  # succeeded and supported
    assert Coverage.of(spans).complete == {"f": frozenset()}
    days = {
        D1: [faces_seen(D1, 300)],
        D2: [faces_seen(D2, 300)],
        D3: [faces_seen(D3, 300), faces_seen(D3, 301)],
    }
    ds = build_history_v2(
        days,
        Coverage.of(spans),
        [],
        generated_at=LATER,
        ulta=BLOCKED,
        ulta_note=NOTE,
        slots=("f",),
    )
    load_dataset(dump_dataset(ds))
    (shop,) = ds.meta.retailers
    assert shop.status is RetailerStatus.PARTIAL
    assert [(w.start, w.end) for w in ds.not_observed] == [(D1, D3)]
    found = launches(ds, (), ProductFilter())
    assert found.data.items == ()
    assert found.reason in {Reason.RETAILER_PARTIAL, Reason.CAPABILITY_OFF, None}


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


def test_v3_content_carries_the_faces_description_gallery_and_gtin() -> None:
    gallery = (IMAGE, "https://www.faces.ae/media/catalog/product/b.jpg")
    rows = [replace(faces(), description="A warm amber.", images=gallery, gtin="03145891074802")]
    v2 = build_dataset_v2(rows, [], generated_at=NOW, ulta=BLOCKED, ulta_note=NOTE, slots=("f",))
    (offer,) = to_v3(v2, rows, []).products[0].offers.values()
    assert offer.content is not None
    assert offer.content.description == "A warm amber."
    assert [str(u) for u in offer.content.images] == list(gallery)
    assert [v.gtin for v in offer.content.variants] == ["03145891074802"]
