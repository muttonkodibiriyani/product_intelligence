"""The request gate: documents stay on the storefront, pictures never leave, hosts are counted."""

from __future__ import annotations

import pytest

from browser_capture import policy

SHOP = frozenset({"www.shop.example"})


@pytest.mark.parametrize(
    ("url", "why"),
    [
        ("http://www.shop.example/p/1", "not https"),
        ("https://user@www.shop.example/p/1", "userinfo"),
        ("https://www.shop.example:8443/p/1", "explicit port 8443"),
        ("https://www.shop.example.evil.test/p/1", "not in the allowed set"),
        ("https://169.254.169.254/computeMetadata/v1/", "not in the allowed set"),
        ("https://shop.example/p/1", "not in the allowed set"),
        ("ftp://www.shop.example/p/1", "not https"),
        ("https:///p/1", "not in the allowed set"),
    ],
)
def test_host_refusal_names_the_reason(url: str, why: str) -> None:
    got = policy.host_refusal(url, SHOP)
    assert got is not None
    assert why in got


def test_host_refusal_accepts_the_storefront_regardless_of_case() -> None:
    assert policy.host_refusal("https://WWW.Shop.Example/p/1?x=1", SHOP) is None


def test_documents_off_the_storefront_are_refused_and_remembered() -> None:
    gate = policy.Gate(SHOP)
    assert gate.decide("https://www.shop.example/p/1", "document", True).allow
    off = gate.decide("http://10.0.0.1/robots.txt", "document", True)
    assert not off.allow
    assert off.reason.startswith("document: scheme")
    again = gate.decide("https://cdn.other.test/frame.html", "document", False)
    assert not again.allow
    assert gate.refused_document == ("http://10.0.0.1/robots.txt", "scheme 'http' is not https")
    assert gate.counts == {"documents": 1, "refused_document": 2}


@pytest.mark.parametrize(
    "kind",
    [*sorted(policy.NEVER_TYPES), "other", "prefetch", "signedexchange", "cspviolationreport"],
)
def test_pictures_media_beacons_and_unknown_types_never_leave(kind: str) -> None:
    gate = policy.Gate(SHOP)
    got = gate.decide("https://www.shop.example/a.bin", kind, False)
    assert not got.allow
    assert got.reason == f"never:{kind}"
    assert gate.counts == {f"refused_type_{kind}": 1}
    assert gate.hosts_seen == {}


def test_record_policy_lets_render_calls_through_and_counts_every_host() -> None:
    gate = policy.Gate(SHOP)
    assert gate.decide("https://www.shop.example/app.js", "script", False).allow
    assert gate.decide("https://cdn.vendor.test/lib.js", "script", False).allow
    assert gate.decide("https://api.vendor.test/graphql", "fetch", False).allow
    assert gate.decide("https://api.vendor.test/graphql", "xhr", False).allow
    assert gate.decide("https://cdn.vendor.test/a.css", "stylesheet", False).allow
    assert gate.hosts_seen == {
        "www.shop.example": 1,
        "cdn.vendor.test": 2,
        "api.vendor.test": 2,
    }
    assert gate.counts == {
        "render_script": 2,
        "render_fetch": 1,
        "render_xhr": 1,
        "render_stylesheet": 1,
        "third_party": 4,
    }


def test_render_calls_over_http_are_refused_even_under_record() -> None:
    gate = policy.Gate(SHOP)
    got = gate.decide("http://cdn.vendor.test/lib.js", "script", False)
    assert not got.allow
    assert got.reason == "http"
    assert gate.counts == {"refused_http": 1}
    assert gate.hosts_seen == {}


