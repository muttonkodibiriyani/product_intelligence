"""``pi.similar/v1`` round-trips and refuses anything that reads like an identity claim."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from pi_similar.model import dump_similar, load_similar


def _competitor(product: str = "q1", retailer: str = "b", score: str = "0.7000") -> dict[str, Any]:
    return {
        "product": product,
        "retailer": retailer,
        "score": score,
        "signals": {"text": "0.8000", "image": None, "price": "0.5000", "attributes": None},
        "reasons": ["price_band:adjacent", "other_brand"],
        "sameBrand": False,
    }


def _file(*competitors: dict[str, Any], k: int = 5) -> dict[str, Any]:
    return {
        "schema": "pi.similar/v1",
        "kind": "similar_not_same_product",
        "meta": {
            "scope": "ae/beauty",
            "generatedAt": "2026-10-06T00:00:00Z",
            "models": {"text": "test/words@1"},
            "weightsVersion": "2026-10-06.1",
            "weights": {"text": "0.4"},
            "k": k,
        },
        "similar": [{"product": "p1", "retailer": "a", "competitors": list(competitors)}],
    }


def test_round_trip() -> None:
    raw = json.dumps(_file(_competitor(), _competitor("q2", score="0.6000")))
    loaded = load_similar(raw)
    assert load_similar(dump_similar(loaded)) == loaded
    assert json.loads(dump_similar(loaded))["kind"] == "similar_not_same_product"


@pytest.mark.parametrize(
    ("competitors", "k", "error"),
    [
        ((_competitor(retailer="a"),), 5, "same retailer"),
        ((_competitor(product="p1"),), 5, "never its own competitor"),
        ((_competitor("q1", score="0.5000"), _competitor("q2", score="0.6000")), 5, "ordered"),
        ((_competitor("q1"), _competitor("q2", score="0.6000")), 1, "more than k=1"),
        ((_competitor(score="1.5000"),), 5, "pattern"),
    ],
)
def test_invalid_files_fail(competitors: tuple[dict[str, Any], ...], k: int, error: str) -> None:
    with pytest.raises(ValidationError, match=error):
        load_similar(json.dumps(_file(*competitors, k=k)))


@pytest.mark.parametrize(
    "signals",
    [
        {"text": "0.8000", "image": None, "price": None, "attributes": None},
        {"text": None, "image": None, "price": "1.0000", "attributes": "1.0000"},
    ],
)
def test_a_competitor_needs_two_signals_one_of_them_text_or_image(signals: dict[str, Any]) -> None:
    competitor = _competitor() | {"signals": signals}
    with pytest.raises(ValidationError, match="needs 2 signals"):
        load_similar(json.dumps(_file(competitor)))


def test_a_product_is_listed_once() -> None:
    raw = _file(_competitor())
    raw["similar"] = raw["similar"] * 2
    with pytest.raises(ValidationError, match="listed twice"):
        load_similar(json.dumps(raw))
