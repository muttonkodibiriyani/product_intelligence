from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import HttpUrl

from pi_connector_ulta import ParseError, UltaConnector
from pi_connector_ulta._pi_fetch_stub import (
    BlockVendor,
    BlockVerdict,
    CollectionContext,
    Connector,
    FetchMethod,
    FetchRequest,
    FetchResult,
    LadderRung,
    Locale,
    PayloadKind,
)
from pi_core import Market, SourceContext

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 30, tzinfo=UTC)
CONTEXT = CollectionContext(
    source_context=SourceContext(
        id=1,
        source_id=2,
        country=Market.UAE,
        locale=Locale.EN,
        time_zone=Market.UAE.time_zone,
        valid_from=NOW - timedelta(days=1),
    ),
    crawl_run_id=3,
    connector_version="ulta_ae@0.1.0",
    ladder_rung_used=LadderRung.PLAIN_HTTP,
    fetch_method=FetchMethod.PLAIN_HTTP,
)


def _fetch_result(
    *,
    body: bytes,
    kind: PayloadKind,
    block: BlockVerdict | None = None,
    status: int = 200,
) -> FetchResult:
    request = FetchRequest(
        url=HttpUrl("https://www.ulta.ae/en/product/example/P1"),
        kind=kind,
        locale=Locale.EN,
    )
    return FetchResult(
        request=request,
        final_url=request.url,
        http_status=403 if block else status,
        content_type="application/json" if kind is PayloadKind.JSON else "text/html",
        body=body,
        headers={},
        ladder_rung_used=LadderRung.PLAIN_HTTP,
        fetch_method=FetchMethod.PLAIN_HTTP,
        egress="fixture",
        retrieved_at=NOW,
        elapsed_ms=1,
        from_cache=False,
        block=block,
        evidence_uri="fixture://synthetic",
    )


def test_connector_matches_temporary_protocol_and_plans_without_io() -> None:
    connector = UltaConnector()
    assert isinstance(connector, Connector)
    items = tuple(connector.discover(CONTEXT))
    assert [item.locale for item in items] == [Locale.EN, Locale.AR]
    requests = connector.requests_for(items[0], CONTEXT)
    assert len(requests) == 1
    assert requests[0].url == items[0].url


@pytest.mark.parametrize(
    ("fixture", "kind", "offer_count"),
    [
        ("product_SYNTHETIC.json", PayloadKind.JSON, 2),
        ("product_page_SYNTHETIC.html", PayloadKind.HTML, 1),
    ],
)
def test_connector_parses_to_temporary_output(
    fixture: str, kind: PayloadKind, offer_count: int
) -> None:
    body = (FIXTURES / fixture).read_bytes()
    output = UltaConnector().parse(_fetch_result(body=body, kind=kind), CONTEXT)
    assert len(output.listings) == offer_count
    assert len(output.offers) == offer_count


def test_connector_never_parses_blocked_result() -> None:
    block = BlockVerdict(vendor=BlockVendor.CLOUDFLARE, reason="403", http_status=403)
    result = _fetch_result(body=b"", kind=PayloadKind.HTML, block=block)
    with pytest.raises(ParseError, match="must never be parsed"):
        UltaConnector().parse(result, CONTEXT)


@pytest.mark.parametrize("status", [300, 302, 399, 404, 410, 500, 503, 599])
def test_connector_emits_nothing_for_unsuccessful_fetch(status: int) -> None:
    body = (FIXTURES / "product_SYNTHETIC.json").read_bytes()
    result = _fetch_result(body=body, kind=PayloadKind.JSON, status=status)
    with pytest.raises(ParseError, match=rf"status {status}: not observed; no records emitted"):
        UltaConnector().parse(result, CONTEXT)


def test_connector_rejects_non_utf8_and_unsupported_payload() -> None:
    with pytest.raises(ParseError, match="not UTF-8"):
        UltaConnector().parse(_fetch_result(body=b"\xff", kind=PayloadKind.HTML), CONTEXT)
    with pytest.raises(ParseError, match="unsupported"):
        UltaConnector().parse(_fetch_result(body=b"ok", kind=PayloadKind.XML), CONTEXT)
