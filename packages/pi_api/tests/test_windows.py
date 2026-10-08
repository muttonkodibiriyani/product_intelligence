"""The served set's window guard (ADR-0013; rulings 01a11c71-37ee, 01a11cad-17da, review
5461045335): no window is refused, the gap is counted in the market's time zone (8 days refused,
7 pass), and a set in more than one time zone is refused."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pi_api.app import app_from_env
from pi_api.windows import MAX_GAP_DAYS, check_windows, window_problems
from pi_dataset import DatasetV3, committed_profile, dump_dataset, upgrade
from pi_dataset.compose import compose
from pi_dataset.examples import ae_pilot
from pi_dataset.v3 import NotObservedV3

NORTH, SOUTH = "example_north_ae", "example_south_ae"
#: ulta_ae tonight (Coordinator 01a11cc0-86a1, 01a11cd9-48b1): the whole retailer, blocked from
#: the day after its last capture (``since`` 2026-10-01).
SINCE = "2026-10-01"
BLOCKED = {
    "retailer": SOUTH,
    "context": None,
    "categories": None,
    "start": "2026-10-02",
    "end": "2026-10-08",
    "why": {"en": "Blocked (p0-20261008-ulta-probe).", "ar": "محجوب."},
}
#: Follows #302's text when a windowless retailer has no whole-retailer entry (01a11d19-9686).
HINT = (
    "; it has no crawl window (ADR-0013): re-export it, or withhold it with a notObserved "
    "entry for the whole retailer"
)
FRESH = {"start": "2026-10-08T00:00:00Z", "end": "2026-10-08T10:00:00Z", "runId": "fresh"}


def windowed(
    end: str | None,
    *,
    cutoff: str = "2026-10-08T19:59:00Z",  # 10-08 in Dubai; 20:00Z is already 10-09
    zone: str = "Asia/Dubai",
    withheld: dict[str, Any] | None = None,
) -> DatasetV3:
    """The ae-pilot example as the exporter writes it: each retailer with its own keys and
    (unless ``end`` is None) a one-day window ending at ``end``; its AE market in ``zone``.
    ``withheld`` is a notObserved entry for ``SOUTH``, which then has no window."""
    profile = committed_profile("beauty", 1)
    assert profile is not None
    d: dict[str, Any] = json.loads(dump_dataset(upgrade(ae_pilot(), profile)))
    meta = d["meta"]
    meta["cutoff"], meta["generatedAt"] = cutoff, cutoff
    meta["markets"][0]["timeZone"] = zone
    for r in meta["retailers"]:
        r["fields"], r["capabilities"] = dict(meta["fields"]), dict(meta["capabilities"])
        if end is not None and not (withheld is not None and r["id"] == SOUTH):
            r["window"] = {"start": end, "end": end, "runId": f"run-{end}"}
            in_window(d, r["id"], end)
        if withheld is not None and r["id"] == SOUTH:
            r["since"] = SINCE
    if withheld is not None:
        d["notObserved"] = [{**BLOCKED, **withheld}]
    return DatasetV3.model_validate(d)


def disclosed(ds: DatasetV3, **entry: Any) -> DatasetV3:
    """``ds`` with ``SOUTH``'s whole-retailer entry changed by ``entry``, not re-validated: a
    body ``pi_dataset.v3`` would refuse, so the served-set guard is tested on its own."""
    [blocked] = [NotObservedV3.model_validate({**BLOCKED, **entry})]
    return ds.model_copy(update={"not_observed": (blocked,)})


def covering(name: str, first: str, cutoff: str) -> str:
    return (
        f"{name}: {SOUTH}: withheld (no window) with offers but no whole-retailer notObserved "
        f"entry covering {first}..{cutoff}"
    )


def in_window(d: dict[str, Any], retailer: str, end: str) -> None:
    """Each of ``retailer``'s offers captured at ``end`` by its window's run, as #302 requires
    of an observed offer (rule (c))."""
    for product in d["products"]:
        for offer in (o for c, o in product["offers"].items() if c == retailer and not o["early"]):
            offer["evidence"] |= {"capturedAt": end, "runId": f"run-{end}"}


def test_seven_dubai_days_pass_and_eight_are_refused_at_the_20z_boundary() -> None:
    assert MAX_GAP_DAYS == 7
    fresh = ("fresh", windowed(FRESH["end"]))
    # 2026-09-30T20:00Z is already 10-01 in Dubai: 7 days before 10-08.
    seven = ("seven", windowed("2026-09-30T20:00:00Z"))
    assert window_problems([fresh, seven]) == []
    # One minute earlier is 09-30 in Dubai: 8 days.
    eight = ("eight", windowed("2026-09-30T19:59:00Z"))
    [problem] = window_problems([fresh, eight])
    assert problem.startswith("window gap 8 days in Asia/Dubai, more than 7")
    assert "eight: example_" in problem
    assert "fresh: example_" in problem
    assert window_problems([eight, fresh]) == [problem]  # order-free


def test_the_market_time_zone_moves_the_boundary() -> None:
    # Riyadh (UTC+3) turns its day at 21:00Z, an hour after Dubai: 20:00Z on 09-30 is still
    # 09-30 there, so the set that is 7 Dubai days apart is 8 Riyadh days apart.
    def riyadh(end: str) -> DatasetV3:
        return windowed(end, zone="Asia/Riyadh")

    fresh = ("fresh", riyadh(FRESH["end"]))
    [problem] = window_problems([fresh, ("dubai-seven", riyadh("2026-09-30T20:00:00Z"))])
    assert problem.startswith("window gap 8 days in Asia/Riyadh, more than 7")
    assert window_problems([fresh, ("seven", riyadh("2026-09-30T21:00:00Z"))]) == []


def test_a_set_in_more_than_one_time_zone_is_refused() -> None:
    same_day = "2026-10-08T10:00:00Z"
    mixed = [("ae", windowed(same_day)), ("sa", windowed(same_day, zone="Asia/Riyadh"))]
    assert window_problems(mixed) == ["windows in more than one time zone: Asia/Dubai, Asia/Riyadh"]


def test_a_retailer_without_a_window_is_refused() -> None:
    problems = window_problems([("old", windowed(None)), ("fresh", windowed(FRESH["end"]))])
    assert problems == [
        f"old: {r}: withheld (no window) with offers but no whole-retailer notObserved entry "
        f"covering 2026-09-02..2026-10-08{HINT}"
        for r in (NORTH, SOUTH)
    ]
    assert window_problems([]) == []


def test_require_all_refuses_a_cold_start_over_the_gap(tmp_path: Path) -> None:
    a, b = "datasets/ae/a/v/1.json", "datasets/ae/b/v/2.json"
    for path, ds in ((a, windowed(FRESH["end"])), (b, windowed("2026-09-30T19:59:00Z"))):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(dump_dataset(ds))
    served = {
        "PI_API_FIREBASE_PROJECT": "p",
        "PI_API_LOCAL_DIR": str(tmp_path),
        "PI_API_ALLOW_TEST": "1",
        "PI_API_DATASETS": f"{a},{b}",
    }
    assert app_from_env(served) is not None  # without the flag the API still starts
    with pytest.raises(RuntimeError, match="PI_API_REQUIRE_ALL: crawl windows: window gap 8"):
        app_from_env({**served, "PI_API_REQUIRE_ALL": "1"})
    (tmp_path / b).write_bytes(dump_dataset(windowed("2026-09-30T20:00:00Z")))
    assert app_from_env({**served, "PI_API_REQUIRE_ALL": "1"}) is not None


def test_a_withheld_retailer_passes_and_the_others_keep_the_gap() -> None:
    """Coordinator 01a11cc0-86a1: a retailer disclosed as not observed for the whole retailer
    to the set's last window day, with no window, is withheld; the rest are still checked."""
    fresh = windowed(FRESH["end"], withheld={})
    check = check_windows([("beauty", fresh)])
    assert check.problems == []
    assert check.withheld == [
        f"beauty: {SOUTH} withheld, not observed until 2026-10-08: "
        "Blocked (p0-20261008-ulta-probe)."
    ]
    # The other retailers keep the 7-day rule: north 8 days stale in another body is refused.
    eight = ("old", windowed("2026-09-30T19:59:00Z"))
    [problem] = window_problems([("beauty", fresh), eight])
    assert problem.startswith("window gap 8 days in Asia/Dubai, more than 7")


