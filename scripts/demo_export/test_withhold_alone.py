"""``--withhold-alone`` (Coordinator 01a11f65-8dca, 01a11f65-cfeb, 01a11f66-02b5): ulta_ae exported
alone from its own run, withheld, as its own per-source file beside a windowed sephora_me in
another file. The composed view keeps each file's own date and Ulta's entry (compose.py:243), the
window guard passes under PI_API_REQUIRE_ALL, and /coverage dates Ulta by its own data."""

# ruff: noqa: S101

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from pi_api.app import app_from_env
from pi_api.source import LocalStore, SnapshotSource
from pi_api.windows import check_windows, window_problems
from pi_dataset import DatasetV3, dump_dataset, load_any
from pi_dataset.compose import only
from pi_dataset.models import RetailerStatus
from pi_metrics.coverage import Coverage, coverage
from scripts.demo_export.export import check_args, parser, withheld_of
from scripts.demo_export.test_v2 import NOTE
from scripts.demo_export.test_window import SEPHORA, ULTA, offers
from scripts.demo_export.test_withhold import BEAUTY, UNBLOCKED, beauty
from scripts.demo_export.v2 import Withheld, build_dataset_v2, crawl_windows, to_v3

S_PATH, U_PATH = "datasets/ae/sephora_me/v/1.json", "datasets/ae/ulta_ae/v/1.json"
#: Sephora's Dubai cutoff day, the roll-time ``--withhold-until``.
UNTIL = date(2026, 10, 9)
OCT_1, OCT_2 = date(2026, 10, 1), date(2026, 10, 2)
WHY = {
    "en": "ulta.ae blocks our collection since 2026-10-02; prices last collected <since>",
    "ar": "يحظر ulta.ae جمع البيانات منذ 2026-10-02؛ آخر جمع للأسعار <since>",
}
SAID = {
    "en": "ulta.ae blocks our collection since 2026-10-02; prices last collected 1 October 2026",
    "ar": "يحظر ulta.ae جمع البيانات منذ 2026-10-02؛ آخر جمع للأسعار 1 أكتوبر 2026",
}
ALONE = Withheld(frozenset({"u"}), WHY, UNTIL, alone=True)
ARGS = [
    "--database-url",
    "x",
    "--output",
    "o.json",
    "--output-v3",
    "o3.json",
    "--sources",
    ULTA,
    "--ulta-unblocked",
    "--run",
    f"{ULTA}=5",
    "--withhold",
    ULTA,
    "--withhold-why",
    WHY["en"],
    "--withhold-why-ar",
    WHY["ar"],
]


def ulta_alone(withheld: Withheld = ALONE) -> DatasetV3:
    """``main`` for ``ARGS`` plus ``--withhold-until 2026-10-09 --withhold-alone``: Ulta's run 5
    only, so its cutoff and date are its own (2026-10-01), not tonight's."""
    rows = [BEAUTY[1]]
    windows = crawl_windows(rows, {ULTA: (5,)})
    v2 = build_dataset_v2(
        rows,
        [],
        generated_at=max(w.end for w in windows.values()) + timedelta(hours=1),
        ulta=UNBLOCKED,
        ulta_note=NOTE,
        windows=windows,
        withheld=withheld,
    )
    v3 = load_any(dump_dataset(to_v3(v2, rows, [], windows, withheld.slots)))
    assert isinstance(v3, DatasetV3)
    return v3


def write(root: Path, ulta: DatasetV3) -> None:
    for path, part in ((S_PATH, only(beauty(), [SEPHORA])), (U_PATH, ulta)):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(dump_dataset(part))


def served(root: Path) -> SnapshotSource:
    source = SnapshotSource(LocalStore(root), (), assigned={SEPHORA: S_PATH, ULTA: U_PATH})
    source.load_all()
    return source


def env(root: Path) -> dict[str, str]:
    return {
        "PI_API_FIREBASE_PROJECT": "p",
        "PI_API_LOCAL_DIR": str(root),
        "PI_API_DATASETS": f"{SEPHORA}={S_PATH},{ULTA}={U_PATH}",
        "PI_API_REQUIRE_ALL": "1",
    }


def shops(ds: DatasetV3) -> Coverage:
    return coverage(ds, ()).data


def test_ulta_alone_is_dated_by_its_own_run() -> None:
    ds = ulta_alone()
    (shop,) = [r for r in ds.meta.retailers if r.id == ULTA]
    assert (ds.meta.dates, ds.meta.cutoff.date()) == ((OCT_1,), OCT_1)
    # item 5 (01a11f69-b7b3): the ulta_ae catalogue resolves only on these two literals
    assert (ds.meta.scope, [m.country for m in ds.meta.markets]) == ("beauty", ["AE"])
    assert {o.evidence.captured_at.date() for o in offers(ds, ULTA).values() if o.evidence} == {
        OCT_1
    }
    assert (shop.window, shop.since, shop.note) == (None, OCT_1, SAID)
    entries = [(n.start, n.end, n.context, n.categories, n.why) for n in ds.not_observed]
    assert entries == [(OCT_2, UNTIL, None, None, SAID)]


