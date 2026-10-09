"""Withholding a published body beside a windowed one (ADR-0013 §8): the set pi-api composes then
serves, every value as it was, and nothing guessed (Coordinator ruling 01a122bf-547a)."""

from __future__ import annotations

# ruff: noqa: S101
import gzip
from datetime import date, timedelta
from pathlib import Path

import pytest

from pi_api.windows import check_windows
from pi_dataset import Dataset, DatasetV3, dump_dataset, load_any
from pi_dataset.compose import compose, only
from pi_metrics.view import as_v3
from scripts.demo_export.test_export import row
from scripts.demo_export.test_v2 import NOTE
from scripts.demo_export.test_window import SEPHORA, ULTA, at, seen
from scripts.demo_export.test_withhold import UNBLOCKED, beauty
from scripts.demo_export.v2 import build_dataset_v2
from scripts.demo_export.withhold_body import main, until_of, withhold_body

OCT_1, OCT_2, OCT_9 = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 9)
WHY = {"en": "Not observed since 1 October 2026", "ar": "لم تُرصد منذ 1 أكتوبر 2026"}


def windowed() -> DatasetV3:
    """Sephora's run 7, windowed, cut off on Dubai 10-09."""
    return only(beauty(None), [SEPHORA])


def stale() -> Dataset:
    """A published one-retailer Ulta body with no window, last captured on Dubai 10-01."""
    rows = [
        seen(row(source=ULTA, family=20, variant=200), at("2026-10-01T00:24"), run=5),
        seen(row(source=ULTA, family=20, variant=201), at("2026-10-01T00:30"), run=5),
    ]
    both = build_dataset_v2(
        rows, [], generated_at=at("2026-10-01T02:00"), ulta=UNBLOCKED, ulta_note=NOTE
    )
    ulta = tuple(r for r in both.meta.retailers if r.id == ULTA)
    one = both.model_copy(update={"meta": both.meta.model_copy(update={"retailers": ulta})})
    ds = load_any(dump_dataset(one))  # validated, as a published body is
    assert isinstance(ds, Dataset)
    return ds


def served(held: Dataset | DatasetV3) -> list[tuple[str, DatasetV3]]:
    v3 = held if isinstance(held, DatasetV3) else as_v3(held)
    return [("sephora", windowed()), ("ulta", v3)]


def test_a_stale_body_beside_a_windowed_one_is_refused_until_withheld() -> None:
    check = check_windows(served(stale()))
    assert len(check.problems) == 1
    assert "ulta_ae: withheld (no window) with offers but no since" in check.problems[0]
    with pytest.raises(
        ValueError, match=r"ulta_ae: withheld \(no window\) with offers but no since"
    ):
        compose([d for _, d in served(stale())])


@pytest.mark.parametrize("body", [stale, lambda: as_v3(stale())], ids=["v2", "v3"])
def test_the_withheld_body_is_served_beside_the_windowed_one(body: object) -> None:
    held = withhold_body(body(), ULTA, OCT_9)  # type: ignore[operator]
    check = check_windows(served(held))
    assert check.problems == []
    assert check.withheld == [f"ulta: {ULTA} withheld, not observed until {OCT_9}: {WHY['en']}"]
    view = compose([d for _, d in served(held)]).dataset  # the per-source view validates
    assert {r.id for r in view.meta.retailers} == {SEPHORA, ULTA}


def test_only_since_and_one_whole_retailer_entry_are_added() -> None:
    src = stale()
    held = withhold_body(src, ULTA, OCT_9)
    assert held.products == src.products
    (entry,) = held.not_observed
    assert (entry.retailer, entry.start, entry.end, entry.categories) == (ULTA, OCT_1, OCT_9, None)
    assert entry.why == WHY
    assert [r.since for r in held.meta.retailers] == [OCT_1]
    unchanged = held.meta.model_copy(update={"retailers": src.meta.retailers})
    assert unchanged == src.meta
    v3 = withhold_body(as_v3(src), ULTA, OCT_9)
    assert v3.not_observed[0].context is None


