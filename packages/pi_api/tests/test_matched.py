"""Ruling A: ``matched=true`` means an exact, non-rejected edge (proposed included); cards say
whether it was reviewed; counted metrics still take approved/locked edges only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from api_fixture import Client, bearer, make_client, served_dataset, write
from pi_api import catalog
from pi_dataset import dump_dataset, load_any
from pi_metrics import view
from pi_metrics.view import as_v3

API = "/api/v1"
#: The fixture's edges: p01-p06, p10, p11, p13 exact approved/locked (shop_a-shop_b); p16 exact
#: approved (shop_a-shop_c, shop_b-shop_c); p07 exact proposed; p08 exact rejected only;
#: p09 family (not exact) approved only; p12, p14, p15 no edge.
REVIEWED = ["p01", "p02", "p03", "p04", "p05", "p06", "p10", "p11", "p13", "p16"]
PROPOSED = "p07"


@pytest.fixture
def client(tmp_path: Path) -> Client:
    write(tmp_path, served_dataset())
    return make_client(tmp_path)[0]


def get(client: Client, path: str) -> Any:
    response = client.get(f"{API}{path}", headers=bearer())
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_matched_true_is_every_exact_non_rejected_edge_proposed_included(client: Client) -> None:
    matched = get(client, "/products?matched=true&limit=100")["items"]
    assert sorted(c["id"] for c in matched) == sorted([*REVIEWED, PROPOSED])
    # Reverting the rule to approved/locked only (COUNTED_STATES) drops p07 and fails here.
    assert PROPOSED in {c["id"] for c in matched}


def test_rejected_only_and_non_exact_only_products_are_not_matched(client: Client) -> None:
    unmatched = get(client, "/products?matched=false&limit=100")["items"]
    assert [c["id"] for c in unmatched] == ["p08", "p09", "p12", "p14", "p15"]
    assert {c["matchReview"] for c in unmatched} == {None}


def test_matched_false_is_the_exact_complement(client: Client) -> None:
    every = {c["id"] for c in get(client, "/products?limit=100")["items"]}
    yes = {c["id"] for c in get(client, "/products?matched=true&limit=100")["items"]}
    no = {c["id"] for c in get(client, "/products?matched=false&limit=100")["items"]}
    assert yes | no == every
    assert not yes & no


def test_cards_label_a_proposed_exact_edge_unreviewed(client: Client) -> None:
    cards = {c["id"]: c for c in get(client, "/products?matched=true&limit=100")["items"]}
    assert cards[PROPOSED]["matchReview"] == "unreviewed"
    assert {cards[i]["matchReview"] for i in REVIEWED} == {"reviewed"}
    assert get(client, f"/products/{PROPOSED}")["card"]["matchReview"] == "unreviewed"


def test_an_unclear_identity_is_never_matched(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pair compare would drop as ``no_match`` for ``identity_unclear`` does not count."""
    ds = as_v3(load_any(dump_dataset(served_dataset())))
    product = next(p for p in ds.products if p.id == "p01")
    assert catalog.match_review(ds, product) is catalog.MatchReview.REVIEWED
    monkeypatch.setattr(view, "identity_unclear", lambda _ds, _p, retailer: retailer == "shop_b")
    assert catalog.matching_edges(ds, product) == []
    assert catalog.match_review(ds, product) is None


def test_no_counted_metric_moves(client: Client) -> None:
    """The proposed exact pair is matched, yet compare, coverage and pair pricing still leave it
    out: COUNTED_STATES is untouched (the metric goldens differ only in apiVersion)."""
    rows = {r["id"]: r for r in get(client, "/compare?retailers=shop_a,shop_b")["rows"]}
    assert rows[PROPOSED]["excludedReason"] == "match_unreviewed"
    assert rows[PROPOSED]["counted"] is False
    assert rows[PROPOSED]["gap"] is None
    counted = sorted(i for i, r in rows.items() if r["counted"])
    assert counted == ["p01", "p02", "p03", "p04", "p05", "p06"]
    shops = {r["id"]: r["matchedCount"] for r in get(client, "/coverage")["retailers"]}
    assert shops["shop_a"] == 10  # p07 would make it 11
    reasons = get(client, "/price-suggestions?subject=shop_a&rival=shop_b")["reasons"]
    assert reasons["match_unreviewed"] == 1
