"""``CrawlWindow`` (ADR-0013): one run, at most four market calendar days, and the gap helper."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from pi_core.enums import NotObservedReason
from pi_dataset import CrawlWindow, DatasetV3, committed_profile, dump_dataset, upgrade
from pi_dataset.compose import window_gap_days
from pi_dataset.examples import ae_pilot

DUBAI = "Asia/Dubai"


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def window(start: str, end: str, run: str = "7") -> CrawlWindow:
    return CrawlWindow(start=at(start), end=at(end), run_id=run)


def test_dubai_midnight_is_20_00_utc() -> None:
    """19:59Z on 10-08 is still the 8th in Dubai; 20:00Z is the 9th."""
    assert window("2026-10-08T00:00", "2026-10-08T19:59").days(DUBAI) == 1
    assert window("2026-10-08T00:00", "2026-10-08T20:00").days(DUBAI) == 2


def test_window_days_count_dubai_calendar_days_not_utc_ones() -> None:
    # 4 UTC days (03..06), but 02T20:00Z is Dubai 10-03 and 06T20:00Z is Dubai 10-07: 5 days.
    assert window("2026-10-03T00:00", "2026-10-06T20:00").days(DUBAI) == 5
    # 5 UTC days (02..06), but 02T20:00Z is already Dubai 10-03 and 06T19:59Z is Dubai 10-06: 4.
    assert window("2026-10-02T20:00", "2026-10-06T19:59").days(DUBAI) == 4


def test_a_window_ends_after_it_starts() -> None:
    with pytest.raises(ValidationError, match="is after end"):
        window("2026-10-02T00:00", "2026-10-01T00:00")
    assert window("2026-10-02T00:00", "2026-10-02T00:00").days(DUBAI) == 1


def test_window_gap_days_is_the_distance_between_the_dubai_end_dates() -> None:
    a = window("2026-10-08T00:00", "2026-10-08T19:59")
    b = window("2026-10-08T00:00", "2026-10-08T20:00")
    assert window_gap_days(a, b, DUBAI) == window_gap_days(b, a, DUBAI) == 1
    # Same Dubai day, 23h59m apart in time: 0 days.
    early = window("2026-10-07T20:00", "2026-10-07T20:00")
    assert window_gap_days(early, a, DUBAI) == 0
    seven = window("2026-10-01T00:00", "2026-10-01T10:00")
    assert window_gap_days(seven, a, DUBAI) == 7


def _doc_with(
    window_doc: dict[str, Any] | None, cutoff: str = "2026-10-06T20:00:00Z"
) -> dict[str, Any]:
    profile = committed_profile("beauty", 1)
    assert profile is not None
    d: dict[str, Any] = json.loads(dump_dataset(upgrade(ae_pilot(), profile)))
    d["meta"]["cutoff"] = cutoff
    d["meta"]["generatedAt"] = "2026-10-07T21:00:00Z"
    if window_doc is not None:
        for retailer in d["meta"]["retailers"]:
            retailer["window"] = dict(window_doc)
        for product in d["products"]:  # captured inside every window these tests write
            for offer in product["offers"].values():
                offer["evidence"]["capturedAt"] = "2026-10-06T19:00:00Z"
                if not offer.get("early"):  # a recon offer is never the window's run
                    offer["evidence"]["runId"] = window_doc["runId"]
    return d


def test_a_snapshot_spans_at_most_four_dubai_days() -> None:
    four = {"start": "2026-10-02T20:00:00Z", "end": "2026-10-06T19:59:00Z", "runId": "7"}
    DatasetV3.model_validate(_doc_with(four))
    five = four | {"end": "2026-10-06T20:00:00Z"}
    with pytest.raises(ValidationError, match="spans 5 days in Asia/Dubai, more than 4"):
        DatasetV3.model_validate(_doc_with(five))


def test_a_window_never_ends_after_the_cutoff() -> None:
    late = {"start": "2026-10-06T00:00:00Z", "end": "2026-10-06T20:00:01Z", "runId": "7"}
    with pytest.raises(ValidationError, match=r"end is after meta\.cutoff"):
        DatasetV3.model_validate(_doc_with(late))


def test_the_keys_are_optional_and_camel_case_on_the_wire() -> None:
    ds = DatasetV3.model_validate(_doc_with(None))
    assert ds.meta.retailers[0].window is None
    w = window("2026-10-05T00:00", "2026-10-06T00:00", run="8")
    assert w.model_dump(mode="json", by_alias=True) == {
        "start": "2026-10-05T00:00:00Z",
        "end": "2026-10-06T00:00:00Z",
        "runId": "8",
        "segments": [],
    }


# The window against its own offers (Coordinator rulings 01a11ca9-250f and 01a11cb7-030e;
# Reviewer (a)-(c), segments and marker => covered).

FOUR = {"start": "2026-10-02T20:00:00Z", "end": "2026-10-06T19:59:00Z", "runId": "7"}
# a cutoff on the window's last Dubai day (10-06); 20:00Z would already be 10-07 in Dubai
ON_THE_LAST_DAY = FOUR["end"]
REASONS = [r.value for r in NotObservedReason]
WHY = {"en": "Not captured in this run.", "ar": "لم تُلتقط في هذه الجولة."}


def _first(d: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
    """The windowed retailer's first offer, its product and its context id."""
    shop = d["meta"]["retailers"][0]["id"]
    contexts = {c["id"] for c in d["meta"]["contexts"] if c["retailer"] == shop}
    return next(
        (o, p, cid) for p in d["products"] for cid, o in p["offers"].items() if cid in contexts
    )


