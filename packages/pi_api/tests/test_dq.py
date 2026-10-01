"""The read-time view of an imported retailer (``pi_api.dq``, API 1.5.0).

``ulta_ae`` here is the fixture's ``shop_b`` renamed. All six of its offers that carry a
was-price carry one equal to the price, so without the view its promotion share would be
measured as 0%, the figure the owner ruled out.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from api_fixture import Client, bearer, make_client, write
from pi_api.dq import IMPORTED, Imported, caveats, imported_view
from pi_dataset import DatasetV3
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


def test_ulta_ae_is_the_imported_retailer() -> None:
    assert frozenset({ULTA}) == IMPORTED


def test_a_dataset_without_an_imported_retailer_is_served_as_the_same_object() -> None:
    ds = load(doc())
    served_ds, found = imported_view(ds)
    assert served_ds is ds
    assert found == ()


def test_the_view_clears_only_the_imported_was_prices_and_finds_the_import_date() -> None:
    ds = load(ulta_doc())
    view, (found,) = imported_view(ds)
    assert (found.retailer, found.contexts, found.was_prices) == (ULTA, (ULTA,), 6)
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


def test_without_the_view_ulta_was_prices_would_be_measured() -> None:
    """The failure the view prevents: unverified was-prices read as a promotion share."""
    d = ulta_doc()
    assert summary(load(d), ULTA).data.promo_share_pct == Decimal("100") / 6  # p03 only
    offer(d, "p03", ULTA)["series"]["price"][-1] = offer(d, "p03", ULTA)["series"]["regular"][-1]
    assert summary(load(d), ULTA).data.promo_share_pct == 0  # "no promotions": ruled out


def test_metrics_withhold_promotions_of_an_unverified_context_with_a_reason() -> None:
    view, _ = imported_view(load(ulta_doc()))
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


def test_summary_of_ulta_is_a_withheld_promotion_and_a_dated_snapshot(tmp_path: Path) -> None:
    body = get(served(tmp_path), f"/summary?retailer={ULTA}")
    data = body["data"]
    assert data["promoSharePct"] is None
    assert data["promoSharePct"] != 0
    assert (data["promoDepth"], data["topDiscounts"]) == (None, None)
    assert {"section": "promotions", "reason": "was_price_unverified"} in data["withheld"]
    assert data["freshness"]["status"] == "snapshot"
    assert data["freshness"]["cutoff"] == IMPORTED_AT
    assert codes(body)[-3:] == [
        "was_price_unverified",
        "snapshot_import_date",
        "parent_listings_included",
    ]
    snapshot = next(c for c in body["caveats"] if c["code"] == "snapshot_import_date")
    assert snapshot["params"] == {"retailer": ULTA, "date": "2026-10-01"}
    assert snapshot["en"] == SNAPSHOT_EN
    assert "fresh" not in json.dumps(data["freshness"])


def test_another_retailers_summary_has_no_ulta_caveat(tmp_path: Path) -> None:
    body = get(served(tmp_path), "/summary?retailer=shop_a")
    assert not {c.value for c in CaveatCode if "snapshot" in c.value} & set(codes(body))
    assert "was_price_unverified" not in codes(body)
    assert body["data"]["freshness"]["status"] != "snapshot"
    assert body["data"]["promoSharePct"] is not None


def test_promotions_withhold_ulta_and_keep_the_others(tmp_path: Path) -> None:
    body = get(served(tmp_path), "/promotions")
    shares = {r["retailer"]: r for r in body["data"]["retailers"]}
    assert shares[ULTA]["share"] is None
    assert shares[ULTA]["reason"] == "was_price_unverified"
    assert shares["shop_a"]["share"] is not None
    assert all(item["retailer"] != ULTA for item in body["data"]["items"])
    assert body["reason"] == "was_price_unverified"
    assert "was-prices are unverified" in body["detail"]["en"]
    assert "was_price_unverified" in codes(body)


def test_promotions_of_shop_a_alone_owe_no_ulta_caveat(tmp_path: Path) -> None:
    body = get(served(tmp_path), "/promotions?retailer=shop_a")
    assert codes(body) == []
    assert body["status"] == "ok"


def test_a_product_shows_no_ulta_was_price_or_discount(tmp_path: Path) -> None:
    client = served(tmp_path)
    body = get(client, "/products/p03")
    offers = {o["retailer"]: o for o in body["data"]["offers"]}
    assert (offers[ULTA]["regular"], offers[ULTA]["promoPct"]) == (None, None)
    assert offers[ULTA]["price"]["amount"] == "80.00"
    assert offers["shop_a"]["regular"] is not None
    assert codes(body)[-3:] == [
        "was_price_unverified",
        "snapshot_import_date",
        "parent_listings_included",
    ]
    assert "snapshot_import_date" not in codes(get(client, "/products/p12"))  # shop_a only
    assert "was_price_unverified" in codes(get(client, f"/products?retailer={ULTA}"))


def test_endpoints_without_prices_owe_only_the_snapshot_caveats() -> None:
    _, found = imported_view(load(ulta_doc()))
    assert [c.code for c in caveats(found, "coverage", frozenset())] == [
        CaveatCode.SNAPSHOT_IMPORT_DATE,
        CaveatCode.PARENT_LISTINGS_INCLUDED,
    ]
    first, *_ = caveats(found, "export_promotions", frozenset({ULTA}))
    assert first.code is CaveatCode.WAS_PRICE_UNVERIFIED
    assert caveats(found, "summary", frozenset({"shop_a"})) == ()


def test_a_sephora_only_dataset_has_no_dq_caveats(tmp_path: Path) -> None:
    d = doc()
    d["meta"]["test"] = False
    write(tmp_path, DatasetV3.model_validate(d))
    client = make_client(tmp_path)[0]
    for path in ("/summary", "/promotions", "/products?limit=5", "/coverage"):
        assert not {"snapshot_import_date", "was_price_unverified"} & set(codes(get(client, path)))


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