def test_withholding_never_excuses_a_window_or_a_stale_disclosure() -> None:
    # A retailer that has a window is counted, disclosure or not: a stale window is refused.
    stale = windowed("2026-09-30T19:59:00Z")
    stale = stale.model_copy(update={"not_observed": windowed(None, withheld={}).not_observed})
    [problem] = window_problems([("fresh", windowed(FRESH["end"])), ("stale", stale)])
    assert problem.startswith("window gap 8 days")
    # Disclosed only until 10-07 while the cutoff is on 10-08: refused.
    short = disclosed(windowed(FRESH["end"], withheld={}), end="2026-10-07")
    assert window_problems([("b", short)]) == [covering("b", "2026-10-02", "2026-10-08")]
    # Part of the retailer (a category) is not the whole retailer: no window is refused.
    part = disclosed(windowed(FRESH["end"], withheld={}), categories=["skincare"])
    [problem] = window_problems([("b", part)])
    assert problem == covering("b", "2026-10-02", "2026-10-08") + HINT


def test_a_set_with_no_window_at_all_is_refused_whatever_it_discloses() -> None:
    """Review 5461198455: with no windowed retailer there is no last window day, so an old
    whole-retailer disclosure would pass for every retailer. Nothing fresh: refused."""
    old = {"start": "2026-09-01", "end": "2026-09-02"}
    entries = [{**BLOCKED, **old, "retailer": r} for r in (NORTH, SOUTH)]
    d = json.loads(dump_dataset(windowed(None))) | {"notObserved": entries}
    for r in d["meta"]["retailers"]:
        r["since"] = "2026-09-01"
    both = DatasetV3.model_validate(d)
    check = check_windows([("pre", both)])
    assert check.problems == [
        "no retailer in the served set has a crawl window (ADR-0013): a retailer can only be "
        "withheld beside a windowed one"
    ]
    assert check.withheld == []
    # The same disclosures beside one fresh window are judged against its day: too old.
    problems = window_problems([("pre", both), ("fresh", windowed(FRESH["end"]))])
    assert problems == [
        f"pre: {r}: withheld (no window) with offers but no whole-retailer notObserved entry "
        "covering "
        "2026-09-02..2026-10-08"
        for r in (NORTH, SOUTH)
    ]


