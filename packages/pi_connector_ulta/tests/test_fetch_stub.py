from datetime import UTC, datetime

from pydantic import HttpUrl

from pi_connector_ulta._pi_fetch_stub import (
    BlockVendor,
    BlockVerdict,
    FetchMethod,
    FetchRequest,
    FetchResult,
    LadderRung,
    Locale,
    PayloadKind,
)


def test_ladder_rungs_exactly_mirror_pi_core() -> None:
    assert [(rung.name, rung.value) for rung in LadderRung] == [
        ("SITE_DATA", 0),
        ("PLAIN_HTTP", 1),
        ("BROWSER", 2),
        ("STEALTH_BROWSER", 3),
        ("EGRESS_VARIATION", 4),
        ("PAID_PROXY", 5),
    ]


def _result(*, status: int = 200, blocked: bool = False) -> FetchResult:
    request = FetchRequest(
        url=HttpUrl("https://www.ulta.ae/en/product/example/P1"),
        kind=PayloadKind.HTML,
        locale=Locale.EN,
    )
    block = (
        BlockVerdict(vendor=BlockVendor.CLOUDFLARE, reason="403", http_status=403)
        if blocked
        else None
    )
    return FetchResult(
        request=request,
        final_url=request.url,
        http_status=status,
        content_type="text/html",
        body=b"",
        headers={},
        ladder_rung_used=LadderRung.PLAIN_HTTP,
        fetch_method=FetchMethod.PLAIN_HTTP,
        egress="fixture",
        retrieved_at=datetime.now(UTC),
        elapsed_ms=1,
        from_cache=False,
        block=block,
        evidence_uri="fixture://synthetic",
    )


def test_fetch_result_ok_requires_2xx_without_block() -> None:
    assert _result().ok
    assert not _result(status=500).ok
    assert not _result(status=403, blocked=True).ok