def test_ulta_alone_beside_windowed_sephora_is_served_as_of_its_own_day(tmp_path: Path) -> None:
    write(tmp_path, ulta_alone())
    source = served(tmp_path)
    assert source.unserved() == []
    (view,) = source.datasets()
    ds = view.dataset
    assert ds.meta.dates == (OCT_1, UNTIL)  # each file's own date is kept
    gone = [n for n in ds.not_observed if n.retailer == ULTA]
    ulta = [(n.start, n.end, n.context, n.categories) for n in gone]
    assert (OCT_2, UNTIL, None, None) in ulta
    # (b): Ulta's own day is observed only: its values, and no entry covering it
    assert not [s for s, e, *_ in ulta if s <= OCT_1 <= e]
    assert all(o.series.price[0] is not None for o in offers(ds, ULTA).values())
    pairs = [(d.path, d.dataset) for d in source.datasets()]
    assert window_problems(pairs) == []
    (held,) = check_windows(pairs).withheld
    assert f"{ULTA} withheld, not observed until {UNTIL}" in held
    rows = {r.id: r for r in shops(ds).retailers}
    assert (rows[ULTA].since, rows[ULTA].freshness, rows[ULTA].note) == (OCT_1, OCT_1, SAID)
    assert rows[ULTA].status is not RetailerStatus.BLOCKED
    assert rows[SEPHORA].freshness == UNTIL
    assert app_from_env(env(tmp_path)) is not None


def test_trap_ulta_cut_from_tonights_single_date_body_reads_fresh(tmp_path: Path) -> None:
    """Why item 2 is exported alone: cut from tonight's body, the guard passes too, but every
    Oct 1 value is filed under the cutoff day and /coverage reads Ulta as fresh (01a11f62-f17a)."""
    write(tmp_path, only(beauty(), [ULTA]))
    source = served(tmp_path)
    (view,) = source.datasets()
    assert window_problems([(d.path, d.dataset) for d in source.datasets()]) == []
    rows = {r.id: r for r in shops(view.dataset).retailers}
    assert (rows[ULTA].since, rows[ULTA].freshness) == (OCT_1, UNTIL)


def test_control_ulta_alone_without_its_entry_is_refused_at_start(tmp_path: Path) -> None:
    write(tmp_path, ulta_alone().model_copy(update={"not_observed": ()}))
    assert served(tmp_path).unserved() == ["composed views"]
    with pytest.raises(RuntimeError, match="PI_API_REQUIRE_ALL: not loaded at start: composed"):
        app_from_env(env(tmp_path))


def test_without_alone_the_entry_still_starts_on_the_cutoff_day() -> None:
    """Outside the flag nothing changes: the entry starts on the body's cutoff day when that is
    before the day after since, and the note stays the exporter's."""
    ds = ulta_alone(Withheld(frozenset({"u"}), WHY, UNTIL))
    (shop,) = [r for r in ds.meta.retailers if r.id == ULTA]
    assert [(n.start, n.end) for n in ds.not_observed] == [(OCT_1, UNTIL)]
    assert shop.note == NOTE


def test_alone_with_until_not_after_since_is_refused() -> None:
    """No day is both observed and not observed (01a11f65-cfeb, 01a11f76-cebd): until == since
    leaves nothing to withhold, so the export is refused, never written with an entry on
    the slice's own day."""
    message = "--withhold-alone: --withhold-until 2026-10-01 is not after since 2026-10-01"
    with pytest.raises(ValueError, match=message):
        ulta_alone(Withheld(frozenset({"u"}), WHY, OCT_1, alone=True))


def test_withhold_alone_flags_become_withheld_slots() -> None:
    args = parser().parse_args([*ARGS, "--withhold-until", "2026-10-09", "--withhold-alone"])
    check_args(args)
    assert withheld_of(args) == ALONE


TWO_RUNS = ["--run", f"{SEPHORA}=7"]


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (ARGS, "every source is withheld"),
        ([*ARGS, "--withhold-alone"], "needs --withhold-until"),
        ([*ARGS[:-6], "--withhold-alone"], "need --withhold"),
        (
            [*ARGS[:7], f"{SEPHORA},{ULTA}", *ARGS[8:], *TWO_RUNS, "--withhold-alone"],
            "needs every --sources entry withheld",
        ),
    ],
)
def test_withhold_alone_is_refused_unless_complete(argv: list[str], message: str) -> None:
    with pytest.raises(SystemExit, match=message):
        check_args(parser().parse_args(argv))
