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
