"""S4 exports (design §6): the view's own rows, a manifest line, the cap and the audit entry."""

from __future__ import annotations

import asyncio
import csv
import gc
import io
import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from starlette.requests import ClientDisconnect
from starlette.responses import StreamingResponse
from starlette.types import Message

from api_fixture import Client, bearer, make_client, served_dataset, write
from metrics_fixture import A, B
from pi_api import export

API = "/api/v1"
NO_STORE = "private, no-store"
PAIR = f"retailers={A},{B}"
NUMBER = re.compile(r"^[+-]?\d+(\.\d+)?$")  # a signed number is data, not a formula

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


def get(
    client: Client,
    path: str,
    status: int = 200,
    params: dict[str, Any] | None = None,
    **overrides: Any,
) -> Any:
    response = client.get(f"{API}/{path}", params=params, headers=bearer(**overrides))
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == NO_STORE
    return response


def with_format(path: str, fmt: str) -> str:
    return f"{path}{'&' if '?' in path else '?'}format={fmt}"


def jsonl(text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    first, *rest = (json.loads(line) for line in text.splitlines())
    return first["manifest"], rest


def read_csv(text: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    assert text.startswith('\ufeff"# ')
    first, header, *table = csv.reader(io.StringIO(text[1:]))
    assert len(first) == 1, "the manifest must be a single cell"
    return json.loads(first[0][2:]), [dict(zip(header, row, strict=True)) for row in table]


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


#: The Reviewer's crafted query on #64: the old unquoted manifest line split it into cells.
CRAFTED = 'x,=HYPERLINK("https://example.invalid","x"),-2+3'


@pytest.mark.parametrize("params", [{"q": CRAFTED}, {"q": CRAFTED, "brand": ["=1+1", "@x"]}])
def test_a_formula_in_a_filter_never_becomes_a_csv_cell(
    client: Client, params: dict[str, Any]
) -> None:
    """Reviewer MUST on #64: filter values stay inside the one manifest cell."""
    text = get(client, "export/products", params=params).text
    head, _ = read_csv(text)  # asserts line 1 is exactly one cell
    assert head["meta"]["filters"]["q"] == CRAFTED
    lines = list(csv.reader(io.StringIO(text[1:])))
    assert lines[0][0].startswith("# ")
    for line in lines:
        assert not [
            cell
            for cell in line
            if cell.startswith(("=", "+", "-", "@", "\t", "\r")) and not NUMBER.match(cell)
        ]


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
        f"export/compare?{PAIR}&limit=5",
        "export/promotions?limit=5",
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
    (entry,) = audits(caplog)
    assert (entry["outcome"], entry["rows"], entry["view"]) == ("too_large", 16, "products")
    assert jsonl(get(client, "export/coverage?format=jsonl").text)[0]["rows"] == 4  # at the cap


def test_each_export_writes_one_audit_entry_without_row_content(
    client: Client, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="pi_api.audit")
    get(client, f"export/compare?{PAIR}&format=jsonl", sub="analyst-7", role="viewer")
    (entry,) = audits(caplog)
    assert entry.pop("generation")
    assert entry == {
        "outcome": "ok",
        "severity": "NOTICE",
        "message": "pi_api.export",
        "event": "pi_api.export",
        "uid": "analyst-7",
        "role": "viewer",
        "view": "compare",
        "format": "jsonl",
        "filters": {"retailers": f"{A},{B}"},
        "rows": 15,
        "apiVersion": "1.8.0",
    }
    text = caplog.text
    assert "Product p01" not in text
    assert "90.00" not in text


def audits(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "pi_api.audit"]


def test_exports_beyond_the_free_slots_get_429_and_are_audited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(export, "MAX_CONCURRENT_EXPORTS", 0)
    write(tmp_path, served_dataset())
    busy = make_client(tmp_path)[0]
    caplog.set_level(logging.INFO, logger="pi_api.audit")
    response = get(busy, "export/coverage", 429)
    assert response.json()["error"]["code"] == "rate_limited"
    assert response.headers["retry-after"] == str(export.BUSY_RETRY)
    assert [e["outcome"] for e in audits(caplog)] == ["busy"]


def test_a_finished_export_frees_its_slot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(export, "MAX_CONCURRENT_EXPORTS", 1)
    write(tmp_path, served_dataset())
    one = make_client(tmp_path)[0]
    for _ in range(3):
        get(one, "export/coverage")


def test_slots_are_non_blocking_and_freed_once_when_a_stream_ends() -> None:
    slots = export.ExportSlots(1)
    assert slots.acquire()
    assert not slots.acquire()
    stream = slots.hold(iter([b"a", b"b"]))
    assert next(stream) == b"a"
    stream.close()  # the client went away mid-download
    stream.close()  # releasing again is a no-op, never a second slot
    assert not stream.held
    assert slots.acquire()
    assert not slots.acquire()
    done = slots.hold(iter([b"a"]))
    assert list(done) == [b"a"]
    assert slots.acquire()
    failing = slots.hold(_Boom())
    with pytest.raises(RuntimeError):
        next(failing)
    assert slots.acquire()
    assert not export.ExportSlots(0).acquire()


class _Boom(Iterator[bytes]):
    def __next__(self) -> bytes:
        raise RuntimeError("encoder failed")


def test_a_disconnect_before_the_response_starts_frees_the_slot() -> None:
    """Reviewer MUST on #64: Starlette sends the headers before it first iterates the body."""
    slots = export.ExportSlots(1)
    assert slots.acquire()
    response = StreamingResponse(slots.hold(iter([b"a"])))

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_: Message) -> None:
        raise OSError("client went away")

    scope = {"type": "http", "asgi": {"spec_version": "2.4"}, "method": "GET", "headers": []}
    with pytest.raises(ClientDisconnect):
        asyncio.run(response(scope, receive, send))
    del response
    gc.collect()
    assert slots.acquire()


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


def test_flatten_dots_objects_and_keeps_lists_as_json() -> None:
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
        "tags": '["a","b"]',
        "nested.x.y": "1",
        "objs": '[{"a":1}]',
    }