def test_a_withheld_retailer_is_disclosed_from_the_day_after_its_last_capture() -> None:
    """Coordinator 01a11cd9-48b1: the entry starts no later than ``since`` + 1 day, so it is
    contiguous with the last capture; since 10-01 and an entry from 10-02 is tonight's shape."""
    assert window_problems([("b", windowed(FRESH["end"], withheld={}))]) == []
    assert window_problems([("b", windowed(FRESH["end"], withheld={"start": SINCE}))]) == []
    gap = disclosed(windowed(FRESH["end"], withheld={}), start="2026-10-03")
    assert window_problems([("b", gap)]) == [covering("b", "2026-10-02", "2026-10-08")]
    known = windowed(FRESH["end"], withheld={})
    retailers = [r.model_copy(update={"since": None}) for r in known.meta.retailers]
    unknown = known.model_copy(
        update={"meta": known.meta.model_copy(update={"retailers": retailers})}
    )
    assert window_problems([("b", unknown)]) == [
        f"b: {SOUTH}: withheld (no window) with offers but no since"
    ]


def test_a_withheld_entry_reaches_the_cutoffs_day_not_the_windows_last_day() -> None:
    """Coordinator 01a11cf3-5ffd, 01a11cf9-5d28 (#302 c08d0ec4's rule): the window ends on
    Dubai day 10-06 and the cutoff 2026-10-07T19:00Z is on 10-07; an entry to 10-06 is refused,
    to 10-07 passes."""
    cutoff = "2026-10-07T19:00:00Z"
    ok = windowed("2026-10-06T10:00:00Z", cutoff=cutoff, withheld={"end": "2026-10-07"})
    check = check_windows([("b", ok)])
    assert check.problems == []
    assert check.withheld == [
        f"b: {SOUTH} withheld, not observed until 2026-10-07: Blocked (p0-20261008-ulta-probe)."
    ]
    short = disclosed(ok, end="2026-10-06")
    assert window_problems([("b", short)]) == [covering("b", "2026-10-02", "2026-10-07")]