def _first_offer(d: dict[str, Any]) -> dict[str, Any]:
    return _first(d)[0]


def _cover(d: dict[str, Any], **entry: Any) -> None:
    """A ``notObserved`` entry over the windowed retailer's first offer, overridable."""
    _, product, cid = _first(d)
    d["notObserved"] = [
        {
            "retailer": d["meta"]["retailers"][0]["id"],
            "context": cid,
            "start": "2026-10-03",
            "end": "2026-10-06",
            "categories": [product["category"][0]],
            "why": WHY,
        }
        | entry
    ]


def _not_observed(
    d: dict[str, Any], reason: str | None, *, run: str | None = "6", cover: bool = True
) -> dict[str, Any]:
    """The first offer kept from an earlier capture: original ``capturedAt``, null series."""
    offer = _first_offer(d)
    n = len(offer["series"]["price"])
    offer["series"] = {"price": [None] * n, "regular": None, "availability": None}
    offer["evidence"] |= {"capturedAt": "2026-09-30T00:00:00Z", "runId": run}
    if reason is not None:
        offer["notObservedReason"] = reason
    if cover:
        _cover(d)
    return offer


def test_an_observed_offer_one_second_outside_its_window_fails() -> None:
    d = _doc_with(FOUR)
    _first_offer(d)["evidence"]["capturedAt"] = "2026-10-06T19:59:01Z"
    with pytest.raises(ValidationError, match="is outside its retailer's window"):
        DatasetV3.model_validate(d)
    _first_offer(d)["evidence"]["capturedAt"] = "2026-10-06T19:59:00Z"  # the end is inside
    DatasetV3.model_validate(d)


@pytest.mark.parametrize("reason", REASONS)
def test_a_marked_offer_with_no_value_may_keep_its_old_capture(reason: str) -> None:
    d = _doc_with(FOUR)
    _not_observed(d, reason)
    offers = DatasetV3.model_validate(d).products[0].offers
    assert NotObservedReason(reason) in {o.not_observed_reason for o in offers.values()}


@pytest.mark.parametrize("reason", REASONS)
def test_an_unmarked_offer_with_an_old_capture_fails(reason: str) -> None:
    d = _doc_with(FOUR)
    _not_observed(d, None)
    with pytest.raises(ValidationError, match="is outside its retailer's window"):
        DatasetV3.model_validate(d)


