"""``/compare`` for the Overlap view (API 1.17.0): each row's ``match``, the gap of an exact pair
that is only unreviewed, ``rows=overlap`` and ``sort``. Nothing added is counted."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from api_fixture import Client, bearer, make_client, served_dataset, write
from pi_dataset import Dataset

API = "/api/v1"
PAIR = "/compare?retailers=shop_a,shop_b"
COUNTED = ["p01", "p02", "p03", "p04", "p05", "p06"]


def proposed_family(ds: Dataset) -> Dataset:
    """The fixture with p09's family edge proposed: an unreviewed edge that is not exact."""
    doc = ds.model_dump(mode="json", by_alias=True)
    for product in doc["products"]:
        if product["id"] == "p09":
            product["matches"][0].update(reviewState="proposed", decidedBy=None)
    return Dataset.model_validate(doc)


@pytest.fixture
def client(tmp_path: Path) -> Client:
    write(tmp_path, proposed_family(served_dataset()))
    return make_client(tmp_path)[0]


def data(client: Client, query: str = "") -> Any:
    response = client.get(f"{API}{PAIR}{query}", headers=bearer())
    assert response.status_code == 200, response.text
    return response.json()["data"]


def rows(client: Client, query: str = "") -> dict[str, Any]:
    return {r["id"]: r for r in data(client, query)["rows"]}


def test_a_default_read_never_carries_an_unreviewed_gap(client: Client) -> None:
    """Reviewer on #220: the assistant's compare tool and the CSV read every row's gap."""
    p07 = rows(client)["p07"]
    assert (p07["counted"], p07["excludedReason"]) == (False, "match_unreviewed")
    assert p07["gap"] is None
    assert p07["match"]["reviewState"] == "proposed"


def test_rows_overlap_gives_an_unreviewed_exact_pair_its_gap_uncounted(client: Client) -> None:
    p07 = rows(client, "&rows=overlap")["p07"]
    assert (p07["counted"], p07["excludedReason"]) == (False, "match_unreviewed")
    assert p07["gap"] == {
        "amount": {"amount": "0.00", "currency": "AED", "minor": 0},
        "pct": "0.0",
        "cheaper": "equal",
    }


def test_no_gap_for_rejected_non_exact_or_unproven_rows(client: Client) -> None:
    assert rows(client)["p09"]["excludedReason"] == "match_unreviewed"  # proposed, but family
    overlap = rows(client, "&rows=overlap")  # only rows with a gap
    for product in ("p08", "p09", "p10", "p11", "p12", "p13", "p14", "p16"):
        assert product not in overlap, product


def test_each_row_carries_its_retailers_edge(client: Client) -> None:
    by_id = rows(client)
    assert by_id["p01"]["match"] == {
        "matchClass": "exact",
        "reviewState": "approved",
        "decidedBy": by_id["p01"]["match"]["decidedBy"],
        "method": by_id["p01"]["match"]["method"],
        "confidence": by_id["p01"]["match"]["confidence"],
    }
    assert by_id["p01"]["match"]["decidedBy"] is not None
    assert (by_id["p03"]["match"]["reviewState"], by_id["p07"]["match"]["reviewState"]) == (
        "locked",
        "proposed",
    )
    assert by_id["p07"]["match"]["decidedBy"] is None
    assert by_id["p08"]["match"]["reviewState"] == "rejected"
    assert by_id["p09"]["match"]["matchClass"] == "family"
    assert by_id["p12"]["match"] is None  # no edge
    assert by_id["p16"]["match"] is None  # edges to shop_c only: never through a third shop


def test_summary_groups_sides_and_cohort_stay_counted_only(client: Client) -> None:
    every = data(client, "&groupBy=brand")
    overlap = data(client, "&groupBy=brand&rows=overlap&sort=gap&limit=2")
    for key in ("summary", "groups", "sides"):
        assert overlap[key] == every[key]
    assert every["summary"]["n"] == len(COUNTED)
    assert sum(every["summary"]["cheaperCounts"].values()) + every["summary"]["equalCount"] == 6


def test_rows_overlap_keeps_counted_and_unreviewed_exact_rows(client: Client) -> None:
    doc = data(client, "&rows=overlap")
    assert sorted(r["id"] for r in doc["rows"]) == [*COUNTED, "p07"]
    assert (doc["total"], doc["truncated"]) == (7, False)


def test_sort_gap_ranks_by_absolute_gap_then_id_before_limit(client: Client) -> None:
    doc = data(client, "&rows=overlap&sort=gap&limit=3")
    assert [r["id"] for r in doc["rows"]] == ["p05", "p01", "p03"]
    assert (doc["total"], doc["truncated"]) == (7, True)
    tail = [r["id"] for r in data(client, "&rows=overlap&sort=gap")["rows"]][-2:]
    assert tail == ["p02", "p07"]  # equal 0% gaps: by id


def test_sort_name_orders_by_name_then_id(client: Client) -> None:
    listed = data(client, "&sort=name")["rows"]
    assert [(r["name"].casefold(), r["id"]) for r in listed] == sorted(
        (r["name"].casefold(), r["id"]) for r in listed
    )


def test_unsorted_limit_still_ranks_counted_gaps_only(client: Client) -> None:
    """Before 1.17.0 a limited /compare ranked counted rows; an unreviewed gap never jumps in."""
    doc = data(client, "&rows=overlap&limit=7")
    # p07 shows its gap but ranks with the gapless rows, first of them by id.
    assert [r["id"] for r in doc["rows"]] == ["p05", "p01", "p03", "p06", "p04", "p02", "p07"]


def test_the_export_carries_match_but_no_unreviewed_gap(client: Client) -> None:
    response = client.get(
        f"{API}/export/compare?retailers=shop_a,shop_b&format=jsonl", headers=bearer()
    )
    assert response.status_code == 200
    rows = {r["id"]: r for r in map(json.loads, response.text.splitlines()[1:])}
    assert rows["p07"]["counted"] is False
    assert rows["p07"]["gap"] is None
    assert rows["p07"]["match"]["reviewState"] == "proposed"
    assert rows["p12"]["match"] is None
