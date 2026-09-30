"""Tests for the pure probe helpers, using the recon block samples as ground truth."""

import html
import re
from pathlib import Path

import pytest

from gulf_probe import analysis, plan

SAMPLES = Path(__file__).resolve().parents[3] / "docs" / "recon" / "samples"

PDP = """<html><head><title>Rouge Lipstick</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product",
"name":"Rouge","brand":{"@type":"Brand","name":"X"},"sku":"P1","gtin13":"123",
"image":["https://cdn/x.jpg"],"description":"d","aggregateRating":{"ratingValue":4},
"offers":[{"@type":"Offer","price":"99","priceCurrency":"AED",
"availability":"https://schema.org/InStock"},{"@type":"Offer","price":"109"}]}</script>
<script type="application/ld+json">{not json</script>
<script>window.__NEXT_DATA__ = {}; var algolia = {"apiKey":"abc123"};</script>
</head></html>"""


def test_akamai_sample_is_blocked() -> None:
    body = (SAMPLES / "sephora_akamai_403.html").read_text()
    verdict = analysis.detect_block(403, {"Server": "AkamaiGHost"}, body)
    assert verdict == analysis.BlockVerdict(analysis.BlockVendor.AKAMAI, "http 403")


def test_cloudflare_sample_is_blocked_even_with_200() -> None:
    body = (SAMPLES / "ulta_ae_cloudflare_block_head.html").read_text()
    verdict = analysis.detect_block(200, {"server": "cloudflare", "cf-ray": "1"}, body)
    assert verdict is not None
    assert verdict.vendor is analysis.BlockVendor.CLOUDFLARE
    assert verdict.reason.startswith("challenge marker")


@pytest.mark.parametrize(
    ("headers", "body", "vendor"),
    [
        ({"set-cookie": "_pxhd=1"}, "", analysis.BlockVendor.PERIMETERX),
        ({"x-datadome": "1"}, "", analysis.BlockVendor.DATADOME),
        ({}, "see errors.edgesuite.net", analysis.BlockVendor.AKAMAI),
        ({"server": "nginx"}, "", None),
    ],
)
def test_detect_vendor(
    headers: dict[str, str], body: str, vendor: analysis.BlockVendor | None
) -> None:
    assert analysis.detect_vendor(headers, body) is vendor


def test_generic_and_empty_blocks() -> None:
    assert analysis.detect_block(429, {}, "x") == analysis.BlockVerdict(
        analysis.BlockVendor.GENERIC, "http 429"
    )
    empty = analysis.detect_block(200, {}, "  ")
    assert empty is not None
    assert empty.reason == "empty 200 body"
    assert analysis.detect_block(200, {}, PDP) is None
    assert analysis.detect_block(200, {}, "", size=406_249) is None  # image: body not decoded
    assert analysis.detect_block(200, {}, "", size=0) is not None


def test_redaction() -> None:
    headers = {"Set-Cookie": "a=b", "Content-Type": "text/html", "Authorization": "x"}
    assert analysis.redact_headers(headers) == {"Content-Type": "text/html"}
    text = '{"apiKey":"abc123","searchKey":"k"} ?x-algolia-api-key=zz9&a=1 "passkey":"pp"'
    out = analysis.redact_text(text)
    for secret in ("abc123", "zz9", '"pp"'):
        assert secret not in out
    assert out.count("REDACTED") == 3


def test_product_fields() -> None:
    fields = analysis.product_fields(PDP)
    for key in ("jsonld_product", "name", "brand", "sku", "gtin", "image", "description"):
        assert fields[key], key
    assert fields["price"]
    assert fields["currency"]
    assert fields["availability"]
    assert fields["rating"]
    assert fields["variants"]
    assert fields["marker_next_data"]
    assert fields["marker_algolia"]
    assert not fields["marker_drupal_settings"]
    assert not analysis.product_fields("<html></html>")["jsonld_product"]


def test_json_fields() -> None:
    payload = {"data": [{"salePrice": 1, "inStock": True, "variants": [], "brand": "B"}]}
    fields = analysis.json_fields(payload)
    assert fields["price"]
    assert fields["stock"]
    assert fields["variants"]
    assert fields["brand"]
    assert not fields["rating"]