@pytest.mark.parametrize("reason", REASONS)
def test_a_marker_never_launders_a_value(reason: str) -> None:
    d = _doc_with(FOUR)
    price = next(p for p in _first_offer(d)["series"]["price"] if p is not None)
    _not_observed(d, reason)["series"]["price"][-1] = price
    with pytest.raises(ValidationError, match=f"marked {reason} but has an in-window value"):
        DatasetV3.model_validate(d)


@pytest.mark.parametrize("reason", REASONS)
def test_an_offer_of_the_windows_own_run_cannot_be_marked(reason: str) -> None:
    d = _doc_with(FOUR)
    _not_observed(d, reason, run="7")
    with pytest.raises(ValidationError, match=f"marked {reason} but captured by the window's run"):
        DatasetV3.model_validate(d)


@pytest.mark.parametrize("reason", REASONS)
def test_an_offer_of_a_segment_of_the_run_cannot_be_marked(reason: str) -> None:
    d = _doc_with(FOUR | {"segments": ["7-ar", "7-stock"]})
    _not_observed(d, reason, run="7-stock")
    with pytest.raises(ValidationError, match="but captured by the window's run 7-stock"):
        DatasetV3.model_validate(d)


def test_a_marked_offer_without_a_run_id_is_from_another_run() -> None:
    d = _doc_with(FOUR)
    _not_observed(d, "retained", run=None)
    DatasetV3.model_validate(d)


def test_the_reasons_are_the_ruled_closed_set() -> None:
    assert REASONS == [
        "retained",
        "blocked",
        "rate_limited",
        "capture_in_progress",
        "planned_not_captured",
    ]
    d = _doc_with(FOUR)
    _not_observed(d, "not_captured")
    with pytest.raises(ValidationError, match="notObservedReason"):
        DatasetV3.model_validate(d)


def test_segments_are_camel_case_and_never_repeat_a_run() -> None:
    w = CrawlWindow.model_validate(FOUR | {"segments": ["7-ar"]})
    assert w.run_ids == {"7", "7-ar"}
    assert w.model_dump(mode="json", by_alias=True)["segments"] == ["7-ar"]
    for repeated in (["7"], ["7-ar", "7-ar"]):
        with pytest.raises(ValidationError, match="repeat a run"):
            CrawlWindow.model_validate(FOUR | {"segments": repeated})


def test_a_segment_capture_is_held_to_the_span_like_the_run() -> None:
    d = _doc_with(FOUR | {"segments": ["7-stock"]})
    offer = _first_offer(d)
    offer["evidence"] |= {"runId": "7-stock", "capturedAt": "2026-10-06T20:00:00Z"}
    with pytest.raises(ValidationError, match="is outside its retailer's window"):
        DatasetV3.model_validate(d)


# Marker => covered (Reviewer 01a11cb6-e0d8, adopted 01a11cb7-030e).


def test_a_marked_offer_with_no_covering_entry_fails() -> None:
    d = _doc_with(FOUR)
    _not_observed(d, "blocked", cover=False)
    with pytest.raises(ValidationError, match="marked blocked but no notObserved entry covers it"):
        DatasetV3.model_validate(d)


def test_a_covering_entry_with_no_categories_or_context_covers_the_retailer() -> None:
    d = _doc_with(FOUR)
    _not_observed(d, "blocked")
    _cover(d, categories=None, context=None)
    DatasetV3.model_validate(d)