def test_columns_drop_a_null_object_column_when_its_fields_exist() -> None:
    rows = [{"id": "1", "gap": ""}, {"id": "2", "gap.amount.minor": "5", "gap.pct": "1"}]
    assert export.columns_of(rows) == ["id", "gap.amount.minor", "gap.pct"]
    assert export.columns_of([{"id": "1", "gap": ""}]) == ["id", "gap"]


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


def test_coverage_contexts_is_the_last_csv_column_whatever_row_shows_it_first() -> None:
    """``contexts`` (ADR-0008 step 4) never moves a column a positional reader relied on."""
    rows = [
        {"id": "a", "note": "", "contexts": "[]"},
        {"id": "b", "note.en": "x", "contexts": "[]"},
    ]
    assert export.columns_of(rows) == ["id", "contexts", "note.en"]
    assert export.columns_of(rows, export.TRAILING[export.ExportView.COVERAGE]) == [
        "id", "note.en", "contexts",
    ]  # fmt: skip


def test_the_coverage_csv_header_keeps_the_v2_columns_then_contexts(client: Client) -> None:
    lines = get(client, "export/coverage").text.lstrip("\ufeff").splitlines()
    header = next(csv.reader([lines[1]]))
    assert header == [
        "id", "name", "status", "since", "productCount", "matchedCount", "freshness", "note.en",
        "contexts",
    ]  # fmt: skip


def test_a_trailing_entry_covers_its_nested_columns_in_trailing_order() -> None:
    rows = [
        {"id": "a", "sizeSystem": "", "sizeLabel": "", "gap": ""},
        {"id": "b", "gap.pct": "1", "gap.sizeLabels": ""},
        {"id": "c", "gap.pct": "2", "gap.sizeLabels": "[]", "note": "", "note.en": "x"},
    ]
    assert export.columns_of(rows, ("gap.sizeLabels", "note", "sizeLabel")) == [
        "id", "sizeSystem", "gap.pct", "gap.sizeLabels", "note.en", "sizeLabel",
    ]  # fmt: skip


def test_the_products_csv_header_keeps_the_v1_1_columns_then_the_1_2_ones(
    client: Client,
) -> None:
    lines = get(client, "export/products?retailer=shop_a&retailer=shop_b").text
    header = next(csv.reader([lines.lstrip("﻿").splitlines()[1]]))
    assert header[-3:] == ["gap.sizeLabels", "sizeLabel", "sizeSystem"]
    assert header[:7] == ["id", "brand", "name", "category", "size.value", "size.unit", "image"]
