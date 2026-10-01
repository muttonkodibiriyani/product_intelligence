"""S4 exports (design §6): the view's own rows, a manifest line, the cap and the audit entry."""

from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from api_fixture import Client, bearer, make_client, served_dataset, write
from metrics_fixture import A, B
from pi_api import export

API = "/api/v1"
NO_STORE = "private, no-store"
PAIR = f"retailers={A},{B}"

#: Export path -> (the view's own endpoint, where its rows sit in ``data``).
VIEWS: dict[str, tuple[str, str | None]] = {
    "products?sort=name": ("products?sort=name&limit=100", "items"),
    f"compare?{PAIR}": (f"compare?{PAIR}", "rows"),
    f"index?{PAIR}": (f"index?{PAIR}", "points"),
    "promotions": ("promotions", "items"),
    f"assortment-gaps?missingAt={B}&presentAt={A}": (
        f"assortment-gaps?missingAt={B}&presentAt={A}",
        "items",
    ),
    "coverage": ("coverage", "retailers"),
}


@pytest.fixture
def client(tmp_path: Path) -> Client:
    write(tmp_path, served_dataset())
    return make_client(tmp_path)[0]


def get(client: Client, path: str, status: int = 200, **overrides: Any) -> Any:
    response = client.get(f"{API}/{path}", headers=bearer(**overrides))
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == NO_STORE
    return response


def with_format(path: str, fmt: str) -> str:
    return f"{path}{'&' if '?' in path else '?'}format={fmt}"