@pytest.mark.parametrize(
    ("entry", "why"),
    [
        ({"context": "other"}, "another context"),
        ({"categories": ["fragrance-x"]}, "another category"),
        ({"start": "2026-09-01", "end": "2026-10-02"}, "dates before the window's first"),
    ],
)
def test_an_entry_that_misses_the_offer_does_not_cover_it(entry: dict[str, Any], why: str) -> None:
    d = _doc_with(FOUR)
    _not_observed(d, "rate_limited")
    if entry.get("context") == "other":  # a real second context of the same retailer
        shop = d["meta"]["retailers"][0]["id"]
        base = next(c for c in d["meta"]["contexts"] if c["retailer"] == shop)
        d["meta"]["contexts"].append(base | {"id": f"{base['id']}_2"})
        entry = {"context": f"{base['id']}_2"}
    _cover(d, **entry)
    with pytest.raises(ValidationError, match="no notObserved entry covers it"):
        DatasetV3.model_validate(d)


def test_values_inside_a_not_observed_entry_stay_legal() -> None:
    """One-directional: an observed, unmarked offer under an entry (metrics fixture p16)."""
    d = _doc_with(FOUR)
    _cover(d)
    DatasetV3.model_validate(d)


# Recon offers (re-ruled 01a11cb7-030e): exempt from the span, never from rule (c).


def test_a_recon_offer_from_another_run_keeps_its_old_capture() -> None:
    d = _doc_with(FOUR)
    offer = _first_offer(d)
    offer["early"] = True
    offer["evidence"] |= {"capturedAt": "2026-09-30T00:00:00Z", "runId": "6"}
    DatasetV3.model_validate(d)


@pytest.mark.parametrize("run", ["7", "7-ar"])
def test_a_recon_offer_of_the_windows_run_fails(run: str) -> None:
    d = _doc_with(FOUR | {"segments": ["7-ar"]})
    offer = _first_offer(d)
    offer["early"] = True
    offer["evidence"]["runId"] = run
    with pytest.raises(ValidationError, match=f"a recon offer captured by the window's run {run}"):
        DatasetV3.model_validate(d)


def test_without_a_window_the_rule_does_not_apply() -> None:
    """An upgraded v2 body has no window: its old and unmarked captures still load."""
    d = _doc_with(None)
    _not_observed(d, None, cover=False)
    DatasetV3.model_validate(d)


def test_an_observed_offer_of_another_run_fails_even_inside_the_span() -> None:
    """Validation holds what the exporter promises (Coordinator 01a11cd8-1fd5): an observed
    offer of a windowed retailer is from the window's run or one of its segments."""
    d = _doc_with(FOUR)
    _first_offer(d)["evidence"]["runId"] = "6"
    with pytest.raises(ValidationError, match="runId 6 is not its retailer's window run 7"):
        DatasetV3.model_validate(d)
    d["meta"]["retailers"][0]["window"]["segments"] = ["6"]
    DatasetV3.model_validate(d)


def test_an_observed_offer_with_no_run_fails() -> None:
    """A null runId is not one of the window's runs (Coordinator 01a11ce2-fd3e)."""
    d = _doc_with(FOUR)
    _first_offer(d)["evidence"]["runId"] = None
    with pytest.raises(ValidationError, match="runId None is not its retailer's window run 7"):
        DatasetV3.model_validate(d)


def _withheld(d: dict[str, Any], start: str | None, end: str = "2026-10-06") -> str:
    """The second retailer withheld beside the windowed first (Coordinator 01a11cd9-48b1): no
    window, last seen ``since`` 10-01 (its offers' run 1 captures, 04:10 in Dubai) and, unless
    ``start`` is None, a whole-retailer ``notObserved`` entry ``start``..``end``."""
    other = d["meta"]["retailers"][1]
    other |= {"window": None, "since": "2026-10-01"}
    contexts = {c["id"]: c["retailer"] for c in d["meta"]["contexts"]}
    for p in d["products"]:
        for cid, o in p["offers"].items():
            if contexts[cid] == other["id"] and not o.get("early"):
                o["evidence"] |= {"capturedAt": "2026-10-01T00:10:00Z", "runId": "1"}
    d["notObserved"] = (
        []
        if start is None
        else [
            {
                "retailer": other["id"],
                "context": None,
                "start": start,
                "end": end,
                "categories": None,
                "why": WHY,
            }
        ]
    )
    return str(other["id"])


