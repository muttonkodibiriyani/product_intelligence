from typing import Any

import pytest
from pydantic import HttpUrl, ValidationError

from fetch_helpers import NOW, WEBKIT
from pi_core import Device, FetchMethod, LadderRung, Locale
from pi_fetch.types import (
    BlockKind,
    BlockVendor,
    BlockVerdict,
    BrowserEngine,
    BrowserProfile,
    CapturedJson,
    FetchRequest,
    FetchResult,
    PayloadKind,
    redact_headers,
)

REQUEST = FetchRequest(
    url=HttpUrl("https://shop.example/p/1"), kind=PayloadKind.HTML, locale=Locale.EN
)


def result(**overrides: Any) -> FetchResult:
    fields: dict[str, Any] = {
        "request": REQUEST,
        "final_url": "https://shop.example/p/1",
        "http_status": 200,
        "content_type": "text/html",
        "body": b"<html></html>",
        "headers": {"content-type": "text/html"},
        "ladder_rung_used": LadderRung.PLAIN_HTTP,
        "fetch_method": FetchMethod.PLAIN_HTTP,
        "egress": "direct",
        "retrieved_at": NOW,
        "elapsed_ms": 3,
        "from_cache": False,
        "block": None,
        "evidence_uri": "file:///e/ab/abc",
    }
    fields.update(overrides)
    return FetchResult.model_validate(fields)


@pytest.mark.parametrize(
    "name", ["Cookie", "authorization", "Proxy-Authorization", "User-Agent", "HOST"]
)
def test_request_refuses_auth_cookie_and_identity_headers(name: str) -> None:
    with pytest.raises(ValidationError, match="not allowed"):
        FetchRequest(
            url=HttpUrl("https://shop.example/"),
            kind=PayloadKind.JSON,
            locale=Locale.AR,
            headers={name: "x"},
        )


def test_request_allows_ordinary_headers() -> None:
    req = FetchRequest(
        url=HttpUrl("https://shop.example/"),
        kind=PayloadKind.JSON,
        locale=Locale.AR,
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert req.headers == {"X-Requested-With": "XMLHttpRequest"}


def test_ok_only_for_2xx_without_block() -> None:
    assert result().ok
    assert not result(http_status=404).ok
    assert not result(http_status=500).ok
    assert not result(http_status=304).ok
    verdict = BlockVerdict(
        kind=BlockKind.CHALLENGE, vendor=BlockVendor.AKAMAI, reason="challenge", http_status=200
    )
    assert not result(block=verdict).ok


def test_result_refuses_rung_3() -> None:
    with pytest.raises(ValidationError, match="forbidden"):
        result(ladder_rung_used=LadderRung.STEALTH_BROWSER)


def test_result_refuses_method_of_another_rung() -> None:
    with pytest.raises(ValidationError, match="belongs to rung"):
        result(fetch_method=FetchMethod.PLAYWRIGHT)


def test_result_refuses_unredacted_cookie_headers() -> None:
    with pytest.raises(ValidationError, match="redacted"):
        result(headers={"Set-Cookie": "_abck=secret"})


def test_captured_json_only_from_browser_rungs() -> None:
    capture = CapturedJson(url=HttpUrl("https://shop.example/api"), status=200, body=b"{}")
    with pytest.raises(ValidationError, match="browser"):
        result(captured_json=(capture,))
    ok = result(
        captured_json=(capture,),
        ladder_rung_used=LadderRung.BROWSER,
        fetch_method=FetchMethod.PLAYWRIGHT,
        browser=WEBKIT,
    )
    assert ok.captured_json == (capture,)
    assert ok.browser == WEBKIT


CAPTURE = CapturedJson(url=HttpUrl("https://shop.example/api"), status=200, body=b"{}")


@pytest.mark.parametrize(
    ("rung", "method"),
    [
        (LadderRung.BROWSER, FetchMethod.PLAYWRIGHT),
        (LadderRung.EGRESS_VARIATION, FetchMethod.EGRESS_VARIATION),
        (LadderRung.PAID_PROXY, FetchMethod.RESIDENTIAL_PROXY),  # the proxied pinned browser
    ],
)
def test_captured_json_accepted_on_every_browser_rung(
    rung: LadderRung, method: FetchMethod
) -> None:
    ok = result(
        captured_json=(CAPTURE,), ladder_rung_used=rung, fetch_method=method, browser=WEBKIT
    )
    assert ok.captured_json == (CAPTURE,)


@pytest.mark.parametrize(
    ("rung", "method"),
    [
        (LadderRung.SITE_DATA, FetchMethod.SITEMAP),
        (LadderRung.PLAIN_HTTP, FetchMethod.PLAIN_HTTP),
        (LadderRung.PAID_PROXY, FetchMethod.RESIDENTIAL_PROXY),  # no browser profile: not a browser
    ],
)
def test_captured_json_rejected_without_a_browser(rung: LadderRung, method: FetchMethod) -> None:
    with pytest.raises(ValidationError, match="captured_json only comes from a browser fetch"):
        result(captured_json=(CAPTURE,), ladder_rung_used=rung, fetch_method=method)


def test_browser_profile_is_recorded_exactly_on_browser_fetches() -> None:
    with pytest.raises(ValidationError, match="must record its browser profile"):
        result(ladder_rung_used=LadderRung.BROWSER, fetch_method=FetchMethod.PLAYWRIGHT)
    with pytest.raises(ValidationError, match="only a browser fetch"):
        result(browser=WEBKIT)
    egress_browser = result(
        ladder_rung_used=LadderRung.EGRESS_VARIATION,
        fetch_method=FetchMethod.EGRESS_VARIATION,
        browser=BrowserProfile(engine=BrowserEngine.FIREFOX, headless=False),
    )
    assert egress_browser.browser is not None
    assert egress_browser.model_dump(mode="json")["browser"] == {
        "engine": "firefox",
        "headless": False,
        "device": "desktop",
        "viewport_width": 1366,
        "viewport_height": 768,
    }


def test_browser_profile_is_desktop_only_for_now() -> None:
    with pytest.raises(ValidationError, match="not supported yet"):
        BrowserProfile(engine=BrowserEngine.CHROMIUM, device=Device.MOBILE)


def test_redact_headers_drops_cookies_and_joins_repeats() -> None:
    pairs = [
        ("Set-Cookie", "a=1"),
        ("set-cookie", "b=2"),
        ("Cookie", "c=3"),
        ("Vary", "Accept"),
        ("vary", "Accept-Language"),
    ]
    assert redact_headers(pairs) == {"vary": "Accept, Accept-Language"}
