"""The read-time view of an imported retailer (``pi_api.dq``, API 1.5.0; 1.13.0).

``ulta_ae`` here is the fixture's ``shop_b`` renamed. Six of its offers carry a was-price: p03's
is above its price (a promotion), the other five equal the price (not one). Since 1.13.0 (owner,
2026-10-03: "Show Ulta discounts") those stated was-prices are served and measured with a
``was_price_stated`` caveat; ``WAS_PRICE_WITHHELD`` brings back the 1 October rule, under which
the view cleared them so the share never read 0%.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from api_fixture import Client, bearer, make_client, write
from pi_api.app import _named
from pi_api.catalog import ProductQuery
from pi_api.dq import IMPORTED, WAS_PRICE_WITHHELD, Imported, caveats, imported_view
from pi_dataset import ContractModel, DatasetV3
from pi_metrics import CaveatCode, Reason, promotions, summary
from pi_metrics.model import ProductFilter
from pi_metrics.summary import default_context
from v3_fixture import doc, load, offer

API = "/api/v1"
ULTA = "ulta_ae"
IMPORTED_AT = "2026-09-30T21:15:00Z"
#: The import's local day in the market (Asia/Dubai, +04:00): 21:15Z is already 1 October.
SNAPSHOT_EN = "ulta_ae: snapshot imported 2026-10-01, capture date unknown."


def ulta_doc() -> dict[str, Any]:
    d: dict[str, Any] = json.loads(json.dumps(doc()).replace('"shop_b"', f'"{ULTA}"'))
    d["meta"]["test"] = False
    for product in d["products"]:
        for edge in product["matches"]:
            if edge["a"] > edge["b"]:  # edges are ordered a < b
                edge["a"], edge["b"] = edge["b"], edge["a"]
    offer(d, "p03", ULTA)["series"]["price"][-1] = {
        "amount": "80.00",
        "minor": 8000,
        "currency": "AED",
    }  # a was-price above the price: a promotion if the was-price were believed
    offer(d, "p05", ULTA)["evidence"]["capturedAt"] = IMPORTED_AT
    return d


def served(tmp_path: Path) -> Client:
    write(tmp_path, load(ulta_doc()))
    return make_client(tmp_path)[0]


def get(client: Client, path: str) -> Any:
    response = client.get(f"{API}{path}", headers=bearer())
    assert response.status_code == 200, response.text
    return response.json()


def codes(body: Any) -> list[str]:
    return [c["code"] for c in body["caveats"]]


def test_ulta_ae_is_the_imported_retailer_and_its_was_prices_are_not_withheld() -> None:
    assert frozenset({ULTA}) == IMPORTED
    assert frozenset() == WAS_PRICE_WITHHELD  # owner, 2026-10-03: "Show Ulta discounts"


def test_the_view_keeps_ulta_stated_was_prices_and_finds_the_import_date() -> None:
    ds = load(ulta_doc())
    view, (found,) = imported_view(ds)
    assert (found.retailer, found.contexts, found.was_prices, found.withheld) == (
        ULTA,
        (ULTA,),
        6,
        False,
    )
    assert found.imported_at == datetime(2026, 9, 30, 21, 15, tzinfo=UTC)
    assert view.products == ds.products  # nothing cleared: served as the retailer states them
    assert view.meta == ds.meta


def test_ulta_discounts_are_counted_and_a_was_price_at_or_below_the_price_is_not_one() -> None:
    d = ulta_doc()
    # p05: a was-price below the price; the four others equal it. Only p03 (80 < 100) is a
    # promotion, and none of the others is counted as one.
    p05 = offer(d, "p05", ULTA)["series"]
    p05["price"][-1] = {**p05["regular"][-1], "amount": "999.00", "minor": 99900}
    view, _ = imported_view(load(d))
    s = summary(view, ULTA).data
    assert s.promo_share_pct == Decimal("100") / 6
    assert s.top_discounts is not None
    assert [t.id for t in s.top_discounts] == ["p03"]
    p = promotions(view, (ULTA,), ProductFilter())
    (share,) = p.data.retailers
    assert (share.retailer, share.reason) == (ULTA, None)
    assert [(item.id, item.retailer) for item in p.data.items] == [("p03", ULTA)]


def test_a_dataset_without_an_imported_retailer_is_served_as_the_same_object() -> None:
    ds = load(doc())
    served_ds, found = imported_view(ds)
    assert served_ds is ds
    assert found == ()


def test_a_withheld_retailer_has_only_its_was_prices_cleared() -> None:
    ds = load(ulta_doc())
    view, (found,) = imported_view(ds, withheld=IMPORTED)
    assert (found.retailer, found.contexts, found.was_prices, found.withheld) == (
        ULTA,
        (ULTA,),
        6,
        True,
    )
    assert found.imported_at == datetime(2026, 9, 30, 21, 15, tzinfo=UTC)
    for before, after in zip(ds.products, view.products, strict=True):
        for cid, o in after.offers.items():
            if cid == ULTA:
                assert o.series.regular is None
                assert o.series.price == before.offers[cid].series.price
            else:
                assert o is before.offers[cid]  # untouched, so byte-identical
    assert view.meta == ds.meta  # own captures end at the cutoff


def test_the_import_date_is_the_local_day_in_the_market_time_zone() -> None:
    """The caveat's date is counted like ``meta.dates``: in the market, not in UTC."""
    _, (found,) = imported_view(load(ulta_doc()))
    assert found.time_zone == "Asia/Dubai"

    def date_of(at: datetime) -> str:
        shop = Imported(ULTA, (ULTA,), at, 0, found.time_zone)
        (snapshot,) = (c for c in caveats((shop,), "meta", frozenset()) if c.params.get("date"))
        return str(snapshot.params["date"])

    assert date_of(datetime(2026, 9, 30, 19, 59, tzinfo=UTC)) == "2026-09-30"
    assert date_of(datetime(2026, 9, 30, 20, 0, tzinfo=UTC)) == "2026-10-01"
    assert date_of(datetime(2026, 9, 30, 23, 59, tzinfo=UTC)) == "2026-10-01"


