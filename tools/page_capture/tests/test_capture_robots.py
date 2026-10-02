"""robots.txt matcher: RFC 9309 semantics and fail-closed classification."""

from __future__ import annotations

import pytest

from page_capture import robots

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0.0.0 Safari/537.36"
TXT = """
# comment
User-agent: *
Disallow: /private/
Disallow: /temp*
Allow: /private/public$
Disallow: /*?sort=
Crawl-delay: 2.5

User-agent: Googlebot
Disallow: /
"""


def test_parse_selects_wildcard_group_when_no_product_token_matches() -> None:
    rules, delay = robots.parse(TXT, UA)
    assert [r.pattern for r in rules] == ["/private/", "/temp*", "/private/public$", "/*?sort="]
    assert delay == pytest.approx(2.5)


def test_parse_prefers_most_specific_user_agent_group() -> None:
    txt = (
        "User-agent: *\nDisallow: /a\n\nUser-agent: chrome\nDisallow: /b\n\n"
        "User-agent: chrome/140\nDisallow: /c\n"
    )
    rules, _ = robots.parse(txt, UA)
    assert [r.pattern for r in rules] == ["/c"]


def test_parse_merges_equally_specific_groups_and_ignores_bad_delay() -> None:
    txt = (
        "User-agent: *\nDisallow: /a\nCrawl-delay: soon\n\n"
        "User-agent: *\nDisallow: /b\nCrawl-delay: 4\n"
    )
    rules, delay = robots.parse(txt, UA)
    assert [r.pattern for r in rules] == ["/a", "/b"]
    assert delay == pytest.approx(4.0)


def test_empty_disallow_is_no_rule() -> None:
    rules, delay = robots.parse("User-agent: *\nDisallow:\n", UA)
    assert rules == ()
    assert delay is None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://x.example/", robots.ALLOWED),
        ("https://x.example/private/a", robots.DISALLOWED),
        ("https://x.example/private/public", robots.ALLOWED),  # allow wins the longer match
        ("https://x.example/private/publicity", robots.DISALLOWED),  # $ anchors
        ("https://x.example/tempfile", robots.DISALLOWED),  # wildcard
        ("https://x.example/shop?sort=asc", robots.DISALLOWED),  # query is matched
        ("https://x.example/shop?page=2", robots.ALLOWED),
        ("https://x.example/%70rivate/x", robots.DISALLOWED),  # percent-decoding
    ],
)
def test_verdict(url: str, expected: str) -> None:
    rules, delay = robots.parse(TXT, UA)
    assert robots.Robots(robots.OK, rules, delay).verdict(url) == expected


def test_allow_wins_a_specificity_tie() -> None:
    rules, _ = robots.parse("User-agent: *\nDisallow: /p\nAllow: /p\n", UA)
    assert robots.Robots(robots.OK, rules).verdict("https://x.example/page") == robots.ALLOWED


def test_from_response_classification() -> None:
    assert robots.from_response(404, "", "", UA).state == robots.ALLOW_ALL
    assert robots.from_response(410, "", "", UA).state == robots.ALLOW_ALL
    assert robots.from_response(None, "", "", UA).state == robots.UNAVAILABLE
    assert robots.from_response(503, "text/plain", "", UA).state == robots.UNAVAILABLE
    assert robots.from_response(200, "text/html", "User-agent: *", UA).state == robots.UNAVAILABLE
    html = "\n<!DOCTYPE html><html><body>blocked</body></html>"
    assert robots.from_response(200, "text/plain", html, UA).state == robots.UNAVAILABLE
    ok = robots.from_response(200, "text/plain", TXT, UA)
    assert ok.state == robots.OK
    assert len(ok.rules) == 4


def test_unavailable_and_allow_all_verdicts() -> None:
    assert robots.Robots(robots.UNAVAILABLE).verdict("https://x.example/") == robots.UNAVAILABLE
    assert robots.Robots(robots.ALLOW_ALL).verdict("https://x.example/private/") == robots.ALLOWED