def test_a_withheld_entry_reaches_the_served_sets_latest_cutoff() -> None:
    """Review 01a11d05-231d: the guard judges the served set as ``compose`` does, against the
    latest of its files' cutoffs (ADR-0013 §8). The withheld body's own cutoff is on 10-06 and
    its entry ends 10-06, which passes alone; beside a body cut off on 10-07 it is refused, and
    an entry to 10-07 passes."""
    early = windowed(
        "2026-10-06T10:00:00Z", cutoff="2026-10-06T19:00:00Z", withheld={"end": "2026-10-06"}
    )
    late = ("late", windowed("2026-10-07T10:00:00Z", cutoff="2026-10-07T19:00:00Z"))
    assert window_problems([("x", early)]) == []
    assert window_problems([("x", early), late]) == [covering("x", "2026-10-02", "2026-10-07")]
    assert window_problems([late, ("x", early)]) == [covering("x", "2026-10-02", "2026-10-07")]
    reaches = disclosed(early, end="2026-10-07")
    check = check_windows([("x", reaches), late])
    assert check.problems == []
    assert check.withheld == [
        f"x: {SOUTH} withheld, not observed until 2026-10-07: Blocked (p0-20261008-ulta-probe)."
    ]


def test_a_windowless_retailer_without_offers_is_skipped_as_compose_skips_it() -> None:
    """Coordinator 01a11d06-293f, review 01a11d06-19db: parity with ``pi_dataset.v3``, which
    judges only a windowless retailer with offers. One with no offers and no entry, beside a
    windowed one, passes the guard, and the same set loads in compose."""
    d = json.loads(dump_dataset(windowed(FRESH["end"])))
    south = next(r for r in d["meta"]["retailers"] if r["id"] == SOUTH)
    del south["window"]
    contexts = {c["id"] for c in d["meta"]["contexts"] if c["retailer"] == SOUTH}
    for product in d["products"]:
        product["offers"] = {c: o for c, o in product["offers"].items() if c not in contexts}
        product["matches"] = [m for m in product["matches"] if not {m["a"], m["b"]} & contexts]
    d["products"] = [p for p in d["products"] if p["offers"]]
    empty = DatasetV3.model_validate(d)
    assert not any(c in contexts for p in empty.products for c in p.offers)
    check = check_windows([("b", empty)])
    assert check.problems == []
    assert check.withheld == []
    assert compose([empty]) is not None
    # The same retailer with an offer is judged: no window and no entry is refused.
    assert window_problems([("b", windowed(None))])  # control: offers, no window, no entry


def scoped(ds: DatasetV3, scope: str) -> DatasetV3:
    return ds.model_copy(update={"meta": ds.meta.model_copy(update={"scope": scope})})


def test_a_withheld_entry_reaches_its_own_scopes_cutoff_not_another_scopes() -> None:
    """Review 01a11d19-68b2, Coordinator 01a11d19-9686: the API composes one view per scope
    (``source._composed``), so a withheld retailer is judged against the latest cutoff of its
    own scope's files. Its entry ends on its scope's cutoff day, 10-06; another scope cut off
    on 10-07 does not refuse it, whether the guard reads the files or (as ``app_from_env``
    does) the files and the composed views. The gap is still counted over the whole set."""
    beauty = windowed(
        "2026-10-06T10:00:00Z", cutoff="2026-10-06T19:00:00Z", withheld={"end": "2026-10-06"}
    )
    fashion = scoped(windowed("2026-10-07T10:00:00Z", cutoff="2026-10-07T19:00:00Z"), "fashion")
    views = [(f"scope:{d.meta.scope}", compose([d]).dataset) for d in (beauty, fashion)]
    for served in ([("x", beauty), ("f", fashion)], [("x", beauty), ("f", fashion), *views]):
        check = check_windows(served)
        assert check.problems == []
        assert check.withheld[0] == (
            f"x: {SOUTH} withheld, not observed until 2026-10-06: Blocked (p0-20261008-ulta-probe)."
        )
    # The same entry beside a later body of its own scope is refused (the same-scope pair).
    late = ("late", windowed("2026-10-07T10:00:00Z", cutoff="2026-10-07T19:00:00Z"))
    assert window_problems([("x", beauty), ("f", fashion), late]) == [
        covering("x", "2026-10-02", "2026-10-07")
    ]
    # Across scopes the gap still counts: fashion 8 Dubai days after beauty's window is refused.
    stale = scoped(windowed("2026-10-14T10:00:00Z", cutoff="2026-10-14T19:00:00Z"), "fashion")
    [problem] = window_problems([("x", beauty), ("f", stale)])
    assert problem.startswith("window gap 8 days in Asia/Dubai, more than 7")