def test_without_withholding_ulta_was_prices_are_measured() -> None:
    """What withholding prevents when a retailer's was-prices are not to be read."""
    d = ulta_doc()
    assert summary(load(d), ULTA).data.promo_share_pct == Decimal("100") / 6  # p03 only
    offer(d, "p03", ULTA)["series"]["price"][-1] = offer(d, "p03", ULTA)["series"]["regular"][-1]
    assert summary(load(d), ULTA).data.promo_share_pct == 0  # "no promotions": ruled out


def test_metrics_withhold_promotions_of_an_unverified_context_with_a_reason() -> None:
    view, _ = imported_view(load(ulta_doc()), withheld=IMPORTED)
    s = summary(view, ULTA, frozenset({ULTA})).data
    assert (s.promo_share_pct, s.promo_depth, s.top_discounts) == (None, None, None)
    assert (s.withheld[0].section, s.withheld[0].reason) == (
        "promotions",
        Reason.WAS_PRICE_UNVERIFIED,
    )
    assert s.median_price is not None  # prices are still served
    p = promotions(view, (), ProductFilter(), unverified=frozenset({ULTA}))
    shares = {r.retailer: r for r in p.data.retailers}
    assert (shares[ULTA].share, shares[ULTA].reason) == (None, Reason.WAS_PRICE_UNVERIFIED)
    assert shares["shop_a"].share is not None
    assert all(item.retailer != ULTA for item in p.data.items)


