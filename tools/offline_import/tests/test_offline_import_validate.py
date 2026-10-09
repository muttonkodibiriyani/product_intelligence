"""Mapping config, row validation, the report and the dry-run CLI. No database needed."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from pydantic import ValidationError

from offline_import.__main__ import main
from offline_import.mapping import ImportMapping, load_mapping
from offline_import.validate import ImportReport as Report
from offline_import.validate import parse_decimal, validate_file, validate_rows
from pi_core import AvailabilityState

FIXTURES = Path(__file__).parent / "fixtures"
CSV = FIXTURES / "acme_feed.csv"
JSON_FEED = FIXTURES / "acme_feed.json"
MAPPING = FIXTURES / "acme_mapping.json"
PROMO = {"price_promo": "s"}


def _config(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(MAPPING.read_text())
    return data | overrides


def _json_mapping() -> ImportMapping:
    return ImportMapping.model_validate(
        _config(
            observed_at=None,
            json_items_path="data.items",
            decimal_separator=",",
            url_template="https://acme-beauty.example/p/{listing_key}",
            columns={
                "listing_key": "variant_id",
                "name": "name",
                "brand": "brand",
                "size": "size",
                "url": "url",
                "price_current": "price",
                "availability": "stock",
                "observed_at": "updated_at",
            },
            availability_map={"true": "in_stock", "false": "out_of_stock"},
        )
    )


# ---------------------------------------------------------------- mapping
def test_fixture_mapping_loads() -> None:
    mapping = load_mapping(MAPPING)
    assert mapping.source.kind == "offline"
    assert mapping.currency == "AED"
    assert mapping.observed_at == datetime(2026, 9, 15, 4, tzinfo=UTC)
    assert mapping.availability_map["yes"] is AvailabilityState.IN_STOCK
    assert mapping.columns.mapped()["listing_key"] == "Variant ID"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"surprise": 1}, "Extra inputs are not permitted"),
        ({"columns": {"listing_key": "id", "pricee": "p"}}, "Extra inputs are not permitted"),
        ({"columns": {"sku": "SKU"}}, "listing_key"),
        ({"currency": "SAR"}, "AE prices are in AED"),
        ({"currency": "XXX"}, "unsupported currency"),
        ({"country": "uae"}, "String should match pattern"),
        ({"time_zone": "Mars/Olympus"}, "unknown time zone"),
        ({"observed_at": None}, "import time is never used"),
        # never inferred: a priced feed without a declaration is an error, not 'on_promotion'
        ({"regular_stated": None}, "must declare regular_stated"),
        ({"regular_stated": "sometimes"}, "on_promotion"),
        ({"observed_at": "2026-09-15T08:00:00"}, "timezone"),
        ({"availability_map": {}}, "needs an availability_map"),
        ({"availability_map": {"gone": "removed"}}, "cannot assert"),
        ({"url_template": "https://x.example/{name}"}, "url_template may only use"),
        ({"url_template": None}, "an http\\(s\\) listing URL is required"),
        ({"url_template": "file:///feeds/{listing_key}"}, "url_template must be an http"),
    ],
)
def test_mapping_rejects(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ImportMapping.model_validate(_config(**overrides))


def test_a_feed_without_prices_needs_no_regular_declaration() -> None:
    config = _config(regular_stated=None, columns={"listing_key": "k", "availability": "a"})
    assert ImportMapping.model_validate(config).regular_stated is None


def test_a_feed_declared_not_collected_rejects_a_stated_regular_or_promo() -> None:
    mapping = ImportMapping.model_validate(
        _config(
            regular_stated="not_collected",
            columns={"listing_key": "k", "price_current": "p", "price_regular": "r"} | PROMO,
        )
    )
    report = Report(file="mem", sha256="0" * 64, format="csv")
    validate_rows(
        [
            (2, {"k": "A", "p": "10", "r": "", "s": ""}),
            (3, {"k": "B", "p": "10", "r": "12", "s": ""}),
            (4, {"k": "C", "p": "10", "r": "", "s": "10"}),
        ],
        mapping,
        report,
    )
    assert [r.listing_key for r in report.accepted] == ["A"]
    assert {r.row: r.reasons for r in report.rejected} == {
        3: ["price_regular on a feed declared regular_stated not_collected"],
        4: ["price_promo on a feed declared regular_stated not_collected"],
    }


def test_other_market_needs_only_a_known_currency() -> None:
    mapping = ImportMapping.model_validate(_config(country="KW", currency="KWD"))
    assert mapping.currency == "KWD"


def test_yaml_mapping_needs_pyyaml(tmp_path: Path) -> None:
    cfg = tmp_path / "m.yaml"
    cfg.write_text(json.dumps(_config()))  # JSON is valid YAML
    try:
        import yaml  # type: ignore[import-untyped]  # noqa: F401, PLC0415
    except ModuleNotFoundError:
        with pytest.raises(ValueError, match="need PyYAML"):
            load_mapping(cfg)
    else:  # pragma: no cover - PyYAML is not a workspace dependency
        assert load_mapping(cfg).source.name == "acme_beauty_partner_feed"


def test_parse_decimal_separators() -> None:
    assert parse_decimal("1,150.50", ".") == Decimal("1150.50")
    assert parse_decimal("1.150,50", ",") == Decimal("1150.50")
    assert parse_decimal(" 12 ", ".") == Decimal(12)
    assert parse_decimal(7, ".") == Decimal(7)
    assert parse_decimal(Decimal("1.5"), ".") == Decimal("1.5")
    assert parse_decimal("", ".") is None
    for bad in ("abc", "NaN", "Infinity", True):
        with pytest.raises(ValueError, match="not a number"):
            parse_decimal(bad, ".")


# ---------------------------------------------------------------- validation report
def test_csv_report() -> None:
    report = validate_file(CSV, load_mapping(MAPPING))
    assert report.rows == 11
    assert report.format == "csv"
    assert len(report.sha256) == 64
    accepted = {r.listing_key: r for r in report.accepted}
    assert list(accepted) == ["AB-1001", "AB-1002", "AB-1003", "AB-1008", "AB-1009"]
    reasons = {r.row: r.reasons for r in report.rejected}
    assert reasons == {
        5: ["price_regular must be > 0 (got 0); leave it blank when not published"],
        6: ["missing listing_key"],
        7: ["duplicate listing_key (first at row 2)"],
        8: ["bad price_regular: 'abc' is not a number"],
        9: ["unknown availability value 'maybe'"],
        10: ["price_regular must be > 0 (got -5); leave it blank when not published"],
    }

    lipstick = accepted["AB-1001"]
    assert lipstick.price_current == Decimal("89.00")
    assert lipstick.availability is AvailabilityState.IN_STOCK
    assert lipstick.availability_observed
    assert lipstick.stock_qty == 12
    assert lipstick.text["name_ar"] == "أحمر شفاه أكمي"

    promo = accepted["AB-1002"]
    assert (promo.price_current, promo.price_regular, promo.price_promo) == (
        Decimal("99.00"),
        Decimal("120.00"),
        Decimal("99.00"),
    )
    assert promo.availability is AvailabilityState.OUT_OF_STOCK

    serum = accepted["AB-1003"]  # no price: None, never 0; stock quantity 5 -> in stock
    assert serum.price_current is None
    assert serum.availability is AvailabilityState.IN_STOCK

    assert accepted["AB-1008"].price_current == Decimal("1150.50")
    assert accepted["AB-1008"].availability is AvailabilityState.LOW_STOCK

    cream = accepted["AB-1009"]  # nothing published about stock: not observed, not out of stock
    assert cream.availability is AvailabilityState.NOT_OBSERVED
    assert not cream.availability_observed
    assert cream.text["gtin"] is None

    warnings = {(w.row, w.message) for w in report.warnings}
    assert (4, "no price published") in warnings
    assert (12, "gtin '1234567890123' is not a valid GTIN; dropped") in warnings

    as_json = report.to_json()
    assert as_json["accepted"] == 5
    assert len(as_json["rejected"]) == 6
    json.dumps(as_json)  # serialisable
    summary = report.summary()
    assert "11 rows, 5 accepted, 6 rejected" in summary
    assert "rejected row 9: unknown availability value 'maybe'" in summary


def test_json_report_observed_at_column_and_decimal_comma() -> None:
    report = validate_file(JSON_FEED, _json_mapping())
    assert report.format == "json"
    first, second = report.accepted
    assert first.price_current == Decimal("55.5")
    assert first.observed_at == datetime(2026, 9, 20, 6, tzinfo=UTC)
    assert first.text["url"] == "https://acme-beauty.example/p/AB-2001"
    assert second.price_current == Decimal("22.00")
    assert second.observed_at == datetime(2026, 9, 20, 6, tzinfo=UTC)  # naive = Asia/Dubai
    assert second.availability is AvailabilityState.OUT_OF_STOCK
    assert [(r.row, r.reasons) for r in report.rejected] == [
        (3, ["bad observed_at 'yesterday' (ISO 8601 expected)"])
    ]


def test_row_level_edge_cases() -> None:
    mapping = _json_mapping()
    report = Report(file="mem", sha256="0" * 64, format="json")
    rows: list[tuple[int, dict[str, object]]] = [
        (1, {"variant_id": "K1", "price": "1,00001", "updated_at": "2026-09-20T10:00:00Z"}),
        (2, {"variant_id": "K2", "price": "1" + "0" * 15, "updated_at": "2026-09-20T10:00:00Z"}),
        (3, {"variant_id": "K3", "updated_at": None}),
        (4, {"variant_id": "K4", "updated_at": "2026-09-20T10:00:00Z", "stock": "unknown"}),
    ]
    validate_rows(rows, mapping, report)
    assert {r.row: r.reasons for r in report.rejected} == {
        1: ["price_current 1.00001 does not fit numeric(18,4)"],
        2: ["price_current 1000000000000000 does not fit numeric(18,4)"],
        3: ["missing observed_at"],
        4: ["unknown availability value 'unknown'"],
    }
    assert (0, None, "mapped column 'url' (url) is not in the file") in {
        (w.row, w.listing_key, w.message) for w in report.warnings
    }


def test_stock_quantity_rules() -> None:
    mapping = ImportMapping.model_validate(
        _config(columns={"listing_key": "k", "stock_qty": "q", "price_current": "p"})
    )
    report = Report(file="mem", sha256="0" * 64, format="csv")
    validate_rows(
        [
            (2, {"k": "A", "q": "0", "p": "10"}),
            (3, {"k": "B", "q": "-1", "p": "10"}),
            (4, {"k": "C", "q": "1.5", "p": "10"}),
            (5, {"k": "D", "q": "lots", "p": "10"}),
            (6, {"k": "E", "q": "", "p": "10", "extra": "x"}),
        ],
        mapping,
        report,
    )
    states = {r.listing_key: (r.availability, r.availability_observed) for r in report.accepted}
    # A published zero quantity is an explicit stock-out; nothing published is not observed.
    assert states == {
        "A": (AvailabilityState.OUT_OF_STOCK, True),
        "E": (AvailabilityState.NOT_OBSERVED, False),
    }
    assert [r.row for r in report.rejected] == [3, 4, 5]


def test_unknown_mapped_state_is_not_an_observation() -> None:
    mapping = ImportMapping.model_validate(
        _config(
            columns={"listing_key": "k", "availability": "a"},
            availability_map={"?": "unknown", "n/a": "not_observed"},
        )
    )
    report = validate_rows(
        [(2, {"k": "A", "a": "?"}), (3, {"k": "B", "a": "N/A"})],
        mapping,
        Report(file="mem", sha256="0" * 64, format="csv"),
    )
    assert [(r.availability, r.availability_observed) for r in report.accepted] == [
        (AvailabilityState.UNKNOWN, False),
        (AvailabilityState.NOT_OBSERVED, False),
    ]


def test_long_report_summary_is_capped() -> None:
    mapping = ImportMapping.model_validate(_config(columns={"listing_key": "k"}))
    report = validate_rows(
        [(i, {"k": ""}) for i in range(2, 30)],
        mapping,
        Report(file="mem", sha256="0" * 64, format="csv"),
    )
    assert report.summary().endswith("(see the JSON report for the full list)")


# ---------------------------------------------------------------- CLI
def test_dry_run_never_touches_the_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PI_DATABASE_URL", raising=False)

    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("dry run opened a database connection")

    monkeypatch.setattr(psycopg, "connect", refuse)
    out = tmp_path / "report.json"
    assert main([str(CSV), "--mapping", str(MAPPING), "--dry-run", "--report", str(out)]) == 0
    report = json.loads(out.read_text())
    assert report["dry_run"] is True
    assert report["accepted"] == 5
    assert "load" not in report
    assert len(report["rejected"]) == 6
    captured = capsys.readouterr()
    assert json.loads(captured.out)["rows"] == 11
    assert "5 accepted, 6 rejected" in captured.err


def test_cli_reports_unusable_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_config(surprise=1)))
    assert main([str(CSV), "--mapping", str(bad), "--dry-run"]) == 2
    assert "Extra inputs are not permitted" in capsys.readouterr().err
    assert main([str(tmp_path / "missing.csv"), "--mapping", str(MAPPING), "--dry-run"]) == 2


def test_listing_urls_must_be_http() -> None:
    at = "2026-09-20T10:00:00Z"
    rows: list[tuple[int, dict[str, object]]] = [
        (1, {"variant_id": "U1", "url": "file:///home/x/feed.json", "updated_at": at}),
        (2, {"variant_id": "U2", "url": "https://acme-beauty.example/p/U2", "updated_at": at}),
    ]
    templated = Report(file="mem", sha256="0" * 64, format="json")
    validate_rows(rows, _json_mapping(), templated)
    assert [r.text["url"] for r in templated.accepted] == [None, "https://acme-beauty.example/p/U2"]
    assert any("not an http(s) URL; url_template used" in w.message for w in templated.warnings)

    no_template = _json_mapping().model_copy(update={"url_template": None})
    strict = Report(file="mem", sha256="0" * 64, format="json")
    validate_rows(rows, no_template, strict)
    assert {r.row: r.reasons for r in strict.rejected} == {
        1: ["url 'file:///home/x/feed.json' is not an http(s) URL"]
    }