def jsonl(text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    first, *rest = (json.loads(line) for line in text.splitlines())
    return first["manifest"], rest


def read_csv(text: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    assert text.startswith("﻿# ")
    head, _, table = text[1:].partition("\r\n")
    return json.loads(head[2:]), list(csv.DictReader(io.StringIO(table)))


@pytest.mark.parametrize("path", list(VIEWS))
def test_exports_are_bearer_only_and_no_store(client: Client, path: str) -> None:
    response = client.get(f"{API}/export/{path}")
    assert response.status_code == 401
    assert response.headers["cache-control"] == NO_STORE
    assert get(client, f"export/{path}", 403, role=None).json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize("path", list(VIEWS))
def test_jsonl_rows_are_exactly_the_endpoint_rows(client: Client, path: str) -> None:
    endpoint, key = VIEWS[path]
    envelope = get(client, endpoint).json()
    response = get(client, f"export/{with_format(path, 'jsonl')}")
    assert response.headers["content-type"] == "application/x-ndjson"
    head, rows = jsonl(response.text)
    assert rows == envelope["data"][key]
    assert head["rows"] == len(rows)
    assert head["status"] == envelope["status"]
    assert head["reason"] == envelope["reason"]
    assert head["cohort"] == envelope["cohort"]
    assert head["caveats"] == envelope["caveats"]
    meta = {k: v for k, v in envelope["meta"].items() if k not in {"endpoint", "filters"}}
    assert {k: head["meta"][k] for k in meta} == meta


@pytest.mark.parametrize("path", list(VIEWS))
def test_csv_has_a_manifest_line_a_header_and_one_line_per_row(client: Client, path: str) -> None:
    endpoint, key = VIEWS[path]
    rows = get(client, endpoint).json()["data"][key]
    response = get(client, f"export/{path}")
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    view = path.split("?", maxsplit=1)[0]
    disposition = response.headers["content-disposition"]
    assert disposition.startswith(f'attachment; filename="pi-{view}-')
    assert disposition.endswith('.csv"')
    head, table = read_csv(response.text)
    assert head["schemaId"] == "pi-api.export/v1"
    assert (head["view"], head["format"], head["rows"]) == (view, "csv", len(rows))
    assert len(table) == len(rows)
    assert [r.get("id", r.get("date")) for r in table] == [
        str(r.get("id", r.get("date"))) for r in rows
    ]


def test_manifest_filters_exclude_the_format_and_record_the_query(client: Client) -> None:
    head, _ = jsonl(get(client, f"export/compare?{PAIR}&brand=Fixture+Beauty&format=jsonl").text)
    assert head["meta"]["endpoint"] == "export_compare"
    assert head["meta"]["filters"] == {"retailers": f"{A},{B}", "brand": ["Fixture Beauty"]}


def test_csv_compare_flattens_money_and_keeps_signed_numbers(client: Client) -> None:
    _, table = read_csv(get(client, f"export/compare?{PAIR}").text)
    counted = [r for r in table if r["counted"] == "true"]
    uncounted = [r for r in table if r["counted"] == "false"]
    assert counted
    assert uncounted
    assert "gap" not in table[0]
    assert all(r["gap.amount.currency"] == "AED" for r in counted)
    assert all(r["gap.pct"] == "" and r["excludedReason"] for r in uncounted)
    assert any(r["gap.pct"].startswith("-") for r in counted)
    assert not any(r["gap.pct"].startswith("'") for r in counted)


def test_products_export_keeps_the_gap_sort_order(client: Client) -> None:
    query = f"retailer={A}&retailer={B}&sort=gap_asc"
    _, rows = jsonl(get(client, f"export/products?{query}&format=jsonl").text)
    page = get(client, f"products?{query}&limit=100").json()["data"]["items"]
    assert [r["id"] for r in rows] == [r["id"] for r in page]
    assert rows[0]["gap"] is not None


@pytest.mark.parametrize(
    "path",
    [
        "export/products?format=xlsx",
        "export/products?limit=5",
        "export/products?cursor=abc",
        "export/products?sort=gap",
        "export/compare",
        f"export/compare?retailers={A},{A}",
        f"export/index?{PAIR}&from=2027-01-01",
        "export/assortment-gaps",
        "export/coverage?unknown=1",
        "export/matches",
    ],
)
def test_bad_export_queries_are_refused(client: Client, path: str) -> None:
    status = 404 if path.endswith("matches") else 422
    assert get(client, path, status).json()["error"]["code"] in {
        "invalid_request",
        "invalid_query",
        "not_found",
    }


def test_over_the_cap_is_refused_and_not_cut_short(
    client: Client, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(export, "MAX_EXPORT_ROWS", 4)
    caplog.set_level(logging.INFO, logger="pi_api.audit")
    error = get(client, "export/products", 422).json()["error"]
    assert error["code"] == "export_too_large"
    assert "16 rows is over the export cap of 4" in error["message"]
    assert not [r for r in caplog.records if r.name == "pi_api.audit"]
    assert jsonl(get(client, "export/coverage?format=jsonl").text)[0]["rows"] == 4  # at the cap


def test_each_export_writes_one_audit_entry_without_row_content(
    client: Client, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="pi_api.audit")
    get(client, f"export/compare?{PAIR}&format=jsonl", sub="analyst-7", role="viewer")
    entries = [json.loads(r.getMessage()) for r in caplog.records if r.name == "pi_api.audit"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.pop("generation")
    assert entry == {
        "severity": "NOTICE",
        "message": "pi_api.export",
        "event": "pi_api.export",
        "uid": "analyst-7",
        "role": "viewer",
        "view": "compare",
        "format": "jsonl",
        "filters": {"retailers": f"{A},{B}"},
        "rows": 15,
        "apiVersion": "1.0.0",
    }
    text = caplog.text
    assert "Product p01" not in text
    assert "90.00" not in text


def test_configure_audit_writes_bare_json_lines() -> None:
    stream = io.StringIO()
    saved = (export.audit_log.handlers, export.audit_log.propagate, export.audit_log.level)
    try:
        export.configure_audit(stream)
        export.audit_log.info('{"event":"x"}')
    finally:
        export.audit_log.handlers, export.audit_log.propagate = saved[0], saved[1]
        export.audit_log.setLevel(saved[2])
    assert stream.getvalue() == '{"event":"x"}\n'


# ---------------------------------------------------------------- encoding units


def test_flatten_dots_objects_and_joins_scalar_lists() -> None:
    value = {
        "id": "p1",
        "ok": True,
        "none": None,
        "empty": {},
        "tags": ["a", "b"],
        "nested": {"x": {"y": 1}},
        "objs": [{"a": 1}],
    }
    assert export.flatten(value) == {
        "id": "p1",
        "ok": "true",
        "none": "",
        "empty": "",
        "tags": "a|b",
        "nested.x.y": "1",
        "objs": '[{"a":1}]',
    }


def test_columns_drop_a_null_object_column_when_its_fields_exist() -> None:
    rows = [{"id": "1", "gap": ""}, {"id": "2", "gap.amount.minor": "5", "gap.pct": "1"}]
    assert export.columns(rows) == ["id", "gap.amount.minor", "gap.pct"]
    assert export.columns([{"id": "1", "gap": ""}]) == ["id", "gap"]


@pytest.mark.parametrize(
    ("cell", "safe"),
    [
        ("=HYPERLINK(1)", "'=HYPERLINK(1)"),
        ("+cmd", "'+cmd"),
        ("-1+2", "'-1+2"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tx", "'\tx"),
        ("-12.5", "-12.5"),
        ("+3", "+3"),
        ("Brand = Good", "Brand = Good"),
        ("", ""),
    ],
)
def test_safe_cell_neutralises_formulas_only(cell: str, safe: str) -> None:
    assert export.safe_cell(cell) == safe