def test_summary_of_ulta_measures_its_stated_discounts_as_a_dated_snapshot(
    tmp_path: Path,
) -> None:
    body = get(served(tmp_path), f"/summary?retailer={ULTA}")
    data = body["data"]
    assert data["promoSharePct"] is not None
    assert [t["id"] for t in data["topDiscounts"]] == ["p03"]
    assert not [w for w in data["withheld"] if w["section"] == "promotions"]
    assert data["freshness"]["status"] == "snapshot"
    assert data["freshness"]["cutoff"] == IMPORTED_AT
    assert codes(body)[-3:] == [
        "was_price_stated",
        "snapshot_import_date",
        "parent_listings_included",
    ]
    stated = next(c for c in body["caveats"] if c["code"] == "was_price_stated")
    assert stated["params"] == {"retailer": ULTA}
    assert stated["en"] == (
        "ulta_ae's discounts use the was-prices it states itself; PI has not checked them."
    )
    assert stated["ar"]
    snapshot = next(c for c in body["caveats"] if c["code"] == "snapshot_import_date")
    assert snapshot["params"] == {"retailer": ULTA, "date": "2026-10-01"}
    assert snapshot["en"] == SNAPSHOT_EN
    assert "fresh" not in json.dumps(data["freshness"])


def test_another_retailers_summary_has_no_ulta_caveat(tmp_path: Path) -> None:
    body = get(served(tmp_path), "/summary?retailer=shop_a")
    assert not {c.value for c in CaveatCode if "snapshot" in c.value} & set(codes(body))
    assert not {"was_price_unverified", "was_price_stated"} & set(codes(body))
    assert body["data"]["freshness"]["status"] != "snapshot"
    assert body["data"]["promoSharePct"] is not None


def test_promotions_count_ulta_with_its_stated_was_prices(tmp_path: Path) -> None:
    body = get(served(tmp_path), "/promotions")
    shares = {r["retailer"]: r for r in body["data"]["retailers"]}
    assert shares[ULTA]["share"] is not None
    assert shares[ULTA]["reason"] is None
    assert shares["shop_a"]["share"] is not None
    assert [i["id"] for i in body["data"]["items"] if i["retailer"] == ULTA] == ["p03"]
    assert body["reason"] != "was_price_unverified"
    assert "was_price_stated" in codes(body)
    assert "was_price_unverified" not in codes(body)


def test_promotions_of_shop_a_alone_owe_no_ulta_caveat(tmp_path: Path) -> None:
    body = get(served(tmp_path), "/promotions?retailer=shop_a")
    assert codes(body) == []
    assert body["status"] == "ok"


def test_a_product_shows_ulta_stated_was_price_and_discount(tmp_path: Path) -> None:
    client = served(tmp_path)
    body = get(client, "/products/p03")
    offers = {o["retailer"]: o for o in body["data"]["offers"]}
    assert offers[ULTA]["regular"] is not None
    assert offers[ULTA]["promoPct"] is not None
    assert offers[ULTA]["price"]["amount"] == "80.00"
    assert offers["shop_a"]["regular"] is not None
    assert codes(body)[-3:] == [
        "was_price_stated",
        "snapshot_import_date",
        "parent_listings_included",
    ]
    assert "snapshot_import_date" not in codes(get(client, "/products/p12"))  # shop_a only
    assert "was_price_stated" in codes(get(client, f"/products?retailer={ULTA}"))


def test_endpoints_without_prices_owe_only_the_snapshot_caveats() -> None:
    _, found = imported_view(load(ulta_doc()))
    assert [c.code for c in caveats(found, "coverage", frozenset())] == [
        CaveatCode.SNAPSHOT_IMPORT_DATE,
        CaveatCode.PARENT_LISTINGS_INCLUDED,
    ]
    first, *_ = caveats(found, "export_promotions", frozenset({ULTA}))
    assert first.code is CaveatCode.WAS_PRICE_STATED
    assert caveats(found, "summary", frozenset({"shop_a"})) == ()


def test_the_was_price_caveat_follows_withholding_and_is_owed_only_with_was_prices() -> None:
    at = datetime(2026, 9, 30, 21, 15, tzinfo=UTC)

    def first(shop: Imported) -> CaveatCode:
        return caveats((shop,), "promotions", frozenset())[0].code

    assert first(Imported(ULTA, (ULTA,), at, 3)) is CaveatCode.WAS_PRICE_STATED
    assert first(Imported(ULTA, (ULTA,), at, 3, withheld=True)) is CaveatCode.WAS_PRICE_UNVERIFIED
    assert first(Imported(ULTA, (ULTA,), at, 0)) is CaveatCode.SNAPSHOT_IMPORT_DATE