def test_sitemaps() -> None:
    xml = (SAMPLES / "sephora_sitemap_index_head.xml").read_text()
    locs = analysis.sitemap_locs(xml)
    assert locs[0].endswith("productSlugsCO-4.xml")
    urlset = (
        "<urlset><url><loc>https://a/1</loc><image:image>i</image:image>"
        '<xhtml:link rel="alternate"/></url><url><loc> https://a/2 </loc></url></urlset>'
    )
    assert analysis.sitemap_stats(urlset) == {
        "url_elements": 2,
        "locs": 2,
        "image_children": 1,
        "hreflang_links": 1,
    }


def test_trim_for_fixture() -> None:
    out = analysis.trim_for_fixture(PDP)
    assert out.startswith("<title>Rouge Lipstick</title>")
    assert "__NEXT_DATA__" not in out
    assert analysis.trim_for_fixture("<p>x</p>") == "<title></title>"
    assert len(analysis.trim_for_fixture(PDP, limit=10)) == 10


def test_plan() -> None:
    maps = plan.sephora_product_sitemaps()
    assert len(maps) == 80
    assert {t.locale for t in maps} == {"en-AE", "ar-AE"}
    assert maps[0].url == "https://www.sephora.me/sitemap/en-AE/catalog/productSlugsCO-0.xml"
    assert all(t.site == "sephora" for t in plan.sephora_fixed())
    assert all(t.url.startswith(plan.ULTA) for t in plan.ulta_fixed())
    ar = plan.browser_headers("ar-AE", "html")
    assert ar["Accept-Language"].startswith("ar-AE")
    assert "Cookie" not in ar
    assert plan.browser_headers("en-AE", "other")["Accept"] == "*/*"


def test_pick_and_json_api() -> None:
    locs = [f"https://a/{i}" for i in range(10)] + ["https://a/0"]
    assert plan.pick(locs, 3) == ["https://a/0", "https://a/3", "https://a/6"]
    assert plan.pick(locs, 20, contains="/1") == ["https://a/1"]
    assert plan.is_json_api("https://x/api/v1/p", "application/json; charset=utf-8")
    assert not plan.is_json_api("https://x/a.js", "application/json")
    assert not plan.is_json_api("https://x/a", "text/html")


def test_client_labels_roundtrip() -> None:
    for client in (plan.HTTP, plan.CHROMIUM_HEADLESS, *plan.STAGE2_CLIENTS):
        assert plan.parse_client(client.label) == client
    for bad in ("curl_cffi-headless-desktop", "firefox-headless-mobile", "webkit-stealth-desktop"):
        with pytest.raises(ValueError, match=bad):
            plan.parse_client(bad)


def test_parse_spec_and_search() -> None:
    raw = (
        '[{"site":"ulta","step":"home","url":"https://www.ulta.ae/en/","kind":"html",'
        '"locale":"en-AE","clients":["plain_http","webkit-headed-mobile"]}]'
    )
    rows = plan.parse_spec(raw)
    assert [c.label for _, c in rows] == ["plain_http", "webkit-headed-mobile"]
    assert rows[0][0].site == "ulta"
    assert {t.site for t in plan.search_targets()} == {"sephora", "ulta"}


def test_usable() -> None:
    assert plan.usable({"price": True}, [])
    assert plan.usable(None, [None, {"price": True}])
    assert not plan.usable({"price": False}, [None, {"price": False}])


def test_robots_rules_and_matching() -> None:
    txt = (
        "User-agent: Googlebot\nDisallow: /\n\n"
        "User-agent: *\nDisallow: /search\nDisallow: /*?sort=\nAllow: /search/help$\n"
        "Disallow: /*.json$\nDisallow:\n# comment\n"
    )
    rules = analysis.robots_rules(txt)
    assert (False, "/search") in rules
    assert analysis.robots_allowed(rules, "/en/buy-x")
    assert not analysis.robots_allowed(rules, "/search?q=a")
    assert analysis.robots_allowed(rules, "/search/help")
    assert not analysis.robots_allowed(rules, "/en/makeup?sort=price")
    assert not analysis.robots_allowed(rules, "/en/query-index.json")
    assert analysis.robots_allowed(rules, "/en/query-index.json?x=1")
    assert analysis.robots_rules(txt, "googlebot") == [(False, "/")]
    assert analysis.robots_rules("User-agent: a\nUser-agent: b\nDisallow: /x\n", "b") == [
        (False, "/x")
    ]
    assert analysis.robots_rules("Sitemap: /s.xml\nnonsense\n") == []


