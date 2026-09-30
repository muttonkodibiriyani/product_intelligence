import random
from datetime import UTC, datetime, time
from itertools import pairwise
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fetch_helpers import FakeClock, fake_pacer
from pi_fetch.pacing import (
    MAX_DEFER_S,
    HostPacer,
    OffPeakWindow,
    RobotsRules,
    RobotsTag,
    RobotsTagger,
    parse_retry_after,
    product_token,
)


def test_first_request_does_not_wait() -> None:
    clock = FakeClock()
    assert fake_pacer(clock).wait("shop.example") == 0
    assert clock.slept == []


@given(
    hosts=st.lists(st.sampled_from(["a.example", "b.example", "A.EXAMPLE"]), max_size=30),
    seed=st.integers(0, 2**32 - 1),
    jitter=st.floats(0, 2),
)
def test_at_most_one_request_per_second_per_host(
    hosts: list[str], seed: int, jitter: float
) -> None:
    clock = FakeClock()
    pacer = HostPacer(clock=clock, sleep=clock.sleep, jitter_s=jitter, rng=random.Random(seed))  # noqa: S311
    starts: dict[str, list[float]] = {}
    for host in hosts:
        pacer.wait(host)
        starts.setdefault(host.lower(), []).append(clock.now)
    for times in starts.values():
        gaps = [b - a for a, b in pairwise(times)]
        assert all(g >= 1.0 for g in gaps)


def test_hosts_are_paced_independently() -> None:
    clock = FakeClock()
    pacer = fake_pacer(clock)
    pacer.wait("a.example")
    assert pacer.wait("b.example") == 0


def test_faster_than_one_per_second_is_refused() -> None:
    with pytest.raises(ValueError, match="1 req/s"):
        HostPacer(min_interval_s=0.5)
    with pytest.raises(ValueError, match="jitter"):
        HostPacer(jitter_s=-1)


def test_defer_honours_retry_after_capped() -> None:
    clock = FakeClock()
    pacer = HostPacer(clock=clock, sleep=clock.sleep, jitter_s=0)
    pacer.wait("a.example")
    pacer.defer("a.example", 30)
    assert pacer.wait("a.example") == 30
    pacer.defer("a.example", 10**9)
    assert pacer.wait("a.example") == MAX_DEFER_S


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("120", 120.0),
        (" 5 ", 5.0),
        (None, None),
        ("soon", None),
        ("-3", None),
        ("Thu, 01 Oct 2026 00:10:00 GMT", 600.0),
        ("Wed, 30 Sep 2026 23:00:00 GMT", 0.0),
    ],
)
def test_parse_retry_after(value: str | None, expected: float | None) -> None:
    now = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    assert parse_retry_after(value, now) == expected


def test_back_off_doubles_until_success_and_reports_the_cap() -> None:
    clock = FakeClock()
    pacer = HostPacer(clock=clock, sleep=clock.sleep, jitter_s=0)
    assert pacer.back_off("a.example", None) == (60.0, False)
    assert pacer.back_off("A.example", 30) == (120.0, False)
    assert pacer.back_off("a.example", 900) == (900.0, False)
    pacer.succeeded("a.example")
    assert pacer.back_off("a.example", None) == (60.0, False)
    assert pacer.back_off("b.example", 7200) == (MAX_DEFER_S, True)


def test_wait_uses_the_longer_of_pacer_and_source_interval() -> None:
    clock = FakeClock()
    pacer = HostPacer(clock=clock, sleep=clock.sleep, jitter_s=0)
    pacer.wait("a.example", 5.0)
    pacer.wait("a.example", 5.0)
    pacer.wait("a.example", 0.2)  # the slot was reserved 5 s out by the previous call
    pacer.wait("a.example", 0.2)  # below the 1 s floor, so the floor applies
    assert clock.slept == [5.0, 5.0, 1.0]


def test_off_peak_window_wrapping_midnight() -> None:
    night = OffPeakWindow(start=time(1, 0), end=time(6, 0), time_zone="Asia/Dubai")
    wrap = OffPeakWindow(start=time(23, 0), end=time(5, 0), time_zone="Asia/Dubai")
    at_2am_dubai = datetime(2026, 9, 30, 22, 0, tzinfo=UTC)
    at_noon_dubai = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)
    assert night.contains(at_2am_dubai)
    assert not night.contains(at_noon_dubai)
    assert wrap.contains(at_2am_dubai)
    assert not wrap.contains(at_noon_dubai)
    assert night.seconds_until_open(at_2am_dubai) == 0
    assert night.seconds_until_open(at_noon_dubai) == 13 * 3600
    early = OffPeakWindow(start=time(23, 0), end=time(23, 30), time_zone="Asia/Dubai")
    assert early.seconds_until_open(at_noon_dubai) == 11 * 3600


def test_off_peak_window_has_no_default_zone() -> None:
    with pytest.raises(ValueError, match="time_zone"):
        OffPeakWindow(start=time(1), end=time(2))  # type: ignore[call-arg]
    kuwait = OffPeakWindow(start=time(1), end=time(6), time_zone="Asia/Kuwait")
    assert kuwait.contains(datetime(2026, 9, 30, 23, 0, tzinfo=UTC))  # 02:00 in Kuwait


def test_off_peak_window_rejects_unknown_zone() -> None:
    with pytest.raises(ValueError, match="Mars"):
        OffPeakWindow(start=time(1), end=time(2), time_zone="Mars/Olympus")