def test_enforce_policy_refuses_hosts_outside_the_list_and_still_counts_them() -> None:
    gate = policy.Gate(SHOP, policy.ENFORCE_HOSTS, frozenset({"cdn.vendor.test"}))
    assert gate.decide("https://cdn.vendor.test/lib.js", "script", False).allow
    assert gate.decide("https://www.shop.example/x.js", "script", False).allow
    got = gate.decide("https://tracker.ads.test/px.js", "script", False)
    assert not got.allow
    assert got.reason == "host:tracker.ads.test"
    assert gate.hosts_seen == {"cdn.vendor.test": 1, "www.shop.example": 1, "tracker.ads.test": 1}
    assert gate.counts == {"render_script": 2, "third_party": 1, "refused_third_party": 1}


def test_a_popup_window_is_refused_whatever_it_asks_for() -> None:
    gate = policy.Gate(frozenset({"www.shop.example"}))
    for url in ("https://www.shop.example/p/1", "https://evil.test/x"):
        assert not gate.decide(url, "document", True, scope=policy.POPUP).allow
        assert not gate.decide(url, "script", False, scope=policy.POPUP).allow
    assert gate.counts == {"refused_popup": 4}
    assert gate.refused_document is None  # a popup is not the page's document


def test_a_child_frame_document_obeys_the_host_rules_and_is_counted_apart() -> None:
    gate = policy.Gate(frozenset({"www.shop.example"}))
    assert gate.decide(
        "https://www.shop.example/widget", "document", True, scope=policy.FRAME
    ).allow
    assert not gate.decide("https://pay.other.test/f", "document", True, scope=policy.FRAME).allow
    assert gate.counts == {"frame_documents": 1, "refused_frame_document": 1}
    assert gate.refused_document == (
        "https://pay.other.test/f",
        "host 'pay.other.test' is not in the allowed set",
    )


def test_the_job_document_check_can_refuse_a_document_the_host_rules_allowed() -> None:
    def check(url: str) -> str | None:
        return "robots disallowed: /private/" if "/private/" in url else None

    gate = policy.Gate(frozenset({"www.shop.example"}), document_check=check)
    assert gate.decide("https://www.shop.example/p/1", "document", True).allow
    assert not gate.decide("https://www.shop.example/private/x", "document", True).allow
    assert gate.refused_document == (
        "https://www.shop.example/private/x",
        "robots disallowed: /private/",
    )
    assert gate.counts == {"documents": 1, "refused_document": 1}
    # the check is not consulted for a URL the host rules already refused
    seen: list[str] = []
    gate2 = policy.Gate(frozenset({"www.shop.example"}), document_check=seen.append)
    gate2.decide("https://evil.test/x", "document", True)
    assert seen == []


@pytest.mark.parametrize("sub", [policy.RECORD, policy.ENFORCE_HOSTS])
def test_writes_never_leave_the_storefront_under_either_policy(sub: str) -> None:
    gate = policy.Gate(
        frozenset({"www.shop.example"}),
        sub,
        frozenset({"api.vendor.test"}),
        schemes=policy.HTTPS_ONLY,
    )
    assert gate.decide("https://www.shop.example/graphql", "fetch", False, method="POST").allow
    assert not gate.decide("https://api.vendor.test/collect", "fetch", False, method="POST").allow
    assert not gate.decide("https://api.vendor.test/collect", "xhr", False, method="PUT").allow
    assert gate.decide("https://api.vendor.test/cfg", "fetch", False, method="GET").allow
    assert gate.counts["refused_third_party_write"] == 2
    assert gate.counts["render_fetch"] == 2


def test_schemes_are_https_only_unless_a_test_says_otherwise() -> None:
    assert policy.host_refusal("http://localhost:8080/p", frozenset({"localhost"})) is not None
    local = frozenset({"http"})
    assert (
        policy.host_refusal("http://localhost:8080/p", frozenset({"localhost"}), schemes=local)
        is None
    )
    assert policy.host_refusal("https://localhost/p", frozenset({"localhost"}), schemes=local)
    gate = policy.Gate(frozenset({"localhost"}), schemes=local)
    assert gate.decide("http://localhost:8080/p", "document", True).allow
    assert gate.decide("http://localhost:8080/s.js", "script", False).allow
    assert not gate.decide("https://localhost/s.js", "script", False).allow
