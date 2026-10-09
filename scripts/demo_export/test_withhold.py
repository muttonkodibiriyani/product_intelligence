"""``--withhold`` (F1): a retailer exported WITHHELD beside a windowed one, the body pi_api's window
guard serves and the publisher's retention gate keeps (ADR-0013 §8; Coordinator 01a11e48-9543)."""

# ruff: noqa: S101

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pytest
from publish_dataset import retention_problems

from pi_api.windows import check_windows
from pi_dataset import DatasetV3, dump_dataset, load_any
from scripts.demo_export.export import UltaContext, check_args, parser, withheld_of
from scripts.demo_export.test_export import row
from scripts.demo_export.test_v2 import NOTE
from scripts.demo_export.test_window import BLOCKED, SEPHORA, ULTA, at, offers, seen
from scripts.demo_export.v2 import Withheld, build_dataset_v2, crawl_windows, to_v3, with_since

UNBLOCKED = UltaContext(blocked_since=at("2026-09-30T20:55"), blocked=False)
WHY = {"en": "Ulta was last captured on 1 Oct.", "ar": "آخر التقاط لمتجر ألتا كان في 1 أكتوبر."}
#: Ulta's run 5 (Dubai 10-01) beside Sephora's run 7 (Dubai 10-09): 8 days apart, one over
#: ``pi_api.windows.MAX_GAP_DAYS``.
BEAUTY = [
    seen(row(variant=101, availability="in_stock"), at("2026-10-09T08:00"), run=7),
    seen(row(source=ULTA, family=20, variant=200, regular=None), at("2026-10-01T00:24"), run=5),
]
RUNS = {SEPHORA: (7,), ULTA: (5,)}
HELD = Withheld(frozenset({"u"}), WHY)


def beauty(
    withheld: Withheld | None = HELD,
    *,
    ulta: UltaContext = UNBLOCKED,
) -> DatasetV3:
    """``main`` for the beauty body: windows, v2, v3 (withheld slots get no window), then the
    publisher's strict load."""
    windows = crawl_windows(BEAUTY, RUNS)
    v2 = build_dataset_v2(
        BEAUTY,
        [],
        generated_at=max(w.end for w in windows.values()) + timedelta(hours=1),
        ulta=ulta,
        ulta_note=NOTE,
        windows=windows,
        withheld=withheld,
    )
    slots = frozenset() if withheld is None else withheld.slots
    v3 = load_any(dump_dataset(to_v3(v2, BEAUTY, [], windows, slots)))
    assert isinstance(v3, DatasetV3)
    return v3


def doc(ds: DatasetV3) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(dump_dataset(ds))
    return loaded


def test_a_withheld_ulta_beside_a_windowed_sephora_is_served_with_its_values() -> None:
    ds = beauty()
    shops = {r.id: r for r in ds.meta.retailers}
    assert shops[SEPHORA].window is not None
    assert (shops[ULTA].window, shops[ULTA].since) == (None, date(2026, 10, 1))
    entries = [n for n in ds.not_observed if n.retailer == ULTA]
    assert [(n.start, n.end, n.context, n.categories) for n in entries] == [
        (date(2026, 10, 2), date(2026, 10, 9), None, None)
    ]
    assert entries[0].why == WHY
    (ulta,) = offers(ds, ULTA).values()
    assert ulta.series.price[0] is not None  # the run's value, never blanked
    check = check_windows([("beauty", ds)])
    print("problems", check.problems, "withheld", check.withheld)
    assert check.problems == []
    assert len(check.withheld) == 1
    assert check.withheld[0].startswith("beauty: ulta_ae withheld, not observed until 2026-10-09")


def test_the_same_body_without_the_withhold_is_refused_by_the_gap() -> None:
    check = check_windows([("beauty", beauty(None))])
    print("problems", check.problems)
    assert len(check.problems) == 1
    assert "window gap 8 days in Asia/Dubai, more than 7" in check.problems[0]
    assert check.withheld == []


def test_a_withheld_retailer_without_since_is_refused() -> None:
    ds = beauty()
    retailers = [r.model_copy(update={"since": None}) for r in ds.meta.retailers]
    bare = ds.model_copy(update={"meta": ds.meta.model_copy(update={"retailers": retailers})})
    check = check_windows([("beauty", bare)])
    print("problems", check.problems)
    assert len(check.problems) == 1
    assert "ulta_ae: withheld (no window) with offers but no since" in check.problems[0]


def test_withhold_until_extends_the_entry_and_never_ends_before_the_cutoff() -> None:
    later = beauty(Withheld(frozenset({"u"}), WHY, until=date(2026, 10, 11)))
    assert [n.end for n in later.not_observed if n.retailer == ULTA] == [date(2026, 10, 11)]
    assert check_windows([("beauty", later)]).problems == []
    with pytest.raises(ValueError, match="withheld until 2026-10-08: before the cutoff day"):
        beauty(Withheld(frozenset({"u"}), WHY, until=date(2026, 10, 8)))


def test_withholding_keeps_every_live_ulta_offer_for_the_publisher() -> None:
    live, new = doc(beauty(None)), doc(beauty())
    problems = retention_problems(live, new)
    assert problems == []
    lost = doc(beauty())
    lost["products"] = [p for p in lost["products"] if ULTA not in json.dumps(p["offers"])]
    assert len(retention_problems(live, lost)) == 2  # control: the gate still fires