PROBE = SAMPLES / "probe"


@pytest.mark.parametrize(
    ("name", "status", "vendor"),
    [
        ("ulta_ae_cf_challenge_webkit_head.html", 403, analysis.BlockVendor.CLOUDFLARE),
        ("ulta_ae_cf_429_head.html", 429, analysis.BlockVendor.CLOUDFLARE),
        ("ulta_com_kw_cf_block_head.html", 403, analysis.BlockVendor.CLOUDFLARE),
        ("sephora_akamai_403_our_server.html", 403, analysis.BlockVendor.GENERIC),
    ],
)
def test_probe_block_fixtures(name: str, status: int, vendor: analysis.BlockVendor) -> None:
    body = (PROBE / name).read_text(encoding="utf-8")
    headers = {"server": "cloudflare"} if vendor is analysis.BlockVendor.CLOUDFLARE else {}
    verdict = analysis.detect_block(status, headers, body)
    assert verdict is not None
    assert verdict.vendor is vendor


def test_challenge_page_served_with_200_is_still_a_block() -> None:
    body = (PROBE / "ulta_ae_cf_429_head.html").read_text(encoding="utf-8")  # Arabic title
    verdict = analysis.detect_block(200, {}, body)
    assert verdict is not None
    assert "challenge-platform" in verdict.reason


def test_usable_probe_fixtures_are_not_blocks() -> None:
    for name in ("sephora_pdp_trimmed.html", "ulta_ae_pdp_trimmed.html"):
        body = (PROBE / name).read_text(encoding="utf-8")
        assert analysis.detect_block(200, {}, body) is None
        assert analysis.product_fields(body)["price"]


def test_probe_fixtures_carry_no_cookies_or_keys() -> None:
    needles = ("set-cookie", "cf_clearance", "__cf_bm", "_abck", "bm_sz", "x-algolia-api-key")
    for path in PROBE.iterdir():
        text = path.read_text(encoding="utf-8").lower()
        for needle in needles:
            assert needle not in text, (path.name, needle)
    # An Akamai "Reference #18.<hex>..." may encode a client IP in hex (PR #15 review).
    assert not re.search(r"reference\s*#\s*\d+\.[0-9a-f]{8}", html.unescape(text)), path.name


ULTA = "ulta"


@pytest.mark.parametrize(
    ("site", "path", "has_rules", "status", "expected"),
    [
        # Sephora is tag_only (ADR-0005): never gated.
        ("sephora", "/ae-en/api/v1/x", False, None, None),
        # robots.txt itself may always be requested.
        (ULTA, "/robots.txt", False, None, None),
        # Fail closed: no parsed rules and robots.txt not yet fetched / 403 / 429 / 5xx / error.
        (ULTA, "/en/search?keywords=lipstick", False, None, "robots_unavailable"),
        (ULTA, "/en/buy-x", False, 403, "robots_unavailable"),
        (ULTA, "/en/buy-x", False, 429, "robots_unavailable"),
        (ULTA, "/en/buy-x", False, 503, "robots_unavailable"),
        (ULTA, "/en/buy-x", False, 200, "robots_unavailable"),  # 200 challenge page, no rules
        # 404/410 = allow-all.
        (ULTA, "/en/search?keywords=lipstick", False, 404, None),
        (ULTA, "/en/buy-x", False, 410, None),
        # Parsed rules decide.
        (ULTA, "/en/search?keywords=lipstick", True, 200, "robots_disallowed"),
        (ULTA, "/en/buy-signature-lip-pencil", True, 200, None),
    ],
)
def test_robots_gate_fails_closed(
    site: str, path: str, has_rules: bool, status: int | None, expected: str | None
) -> None:
    robots = (PROBE / "ulta_ae_robots.txt").read_text(encoding="utf-8")
    rules = analysis.robots_rules(robots) if has_rules else None
    assert analysis.robots_gate(site, path, rules, status) == expected