def test_a_sephora_only_dataset_has_no_dq_caveats(tmp_path: Path) -> None:
    d = doc()
    d["meta"]["test"] = False
    write(tmp_path, DatasetV3.model_validate(d))
    client = make_client(tmp_path)[0]
    for path in ("/summary", "/promotions", "/products?limit=5", "/coverage"):
        found = set(codes(get(client, path)))
        assert not {"snapshot_import_date", "was_price_unverified", "was_price_stated"} & found


COLLECTED_AT = "2026-09-29T10:00:00Z"


def late_import_doc() -> dict[str, Any]:
    """Collected offers end on 29 Sep; the Ulta import, later, set the file's cutoff and date."""
    d = ulta_doc()
    for product in d["products"]:
        for cid, o in product["offers"].items():
            if cid != ULTA:
                o["evidence"]["capturedAt"] = COLLECTED_AT
    d["meta"]["cutoff"] = IMPORTED_AT  # as an export that counted the Ulta capture wrote it
    d["meta"]["generatedAt"] = "2026-09-30T22:00:00Z"
    return d


def test_a_later_import_never_sets_the_cutoff_or_as_of_of_collected_data(tmp_path: Path) -> None:
    """Coordinator and Reviewer, before #134: /meta and /summary read collected offers only."""
    write(tmp_path, load(late_import_doc()))
    client = make_client(tmp_path)[0]
    meta = get(client, "/meta")
    assert (meta["data"]["cutoff"], meta["meta"]["cutoff"]) == (COLLECTED_AT, COLLECTED_AT)
    assert meta["data"]["dates"][-1] == "2026-09-30"  # the series dates are left as published
    for path in ("/summary", "/summary?retailer=shop_a"):
        body = get(client, path)
        assert body["data"]["retailer"] != ULTA
        assert body["data"]["asOf"] == "2026-09-29"
        assert body["data"]["freshness"]["cutoff"] == COLLECTED_AT
        assert body["data"]["freshness"]["status"] != "snapshot"
    ulta = get(client, f"/summary?retailer={ULTA}")
    assert ulta["data"]["asOf"] == "2026-09-30"  # unchanged since 1.5.0
    assert ulta["data"]["freshness"] == {
        "cutoff": IMPORTED_AT,
        "ageDays": ulta["data"]["freshness"]["ageDays"],
        "status": "snapshot",
    }


def test_meta_sources_never_give_a_collected_source_the_import_time(tmp_path: Path) -> None:
    """Reviewer, #120: each source's cutoff is its own latest capture, in a whole mixed file too;
    a source without offers is capped at the collected cutoff."""
    write(tmp_path, load(late_import_doc()))
    sources = get(make_client(tmp_path)[0], "/meta")["data"]["sources"]
    cutoffs = {s["source"]: s["cutoff"] for s in sources}
    assert cutoffs == {
        "shop_a": COLLECTED_AT,
        "shop_c": COLLECTED_AT,
        "shop_d": COLLECTED_AT,  # no offers: the file's cutoff, capped
        ULTA: IMPORTED_AT,  # the import keeps its own
    }


def test_the_as_of_cap_is_the_cutoff_day_in_the_market_time_zone(tmp_path: Path) -> None:
    """Reviewer, #135: 21:30Z on 29 Sep is 30 Sep 01:30 in Dubai, the day meta.dates count in."""
    d = late_import_doc()
    for product in d["products"]:
        for cid, o in product["offers"].items():
            if cid != ULTA:
                o["evidence"]["capturedAt"] = "2026-09-29T21:30:00Z"
    write(tmp_path, load(d))
    client = make_client(tmp_path)[0]
    assert get(client, "/meta")["data"]["cutoff"] == "2026-09-29T21:30:00Z"
    for path in ("/summary", "/summary?retailer=shop_a"):
        assert get(client, path)["data"]["asOf"] == "2026-09-30"


