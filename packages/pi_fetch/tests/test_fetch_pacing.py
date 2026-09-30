import random
from datetime import UTC, datetime, time
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fetch_helpers import FakeClock, fake_pacer
from pi_fetch.pacing import (
    MAX_DEFER_S,
    HostPacer,
    OffPeakWindow,
    RobotsTag,
    RobotsTagger,
    parse_retry_after,
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
    [("120", 120.0), (" 5 ", 5.0), (None, None), ("Wed, 21 Oct 2026 07:28:00 GMT", None)],
)
def test_parse_retry_after(value: str | None, expected: float | None) -> None:
    assert parse_retry_after(value) == expected


def test_off_peak_window_wrapping_midnight() -> None:
    night = OffPeakWindow(start=time(1, 0), end=time(6, 0))
    wrap = OffPeakWindow(start=time(23, 0), end=time(5, 0))
    at_2am_dubai = datetime(2026, 9, 30, 22, 0, tzinfo=UTC)
    at_noon_dubai = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)
    assert night.contains(at_2am_dubai)
    assert not night.contains(at_noon_dubai)
    assert wrap.contains(at_2am_dubai)
    assert not wrap.contains(at_noon_dubai)
    assert night.seconds_until_open(at_2am_dubai) == 0
    assert night.seconds_until_open(at_noon_dubai) == 13 * 3600
    early = OffPeakWindow(start=time(23, 0), end=time(23, 30))
    assert early.seconds_until_open(at_noon_dubai) == 11 * 3600


def test_off_peak_window_rejects_unknown_zone() -> None:
    with pytest.raises(ValueError, match="Mars"):
        OffPeakWindow(start=time(1), end=time(2), time_zone="Mars/Olympus")


def test_robots_tagger() -> None:
    tagger = RobotsTagger()
    tagger.add("Shop.example", "User-agent: *\nDisallow: /api/\n")
    assert tagger.tag("shop.example", "https://shop.example/api/v1/p") is RobotsTag.DISALLOWED
    assert tagger.tag("shop.example", "https://shop.example/p/1") is RobotsTag.ALLOWED
    assert tagger.tag("other.example", "https://other.example/") is RobotsTag.UNKNOWN
