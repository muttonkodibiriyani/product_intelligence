"""Page-JSON captures are read only when robots.txt allows their URL (coordinator ruling)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from ulta_snapshot.load import allowed_captures, page_product, robots_for

FIXTURES = Path(__file__).parents[3] / "packages/pi_connector_ulta/tests/fixtures"
BASE = "https://www.ulta.ae"
GET_QUERY = f"{BASE}/graphql?query=query%20products&variables=%7B%7D"
POST_BARE = f"{BASE}/graphql"
SHADE = "346900338"  # not selected on the page; its price exists only in the page JSON


@pytest.fixture
def robots(tmp_path: Path) -> Any:
    (tmp_path / "robots.txt").write_text((FIXTURES / "ulta_ae_robots.txt").read_text())
    return robots_for(tmp_path, enabled=True)


def _rec(capture_url: str, status: int = 200) -> dict[str, Any]:
    return {
        "at": "2026-10-01T10:00:00+00:00",
        "url": f"{BASE}/en/buy-kylie-cosmetics-lip-and-cheek-tint",
        "lang": "en",
        "status": 200,
        "html": (FIXTURES / "ulta_ae_pdp_en_kylie_tint.html").read_text(),
        "captures": [
            {
                "url": capture_url,
                "status": status,
                "body": (FIXTURES / "ulta_ae_page_json_kylie_tint.json").read_text(),
            }
        ],
    }


def _price(rec: dict[str, Any], robots: Any) -> Decimal | None:
    product = page_product(rec, robots)
    assert product is not None
    return next(v for v in product.variants if v.sku == SHADE).final.amount


def test_disallowed_get_graphql_query_is_never_parsed(robots: Any) -> None:
    rec = _rec(GET_QUERY)
    assert allowed_captures(rec, robots) == ([], 1)
    assert _price(rec, robots) is None  # DOM only: the refused JSON filled nothing


def test_allowed_bare_graphql_capture_fills_dom_gaps(robots: Any) -> None:
    rec = _rec(POST_BARE)
    usable, refused = allowed_captures(rec, robots)
    assert len(usable) == 1
    assert refused == 0
    assert _price(rec, robots) == Decimal("155")


@pytest.mark.parametrize(
    "url", ["https://evil.example/graphql", "http://www.ulta.ae/graphql", "not a url"]
)
def test_off_host_captures_are_refused(robots: Any, url: str) -> None:
    assert allowed_captures(_rec(url), robots) == ([], 1)


def test_non_200_capture_is_refused(robots: Any) -> None:
    assert allowed_captures(_rec(POST_BARE, status=403), robots) == ([], 1)


def test_fails_closed_without_robots(tmp_path: Path) -> None:
    assert robots_for(tmp_path, enabled=True) is None  # no robots.txt in the snapshot
    rec = _rec(POST_BARE)
    assert allowed_captures(rec, None) == ([], 1)
    assert _price(rec, None) is None


def test_flag_off_means_no_page_json(tmp_path: Path) -> None:
    (tmp_path / "robots.txt").write_text((FIXTURES / "ulta_ae_robots.txt").read_text())
    assert robots_for(tmp_path, enabled=False) is None