def test_the_default_summary_is_a_collected_context_even_if_the_import_is_larger() -> None:
    d = ulta_doc()
    for pid in ("p01", "p02", "p04"):
        offer(d, pid, "shop_a")["early"] = True  # leaves ulta_ae with the most counted offers
    ds = load(d)
    assert default_context(ds).id == ULTA
    assert default_context(ds, frozenset({ULTA})).id == "shop_a"
    assert default_context(ds, frozenset(c.id for c in ds.meta.contexts)).id == ULTA


def test_an_import_only_dataset_keeps_its_cutoff_and_says_it_is_a_snapshot(
    tmp_path: Path,
) -> None:
    d = late_import_doc()
    for product in d["products"]:
        product["offers"] = {c: o for c, o in product["offers"].items() if c == ULTA}
        product["matches"] = []
    d["products"] = [p for p in d["products"] if p["offers"]]
    ds = load(d)
    assert imported_view(ds)[0].meta.cutoff == ds.meta.cutoff
    write(tmp_path, ds)
    meta = get(make_client(tmp_path)[0], "/meta")
    assert meta["data"]["cutoff"] == IMPORTED_AT
    assert "snapshot_import_date" in codes(meta)


def test_pair_and_history_endpoints_owe_ulta_caveats_only_when_ulta_is_in_them(
    tmp_path: Path,
) -> None:
    """AIE and Reviewer, #131: the scope comes from the pair, the assortment ends or the series."""
    client = served(tmp_path)
    ulta_codes = {"was_price_stated", "snapshot_import_date", "parent_listings_included"}
    for path in (
        "/compare?retailers=shop_a,shop_c",
        "/index?retailers=shop_a,shop_c",
        "/assortment-gaps?missing_at=shop_a&present_at=shop_c",
        "/products/p12/history",
    ):
        assert not ulta_codes & set(codes(get(client, path))), path
    assert ulta_codes <= set(codes(get(client, f"/compare?retailers=shop_a,{ULTA}")))
    assert "snapshot_import_date" in codes(
        get(client, f"/assortment-gaps?missing_at={ULTA}&present_at=shop_a")
    )
    assert "was_price_stated" in codes(get(client, "/products/p03/history"))


def test_a_query_naming_retailers_in_two_fields_involves_all_of_them() -> None:
    """AIE, #137: a ``retailers`` pair must not hide a ``retailer`` list (the union is named)."""

    class Both(ContractModel):
        retailers: str | None = None
        retailer: tuple[str, ...] = ()

    assert _named(Both(retailers="shop_a,shop_c", retailer=(ULTA,))) == {"shop_a", "shop_c", ULTA}
    assert _named(Both(retailers="shop_a,shop_c")) == {"shop_a", "shop_c"}
    assert _named(Both(retailer=(ULTA,))) == {ULTA}
    assert _named(Both()) == frozenset()
    assert _named(ProductQuery(retailer=("shop_a", ULTA))) == {"shop_a", ULTA}


def test_an_imported_subject_is_served_as_its_snapshot(tmp_path: Path) -> None:
    body = get(served(tmp_path), f"/price-suggestions?subject={ULTA}&rival=shop_a")
    rows = {r["id"]: r for r in body["data"]["rows"]}
    priced = [r for r in rows.values() if r["subject"]["price"] is not None]
    assert priced
    for row in priced:
        assert row["subject"]["basis"] == "imported_snapshot"
        assert row["subject"]["observedOn"] == "2026-10-01"  # the import's local day
        assert row["subject"]["ageDays"] == -1  # the import's day is after the view's last
    assert all(r["rival"]["basis"] == "observed" for r in priced if r["rival"]["price"])
    assert any(r["outcome"] == "suggested" for r in rows.values())
    assert "snapshot_import_date" in codes(body)
    assert "was_price_stated" in codes(body)  # stated was-prices are served (#203)


def test_an_imported_rival_is_never_fresh(tmp_path: Path) -> None:
    body = get(served(tmp_path), f"/price-suggestions?subject=shop_a&rival={ULTA}")
    assert (body["status"], body["reason"]) == ("not_enough_data", "retailer_partial")
    assert not body["data"]["outcomes"]
    reasons = {r["reason"] for r in body["data"]["rows"]}
    assert "stale_observation" in reasons
    assert None not in reasons