@pytest.mark.parametrize(
    ("withheld", "ulta", "message"),
    [
        (HELD, BLOCKED, "blocked"),
        (Withheld(frozenset({"o"}), WHY), UNBLOCKED, r"withheld \['o'\]: not a listed retailer"),
    ],
)
def test_a_blocked_or_unlisted_retailer_is_never_withheld(
    withheld: Withheld, ulta: UltaContext, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        beauty(withheld, ulta=ulta)


BASE = [
    "--database-url",
    "x",
    "--output",
    "o.json",
    "--output-v3",
    "o3.json",
    "--sources",
    f"{SEPHORA},{ULTA}",
    "--ulta-unblocked",
    "--run",
    f"{SEPHORA}=7",
    "--run",
    f"{ULTA}=5",
]
WHY_ARGS = ["--withhold-why", WHY["en"], "--withhold-why-ar", WHY["ar"]]


def test_withhold_flags_become_withheld_slots() -> None:
    args = parser().parse_args(
        [*BASE, "--withhold", ULTA, *WHY_ARGS, "--withhold-until", "2026-10-11"]
    )
    check_args(args)
    assert withheld_of(args) == Withheld(frozenset({"u"}), WHY, until=date(2026, 10, 11))
    plain = parser().parse_args(BASE)
    check_args(plain)
    assert withheld_of(plain) is None
    given = [*BASE, "--withhold", ULTA, "--withhold-why", FALLBACK["en"]]
    filled = parser().parse_args([*given, "--withhold-why-ar", FALLBACK["ar"]])
    check_args(filled)  # <since> is the one placeholder the exporter writes in
    assert withheld_of(filled) == Withheld(frozenset({"u"}), FALLBACK)


#: The fallback strings of 01a11e51-93d9, as given: ``<since>`` is written in by the exporter.
FALLBACK = {
    "en": "Ulta prices and stock shown are from the last complete read on <since>; "
    "Ulta has not been refreshed since.",
    "ar": "أسعار ومخزون Ulta المعروضة من آخر قراءة كاملة بتاريخ <since>؛ "
    "لم يتم تحديث Ulta منذ ذلك الحين.",
}


def test_since_is_written_into_the_reason_from_the_rows_own_since() -> None:
    ds = beauty(Withheld(frozenset({"u"}), FALLBACK))
    shops = {r.id: r for r in ds.meta.retailers}
    (entry,) = [n for n in ds.not_observed if n.retailer == ULTA]
    print("since", shops[ULTA].since, "why", entry.why)
    assert shops[ULTA].since == date(2026, 10, 1)
    assert entry.why == {
        "en": "Ulta prices and stock shown are from the last complete read on 1 October 2026; "
        "Ulta has not been refreshed since.",
        "ar": "أسعار ومخزون Ulta المعروضة من آخر قراءة كاملة بتاريخ 1 أكتوبر 2026؛ "
        "لم يتم تحديث Ulta منذ ذلك الحين.",
    }
    assert "<" not in json.dumps(doc(ds), ensure_ascii=False).replace("<since>", "")


@pytest.mark.parametrize(
    ("day", "en", "ar"),
    [
        (date(2026, 1, 31), "31 January 2026", "31 يناير 2026"),
        (date(2026, 12, 9), "9 December 2026", "9 ديسمبر 2026"),
    ],
)
def test_since_is_written_in_each_language(day: date, en: str, ar: str) -> None:
    assert with_since({"en": "on <since>.", "ar": "بتاريخ <since>"}, day) == {
        "en": f"on {en}.",
        "ar": f"بتاريخ {ar}",
    }


def test_a_reason_with_another_placeholder_is_refused() -> None:
    with pytest.raises(ValueError, match="unfilled placeholder"):
        with_since({"en": "on <since> (<run>)", "ar": "بتاريخ <since>"}, date(2026, 10, 1))


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        ([*BASE, *WHY_ARGS], "need --withhold"),
        ([*BASE, "--withhold-until", "2026-10-11"], "need --withhold"),
        ([*BASE, "--withhold", ULTA, "--withhold", ULTA, *WHY_ARGS], "names a source twice"),
        ([*BASE, "--withhold", "ounass_ae", *WHY_ARGS], "not one of --sources"),
        ([*BASE, "--withhold", ULTA, "--withhold", SEPHORA, *WHY_ARGS], "every source is"),
        ([*BASE[:-4], "--withhold", ULTA, *WHY_ARGS], "needs --run"),
        ([*BASE[:4], *BASE[6:], "--withhold", ULTA, *WHY_ARGS], "needs --output-v2 or"),
        ([*BASE, "--withhold", ULTA, "--withhold-why", WHY["en"]], "both non-empty"),
        ([*BASE, "--withhold", ULTA, *WHY_ARGS[:3], " "], "both non-empty"),
        ([*BASE, "--withhold", ULTA, *WHY_ARGS[:3], "منذ <date>"], "other than <since>"),
        ([*BASE, "--withhold", ULTA, "--withhold-why", "on <date>", *WHY_ARGS[2:]], "other than"),
        ([*BASE, "--withhold", ULTA, "--withhold-why", "<since> > b", *WHY_ARGS[2:]], "other"),
    ],
)
def test_withhold_flags_are_refused_unless_complete(argv: list[str], message: str) -> None:
    with pytest.raises(SystemExit, match=message):
        check_args(parser().parse_args(argv))
