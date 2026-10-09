"""capture_read.combine on synthetic readings in a temporary directory. No real page is used."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from capture_read import combine as cb

SHOP = "https://shop.example/p"


def _row(url: str, at: str, state: str = "ok", mark: str = "") -> dict[str, Any]:
    return {"url": url, "retrieved_at": at, "capture_state": state, "mark": mark}


def _wave1(tmp_path: Path, *rows: dict[str, Any]) -> Path:
    path = tmp_path / "captures.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")
    return path


def _readings(tmp_path: Path, name: str, *rows: dict[str, Any]) -> Path:
    directory = tmp_path / name / "readings"
    directory.mkdir(parents=True)
    with gzip.open(directory / "part-00000.jsonl.gz", "wt", encoding="utf-8") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in rows)
    return directory


def _run(tmp_path: Path, *argv: str) -> tuple[int, list[dict[str, Any]]]:
    out = tmp_path / "out" / "captures.combined.jsonl"
    out.parent.mkdir(exist_ok=True)
    rc = cb.main([*argv, "--out", str(out)])
    kept = (
        [json.loads(line) for line in out.read_text("utf-8").splitlines()] if out.exists() else []
    )
    return rc, kept


def test_an_ok_reading_is_kept_over_a_newer_failed_one(tmp_path: Path) -> None:
    wave1 = _wave1(tmp_path, _row(f"{SHOP}/1", "2026-10-03T08:00:00+00:00", mark="good"))
    tail = _readings(
        tmp_path, "tail", _row(f"{SHOP}/1", "2026-10-04T08:00:00+00:00", "blocked", "newer")
    )
    gap = _readings(
        tmp_path, "gaptail2", _row(f"{SHOP}/1", "2026-10-07T08:00:00+00:00", "http_404", "gone")
    )
    rc, kept = _run(tmp_path, "--wave1", str(wave1), "--tail", str(tail), "--gap", str(gap))
    assert rc == 0
    assert [r["mark"] for r in kept] == ["good"]


def test_the_newest_ok_reading_of_a_page_wins_across_url_spellings(tmp_path: Path) -> None:
    wave1 = _wave1(
        tmp_path,
        _row(f"{SHOP}/1", "2026-10-03T08:00:00+00:00", mark="old"),
        _row(f"{SHOP}/2", "2026-10-03T09:00:00+00:00", mark="only"),
    )
    tail = _readings(tmp_path, "tail", _row(f"{SHOP}/1", "2026-10-04T08:00:00+00:00", mark="new"))
    rc, kept = _run(tmp_path, "--wave1", str(wave1), "--tail", str(tail))
    assert rc == 0
    assert [r["mark"] for r in kept] == ["new", "only"]


@pytest.mark.parametrize(
    "variant",
    [f"{SHOP}/1?colour=red", f"{SHOP}/1/", "https://www.shop.example/p/1", f"{SHOP}/1#reviews"],
)
def test_one_page_key_over_two_different_urls_stops_and_writes_nothing(
    tmp_path: Path, variant: str, capsys: pytest.CaptureFixture[str]
) -> None:
    wave1 = _wave1(tmp_path, _row(f"{SHOP}/1", "2026-10-03T08:00:00+00:00"))
    tail = _readings(tmp_path, "tail", _row(variant, "2026-10-04T08:00:00+00:00"))
    rc, kept = _run(tmp_path, "--wave1", str(wave1), "--tail", str(tail))
    assert rc == 2
    assert kept == []
    assert "STOP: 1 page keys cover more than one URL" in capsys.readouterr().err


def test_a_failed_reading_of_another_url_spelling_does_not_stop(tmp_path: Path) -> None:
    wave1 = _wave1(tmp_path, _row(f"{SHOP}/1", "2026-10-03T08:00:00+00:00", mark="good"))
    tail = _readings(
        tmp_path, "tail", _row(f"{SHOP}/1?x=1", "2026-10-04T08:00:00+00:00", "http_404")
    )
    rc, kept = _run(tmp_path, "--wave1", str(wave1), "--tail", str(tail))
    assert (rc, [r["mark"] for r in kept]) == (0, ["good"])


@pytest.mark.parametrize(
    ("passes", "winner"),
    [(("wave1", "tail", "gap"), "gap"), (("wave1", "tail"), "tail"), (("wave1",), "wave1")],
)
def test_readings_at_the_same_instant_are_broken_gap_then_tail_then_wave1(
    tmp_path: Path, passes: tuple[str, ...], winner: str
) -> None:
    # the same instant written two ways: the time is compared, not the text
    at = {"wave1": "2026-10-03T12:00:00+00:00", "tail": "2026-10-03T16:00:00+04:00"}
    at["gap"] = "2026-10-03T12:00:00.000000+00:00"
    wave1 = _wave1(tmp_path, _row(f"{SHOP}/1", at["wave1"], mark="wave1"))
    tail_rows = [_row(f"{SHOP}/1", at["tail"], mark="tail")] if "tail" in passes else []
    tail = _readings(tmp_path, "tail", *tail_rows, _row(f"{SHOP}/9", at["wave1"], mark="other"))
    argv = ["--wave1", str(wave1), "--tail", str(tail)]
    if "gap" in passes:
        argv += [
            "--gap",
            str(_readings(tmp_path, "gaptail2", _row(f"{SHOP}/1", at["gap"], mark="gap"))),
        ]
    rc, kept = _run(tmp_path, *argv)
    assert rc == 0
    assert {r["url"]: r["mark"] for r in kept}[f"{SHOP}/1"] == winner


def test_the_summary_counts_each_pass_by_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wave1 = _wave1(
        tmp_path,
        _row(f"{SHOP}/1", "2026-10-03T08:00:00+00:00"),
        _row(f"{SHOP}/2", "2026-10-03T08:00:00+00:00", "blocked"),
    )
    tail = _readings(tmp_path, "tail", _row(f"{SHOP}/2", "2026-10-04T08:00:00+00:00"))
    rc, _ = _run(tmp_path, "--wave1", str(wave1), "--tail", str(tail))
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {
        "by_source_state": {"tail:ok": 1, "wave1:blocked": 1, "wave1:ok": 1},
        "ok_observations": 2,
        "pages_after_dedupe": 2,
        "kept_from": {"tail": 1, "wave1": 1},
        "same_instant_same_pass": 0,
    }


def test_two_readings_of_a_page_at_one_instant_from_one_pass_keep_file_order_and_are_counted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    at = "2026-10-03T08:00:00+00:00"
    wave1 = _wave1(
        tmp_path, _row(f"{SHOP}/1", at, mark="first"), _row(f"{SHOP}/1", at, mark="second")
    )
    tail = _readings(tmp_path, "tail", _row(f"{SHOP}/2", at))
    rc, kept = _run(tmp_path, "--wave1", str(wave1), "--tail", str(tail))
    assert (rc, {r["url"]: r["mark"] for r in kept}[f"{SHOP}/1"]) == (0, "first")
    assert json.loads(capsys.readouterr().out)["same_instant_same_pass"] == 1


def test_a_reading_time_without_an_offset_stops_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wave1 = _wave1(tmp_path, _row(f"{SHOP}/1", "2026-10-03T08:00:00+00:00"))
    tail = _readings(tmp_path, "tail", _row(f"{SHOP}/1", "2026-10-04T08:00:00"))
    rc, kept = _run(tmp_path, "--wave1", str(wave1), "--tail", str(tail))
    assert (rc, kept) == (2, [])
    assert "has no offset" in capsys.readouterr().err


@pytest.mark.parametrize("problem", ["out_exists", "empty_gap", "no_wave1"])
def test_missing_inputs_or_an_existing_output_stop_before_writing(
    tmp_path: Path, problem: str
) -> None:
    wave1 = _wave1(tmp_path, _row(f"{SHOP}/1", "2026-10-03T08:00:00+00:00"))
    tail = _readings(tmp_path, "tail", _row(f"{SHOP}/2", "2026-10-04T08:00:00+00:00"))
    out = tmp_path / "captures.combined.jsonl"
    argv = ["--wave1", str(wave1), "--tail", str(tail), "--out", str(out)]
    if problem == "out_exists":
        out.write_text("kept\n", "utf-8")
    elif problem == "empty_gap":
        (tmp_path / "gaptail2" / "readings").mkdir(parents=True)
        argv += ["--gap", str(tmp_path / "gaptail2" / "readings")]
    else:
        argv[1] = str(tmp_path / "absent.jsonl")
    assert cb.main(argv) == 2
    if problem == "out_exists":
        assert out.read_text("utf-8") == "kept\n"
    else:
        assert not out.exists()
