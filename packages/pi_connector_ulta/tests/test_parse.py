from decimal import Decimal
from pathlib import Path

import pytest

from pi_connector_ulta import ParseError, parse_product_html, parse_product_json
from pi_connector_ulta.models import StockState

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_complete_synthetic_json() -> None:
    record = parse_product_json((FIXTURES / "product_SYNTHETIC.json").read_text())
    assert record.source_product_id == "P100"
    assert record.content.name.ar == "بلسم جلو"
    assert record.ratings.average == Decimal("4.5")
    assert len(record.variants) == 2
    assert record.variants[0].prices.current.amount == Decimal("90.00")
    assert record.variants[1].prices.promo.amount is None
    assert record.variants[1].stock.state is StockState.UNKNOWN


def test_parse_synthetic_html_preserves_blocked_access_as_unknown_stock() -> None:
    record = parse_product_html((FIXTURES / "product_page_SYNTHETIC.html").read_text())
    assert record.source_product_id == "P200"
    assert record.variants[0].stock.state is StockState.UNKNOWN
    assert record.variants[0].stock.reason == "source access blocked"


@pytest.mark.parametrize("document", ["{", "null", '{"source_product_id": "P1"}', "NaN"])
def test_invalid_json_raises_parse_error(document: str) -> None:
    with pytest.raises(ParseError):
        parse_product_json(document)


@pytest.mark.parametrize(
    "document",
    ["<html></html>", '<script id="ulta-source-record">{}</script>' * 2],
)
def test_html_requires_one_source_record(document: str) -> None:
    with pytest.raises(ParseError, match="exactly one"):
        parse_product_html(document)