def test_a_retailer_without_a_window_keeps_its_old_values_beside_a_windowed_one() -> None:
    """The withheld shape (Coordinator 01a11cc6-57aa, 01a11cd9-48b1): one retailer windowed,
    another with no window and a whole-retailer ``notObserved`` entry from the day after its
    ``since`` to the cutoff's day. The rules hold the windowed retailer only: the other's
    values from before the window (e.g. Ulta's U1 captures) stay legal, unmarked."""
    d = _doc_with(FOUR, cutoff=ON_THE_LAST_DAY)
    other = _withheld(d, "2026-10-02")
    contexts = {c["id"]: c["retailer"] for c in d["meta"]["contexts"]}
    assert any(
        contexts[cid] == other and any(v is not None for v in o["series"]["price"])
        for p in d["products"]
        for cid, o in p["offers"].items()
    ), "the fixture needs a valued offer of the second retailer"
    ds = DatasetV3.model_validate(d)
    shops = {r.id: r for r in ds.meta.retailers}
    assert shops[d["meta"]["retailers"][0]["id"]].window is not None
    assert shops[other].window is None
    # the same old capture on the windowed retailer is refused
    _first_offer(d)["evidence"]["capturedAt"] = "2026-09-30T18:00:00Z"
    with pytest.raises(ValidationError, match="outside its retailer's window"):
        DatasetV3.model_validate(d)


@pytest.mark.parametrize(
    ("start", "end", "why"),
    [
        (None, "2026-10-06", "no entry"),
        ("2026-10-03", "2026-10-06", "a day's gap after since"),
        ("2026-10-02", "2026-10-05", "ends before the cutoff's day"),
    ],
)
def test_a_withheld_retailer_needs_an_entry_from_the_day_after_since_to_the_end(
    start: str | None, end: str, why: str
) -> None:
    d = _doc_with(FOUR, cutoff=ON_THE_LAST_DAY)
    _withheld(d, start, end)
    with pytest.raises(
        ValidationError,
        match=r"no whole-retailer notObserved entry covering 2026-10-02\.\.2026-10-06",
    ):
        DatasetV3.model_validate(d)


def test_a_withheld_retailer_entry_reaches_the_cutoffs_day_not_the_windows_last_day() -> None:
    """Coordinator 01a11cf3-5ffd: the window ends on Dubai 10-06, the cutoff 2026-10-07T19:00Z
    is Dubai 10-07, so the cutoff wins: an entry ending 10-06 is refused, 10-07 accepted."""
    d = _doc_with(FOUR, cutoff="2026-10-07T19:00:00Z")
    _withheld(d, "2026-10-02", "2026-10-06")
    with pytest.raises(
        ValidationError,
        match=r"no whole-retailer notObserved entry covering 2026-10-02\.\.2026-10-07",
    ):
        DatasetV3.model_validate(d)
    d["notObserved"][0]["end"] = "2026-10-07"
    DatasetV3.model_validate(d)


def test_a_withheld_retailer_entry_must_be_for_the_whole_retailer() -> None:
    d = _doc_with(FOUR, cutoff=ON_THE_LAST_DAY)
    _withheld(d, "2026-10-02")
    d["notObserved"][0]["categories"] = ["skincare"]
    with pytest.raises(ValidationError, match="no whole-retailer notObserved entry"):
        DatasetV3.model_validate(d)


def test_a_withheld_retailer_with_offers_states_since() -> None:
    d = _doc_with(FOUR, cutoff=ON_THE_LAST_DAY)
    _withheld(d, "2026-09-01")
    d["meta"]["retailers"][1]["since"] = None
    with pytest.raises(ValidationError, match=r"withheld \(no window\) with offers but no since"):
        DatasetV3.model_validate(d)