def test_robots_tagger() -> None:
    tagger = RobotsTagger()
    tagger.add("Shop.example", "User-agent: *\nDisallow: /api/\n")
    assert tagger.tag("shop.example", "https://shop.example/api/v1/p") is RobotsTag.DISALLOWED
    assert tagger.tag("shop.example", "https://shop.example/p/1") is RobotsTag.ALLOWED
    assert tagger.tag("other.example", "https://other.example/") is RobotsTag.UNKNOWN
    assert tagger.known("SHOP.example")
    assert not tagger.known("other.example")
    tagger.mark_unavailable("other.example")
    assert tagger.known("other.example")
    assert tagger.tag("other.example", "https://other.example/") is RobotsTag.UNKNOWN


ULTA_ROBOTS = """
User-agent: *
Disallow: /*?
Disallow: */?*
Allow: /*.json?
Allow: /*media_*?
Allow: /*?selected*
Disallow: /checkout$

User-agent: OtherBot
Disallow: /
"""


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://ulta.ae/p/lipstick", True),
        ("https://ulta.ae/p/lipstick?sort=price", False),
        ("https://ulta.ae/search/?q=a", False),
        ("https://ulta.ae/p/lipstick.json?variant=2", True),
        ("https://ulta.ae/img/media_1234?w=300", True),
        ("https://ulta.ae/p/lipstick?selected=2", True),
        ("https://ulta.ae/checkout", False),
        ("https://ulta.ae/checkout/step", True),
        ("https://ulta.ae/robots.txt", True),
    ],
)
def test_robots_rfc9309_wildcards_and_longest_match(url: str, allowed: bool) -> None:
    rules = RobotsRules(ULTA_ROBOTS)
    assert rules.allows(url) is allowed


def test_robots_tie_goes_to_allow_and_agent_groups_merge() -> None:
    rules = RobotsRules("User-agent: *\nDisallow: /a\nAllow: /a\n")
    assert rules.allows("https://x.example/a")
    merged = "User-agent: pibot\nDisallow: /x\n\nUser-agent: pibot\nDisallow: /y\n"
    mine = RobotsRules(merged + "User-agent: *\nDisallow: /\n", "PIbot")
    assert not mine.allows("https://x.example/x")
    assert not mine.allows("https://x.example/y")
    assert mine.allows("https://x.example/z")
    assert RobotsRules("# nothing\nSitemap: https://x.example/s.xml\n").allows("https://x.example/")


SEPHORA_ROBOTS = (Path(__file__).parent / "fixtures" / "robots" / "sephora_me.txt").read_text()


@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("/ae/en/p/lipstick-P123", True),
        ("/on/demandware.store/Sites-SA/en/Home-GetFooter", True),  # longer Allow beats Disallow
        ("/on/demandware.store/Sites-SA/en/Cart-Show", False),
        ("/ae/en/makeup?scgid=C12", True),  # equal-length Allow and Disallow: Allow wins
        ("/ae/en/makeup?scgid=X12", False),
        ("/ae/en/search?q=rouge", False),
        ("/ae/en/makeup?sz=48", False),
        ("/checkout/cart", False),
        ("/ae/en/api/v1/products", False),
        ("/beautyboard/", True),
    ],
)
def test_robots_real_sephora_file(path: str, allowed: bool) -> None:
    assert RobotsRules(SEPHORA_ROBOTS).allows(f"https://www.sephora.me{path}") is allowed


# Provenance: docs/recon/samples/probe/ulta_ae_robots.txt (Crawl Engineer, 2026-09-30, WebKit
# plain-text view; content exact). No live fetch in tests.
ULTA_AE_ROBOTS = (Path(__file__).parent / "fixtures" / "robots" / "ulta_ae.txt").read_text()


@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("/en/search?keywords=lipstick", False),  # /*? (3) beats Allow: / (1)
        ("/en/p/some-lipstick-12345", True),
        ("/en/p/some-lipstick?selected=2", True),  # Allow /*?selected* is longest
        ("/en/api/product.json?id=1", True),  # Allow /*.json?
        ("/assets/media_1234?w=400", True),  # Allow /*media_*?
        ("/en/--promo", False),  # */--*
        ("/en/p/red--matte", True),  # */--* needs "/--"
        ("/en/cart/", False),
        ("/en/user/login", False),
        ("/en/fragments/nav", False),
        ("/en/footer", False),
        ("/en/system/404?referer=x", False),
        ("/graphql?query=%7Bproducts%7D", False),  # /*?
        ("/sitemap.xml", True),
        ("/robots.txt", True),
    ],
)
def test_robots_real_ulta_ae_file(path: str, allowed: bool) -> None:
    assert RobotsRules(ULTA_AE_ROBOTS).allows(f"https://www.ulta.ae{path}") is allowed


def test_robots_percent_encoding_is_normalised() -> None:
    rules = RobotsRules(
        "User-agent: *\nDisallow: /caf\u00e9\nDisallow: /%7euser\nDisallow: /a%2fb\n"
    )
    assert not rules.allows("https://x.example/caf%c3%a9/menu")
    assert not rules.allows("https://x.example/~user/home")
    assert not rules.allows("https://x.example/a%2Fb")
    assert rules.allows("https://x.example/a/b")  # an encoded slash is not a path separator


def test_robots_empty_disallow_allows_all() -> None:
    rules = RobotsRules("User-agent: *\nDisallow:\n")
    assert rules.allows("https://x.example/anything?at=all")


def test_robots_bom_does_not_drop_the_first_group() -> None:
    assert not RobotsRules("\ufeffUser-agent: *\nDisallow: /private\n").allows(
        "https://x.example/private/1"
    )


def test_product_token() -> None:
    assert product_token("Mozilla/5.0 (X11; Linux x86_64) Chrome/140") == "Mozilla"
    assert product_token("   ") == "*"
