"""``--serve-history`` (Coordinator 01a11f69-5abb item 2): a slice exported with it states
``capabilities.history=True``, so the composed view serves every day and each retailer's value
only on its own capture day. Unflagged exports are byte for byte what they were."""

# ruff: noqa: S101

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from pi_api.catalog import HistoryQuery, history
from pi_dataset import DatasetV3, dump_dataset, load_any
from pi_dataset.compose import compose, only
from pi_metrics.index import price_index
from pi_metrics.launches import launches
from pi_metrics.model import CaveatCode, ProductFilter
from scripts.demo_export import export
from scripts.demo_export.export import check_args, parser
from scripts.demo_export.test_v2 import NOTE
from scripts.demo_export.test_window import FACES, SEPHORA, ULTA, faces_carry
from scripts.demo_export.test_withhold import BEAUTY, UNBLOCKED, beauty
from scripts.demo_export.v2 import build_dataset_v2, crawl_windows, served_history, to_v3

LAUNCHES_WITHHELD = CaveatCode.LAUNCHES_WITHHELD
#: Each retailer's one capture day (Dubai): Ulta run 5, Faces run 9, Sephora run 7.
OWN = {ULTA: date(2026, 10, 1), FACES: date(2026, 10, 8), SEPHORA: date(2026, 10, 9)}
ARGV = [
    "export",
    "--database-url",
    "x",
    "--sources",
    f"{SEPHORA},{ULTA}",
    "--ulta-unblocked",
    "--run",
    f"{SEPHORA}=7",
    "--run",
    f"{ULTA}=5",
    "--generated-at",
    "2026-10-09T09:00:00Z",
]


def ulta_slice() -> DatasetV3:
    """Ulta's own run 5, exported alone, then flagged."""
    rows = [BEAUTY[1]]
    windows = crawl_windows(rows, {ULTA: (5,)})
    v2 = build_dataset_v2(
        rows,
        [],
        generated_at=max(w.end for w in windows.values()) + timedelta(hours=1),
        ulta=UNBLOCKED,
        ulta_note=NOTE,
        windows=windows,
    )
    v3 = load_any(dump_dataset(served_history(to_v3(v2, rows, [], windows))))
    assert isinstance(v3, DatasetV3)
    return v3


def final_set() -> DatasetV3:
    """The composed final set's shape: Ulta flagged, Sephora windowed, Faces with a carried
    listing; only the Ulta slice states history."""
    slices = [only(beauty(None), [SEPHORA]), only(ulta_slice(), [ULTA]), faces_carry()]
    return compose(slices).dataset


def unflip(ds: DatasetV3) -> DatasetV3:
    retailers = tuple(
        r.model_copy(update={"capabilities": r.capabilities.model_copy(update={"history": False})})
        if r.capabilities is not None
        else r
        for r in ds.meta.retailers
    )
    caps = ds.meta.capabilities.model_copy(update={"history": False})
    meta = ds.meta.model_copy(update={"capabilities": caps, "retailers": retailers})
    return ds.model_copy(update={"meta": meta})


def run_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, *flags: str
) -> tuple[bytes, bytes]:
    out, out3 = tmp_path / f"{name}.json", tmp_path / f"{name}3.json"
    monkeypatch.setattr(export, "load_rows", lambda *_: (BEAUTY, []))
    monkeypatch.setattr(
        sys, "argv", [*ARGV, "--output", str(out), "--output-v3", str(out3), *flags]
    )
    export.main()
    return out.read_bytes(), out3.read_bytes()


def test_unflagged_export_is_byte_equal_and_the_flag_moves_only_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    v1, plain = run_main(tmp_path, monkeypatch, "plain")
    v1_flagged, flagged = run_main(tmp_path, monkeypatch, "flagged", "--serve-history")
    assert v1_flagged == v1
    assert flagged != plain
    ds = load_any(flagged)
    assert isinstance(ds, DatasetV3)
    assert ds.meta.capabilities.history
    assert all(r.capabilities is not None and r.capabilities.history for r in ds.meta.retailers)
    assert dump_dataset(unflip(ds), compact=True) == plain
    unflagged = load_any(plain)
    assert isinstance(unflagged, DatasetV3)
    assert not unflagged.meta.capabilities.history
    assert served_history(unflagged, on=False) is unflagged


def test_c_the_composed_view_states_history_and_keeps_every_day() -> None:
    ds = final_set()
    assert ds.meta.capabilities.history
    assert set(OWN.values()) <= set(ds.meta.dates)


def test_d_e_each_retailer_has_a_value_only_on_its_own_capture_day() -> None:
    ds = final_set()
    shop = {c.id: c.retailer for c in ds.meta.contexts}
    valued: dict[str, set[date]] = {r: set() for r in OWN}
    for product in ds.products:
        (retailer,) = {shop[k] for k in product.offers}
        served = history(ds, product, HistoryQuery())
        for points in served.data.series.values():
            valued[retailer] |= {p.date for p in points if p.price is not None}
    assert valued == {r: {d} for r, d in OWN.items()}


def test_g_launches_without_a_filter_are_all_withheld() -> None:
    ds = final_set()
    served = launches(ds, (), ProductFilter())
    assert served.data.items == ()
    withheld = [dict(c.params) for c in served.caveats if c.code is LAUNCHES_WITHHELD]
    assert withheld == [{"count": "2"}]  # Sephora's and Faces' own day: no earlier view of it


@pytest.mark.parametrize("other", [SEPHORA, FACES])
def test_h_no_ulta_price_index_point_has_a_value(other: str) -> None:
    ds = final_set()
    for base, against in ((other, ULTA), (ULTA, other)):
        served = price_index(ds, base, against, ProductFilter())
        assert [p for p in served.data.points if getattr(p, "value", None) is not None] == []


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (["--serve-history", "--history"], "does not take --history"),
        (["--serve-history"], "needs --output-v3"),
    ],
)
def test_serve_history_is_refused_without_a_v3_body_or_with_history(
    flags: list[str], message: str
) -> None:
    argv = [*ARGV[1:], "--output", "o.json"]
    if "--history" in flags:
        argv = [a for a in argv if a not in ("--run", f"{SEPHORA}=7", f"{ULTA}=5")]
        argv += ["--output-v3", "o3.json"]
    with pytest.raises(SystemExit, match=message):
        check_args(parser().parse_args([*argv, *flags]))