def test_the_entry_starts_the_day_after_since_when_the_cutoff_is_later() -> None:
    src = stale()
    later = src.model_copy(
        update={"meta": src.meta.model_copy(update={"cutoff": at("2026-10-02T02:00")})}
    )
    (entry,) = withhold_body(later, ULTA, OCT_9).not_observed
    assert (entry.start, entry.end) == (OCT_2, OCT_9)


def test_since_is_the_last_capture_and_must_be_the_bodys_last_date() -> None:
    src = stale()
    moved = src.model_copy(update={"meta": src.meta.model_copy(update={"dates": (OCT_2,)})})
    with pytest.raises(ValueError, match="last capture 2026-10-01 is not the body's last date"):
        withhold_body(moved, ULTA, OCT_9)


def test_nothing_is_guessed() -> None:
    src = stale()
    with pytest.raises(ValueError, match="no retailer sephora_me"):
        withhold_body(src, SEPHORA, OCT_9)
    with pytest.raises(ValueError, match="before the body's cutoff day"):
        withhold_body(src, ULTA, OCT_1 - timedelta(days=1))
    with pytest.raises(ValueError, match="already withheld"):
        withhold_body(withhold_body(src, ULTA, OCT_9), ULTA, OCT_9)
    with pytest.raises(ValueError, match="has a crawl window"):
        withhold_body(windowed(), SEPHORA, OCT_9)
    bare = src.model_copy(
        update={"products": tuple(p for p in src.products if ULTA not in p.offers)}
    )
    with pytest.raises(ValueError, match="no offers"):
        withhold_body(bare, ULTA, OCT_9)


def test_until_is_the_windowed_bodys_cutoff_day_in_the_market() -> None:
    assert until_of(windowed(), "Asia/Dubai") == OCT_9
    with pytest.raises(ValueError, match="no crawl window"):
        until_of(as_v3(stale()), "Asia/Dubai")


def test_main_writes_the_withheld_body_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src, beside, out = tmp_path / "in.json.gz", tmp_path / "w.json", tmp_path / "out.json"
    src.write_bytes(gzip.compress(dump_dataset(stale())))
    beside.write_bytes(dump_dataset(windowed()))
    argv = [str(src), str(out), "--retailer", ULTA, "--beside", str(beside)]
    main(argv)
    assert load_any(out.read_bytes()) == withhold_body(stale(), ULTA, OCT_9)
    assert f"{ULTA}: since={OCT_1} notObserved={OCT_1}..{OCT_9}" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        main(argv)


def test_main_refuses_a_beside_body_that_cannot_date_the_withhold(tmp_path: Path) -> None:
    src, beside = tmp_path / "in.json", tmp_path / "w.json"
    src.write_bytes(dump_dataset(stale()))
    beside.write_bytes(dump_dataset(stale()))
    argv = [str(src), str(tmp_path / "o.json"), "--retailer", ULTA, "--beside", str(beside)]
    with pytest.raises(SystemExit, match=r"not a pi\.dataset/v3 body"):
        main(argv)
    beside.write_bytes(dump_dataset(as_v3(stale())))
    with pytest.raises(SystemExit, match="no crawl window"):
        main(argv)
    other = windowed()
    beside.write_bytes(
        dump_dataset(
            other.model_copy(update={"meta": other.meta.model_copy(update={"scope": "x"})})
        )
    )
    with pytest.raises(SystemExit, match="--beside scope x is not beauty"):
        main(argv)


def test_main_refuses_a_retailer_the_body_does_not_hold(tmp_path: Path) -> None:
    src, beside = tmp_path / "in.json", tmp_path / "w.json"
    src.write_bytes(dump_dataset(stale()))
    beside.write_bytes(dump_dataset(windowed()))
    argv = [str(src), str(tmp_path / "o.json"), "--retailer", "faces_ae", "--beside", str(beside)]
    with pytest.raises(SystemExit, match=r"in\.json: "):
        main(argv)
    assert not (tmp_path / "o.json").exists()
