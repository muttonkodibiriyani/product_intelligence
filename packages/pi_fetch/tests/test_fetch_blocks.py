"""Block detection against synthetic challenge-page fixtures (no recorded vendor pages)."""

import pytest

from pi_fetch.blocks import detect, detect_response
from pi_fetch.types import BlockKind, BlockVendor, PayloadKind
from test_fetch_types import result

HTML = PayloadKind.HTML
Headers = tuple[tuple[str, str], ...]

VENDOR_CASES: list[tuple[str, int, Headers, bytes, BlockVendor]] = [
    (
        "cloudflare managed challenge (header)",
        403,
        (("cf-mitigated", "challenge"), ("server", "cloudflare")),
        b"<html>...</html>",
        BlockVendor.CLOUDFLARE,
    ),
    (
        "cloudflare interstitial body",
        503,
        (("server", "cloudflare"),),
        b"<title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/h/b'>",
        BlockVendor.CLOUDFLARE,
    ),
    (
        "akamai access denied",
        403,
        (("server", "AkamaiGHost"),),
        b"<H1>Access Denied</H1> Reference #18.1 https://errors.edgesuite.net/18.1",
        BlockVendor.AKAMAI,
    ),
    (
        "akamai 200 bot-manager interstitial",
        200,
        (),
        b"<div id='sec-if-cpt-container'>verifying</div>",
        BlockVendor.AKAMAI,
    ),
    (
        "akamai cookie on 403",
        403,
        (("set-cookie", "_abck=xyz; path=/"),),
        b"no",
        BlockVendor.AKAMAI,
    ),
    (
        "perimeterx press and hold",
        403,
        (),
        b"<div id='px-captcha'></div><script>window._pxAppId='PX0'</script>",
        BlockVendor.PERIMETERX,
    ),
    (
        "datadome captcha page",
        403,
        (("x-datadome", "protected"),),
        b"<script src='https://ct.captcha-delivery.com/c.js'></script>",
        BlockVendor.DATADOME,
    ),
    (
        "datadome captcha redirect header",
        403,
        (("x-datadome", "protected"), ("x-dd-b", "https://geo.captcha-delivery.com/x")),
        b"",
        BlockVendor.DATADOME,
    ),
    ("datadome server on 403", 403, (("server", "DataDome"),), b"x", BlockVendor.DATADOME),
    ("plain 403", 403, (("server", "nginx"),), b"Forbidden", BlockVendor.GENERIC),
    (
        "cloudflare challenge on 429",
        429,
        (),
        b"<script>cf_chl_opt={}</script>",
        BlockVendor.CLOUDFLARE,
    ),
    ("plain 401", 401, (), b"auth", BlockVendor.GENERIC),
    ("empty 200 html", 200, (), b"  \n", BlockVendor.GENERIC),
]


@pytest.mark.parametrize(
    ("status", "headers", "body", "vendor"),
    [case[1:] for case in VENDOR_CASES],
    ids=[case[0] for case in VENDOR_CASES],
)
def test_vendor_detection(status: int, headers: Headers, body: bytes, vendor: BlockVendor) -> None:
    verdict = detect_response(status, headers, body, HTML)
    assert verdict is not None
    assert verdict.vendor is vendor
    assert verdict.http_status == status


@pytest.mark.parametrize(
    ("status", "headers", "body", "kind"),
    [
        (200, (("server", "cloudflare"), ("cf-ray", "1")), b"<html>product</html>", HTML),
        (200, (("server", "AkamaiGHost"), ("set-cookie", "_abck=1")), b"<html>p</html>", HTML),
        (404, (), b"not found", HTML),
        (500, (), b"oops", HTML),
        (503, (("server", "nginx"),), b"maintenance", HTML),
        (200, (), b"", PayloadKind.IMAGE),
        (304, (), b"", HTML),
    ],
    ids=["cdn-200", "akamai-200-cookie", "404", "500", "plain-503", "empty-image", "304"],
)
def test_not_a_block(status: int, headers: Headers, body: bytes, kind: PayloadKind) -> None:
    assert detect_response(status, headers, body, kind) is None


def test_reason_names_cookie_not_its_value() -> None:
    verdict = detect_response(403, (("set-cookie", "_abck=SECRETVALUE; path=/"),), b"x", HTML)
    assert verdict is not None
    assert "SECRETVALUE" not in verdict.reason
    assert "_abck" in verdict.reason


@pytest.mark.parametrize(
    ("status", "headers", "body", "kind", "vendor"),
    [
        (429, (), b"Too many requests", BlockKind.RATE_LIMITED, BlockVendor.GENERIC),
        (429, (("cf-ray", "8a-DXB"),), b"slow", BlockKind.RATE_LIMITED, BlockVendor.CLOUDFLARE),
        (429, (), b"<script>cf_chl_opt={}</script>", BlockKind.CHALLENGE, BlockVendor.CLOUDFLARE),
        (403, (), b"Forbidden", BlockKind.BLOCKED, BlockVendor.GENERIC),
    ],
    ids=["plain-429", "429-cloudflare-header", "429-challenge-marker", "403"],
)
def test_block_kind(
    status: int,
    headers: tuple[tuple[str, str], ...],
    body: bytes,
    kind: BlockKind,
    vendor: BlockVendor,
) -> None:
    verdict = detect_response(status, headers, body, HTML)
    assert verdict is not None
    assert (verdict.kind, verdict.vendor) == (kind, vendor)
    assert verdict.marks_source_blocked is (kind is not BlockKind.RATE_LIMITED)
    fetched = result(http_status=status, body=body, block=verdict)
    assert not fetched.ok
    assert fetched.rate_limited is (kind is BlockKind.RATE_LIMITED)


def test_detect_on_a_stored_result() -> None:
    blocked = result(http_status=403, body=b"denied")
    verdict = detect(blocked)
    assert verdict is not None
    assert verdict.vendor is BlockVendor.GENERIC
    assert detect(result()) is None
