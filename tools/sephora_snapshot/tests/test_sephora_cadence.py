"""Unattended runs: window, gap-first plan, terminal status and the day-10 unloaded check.
Synthetic ids only; no network (fetches are stubbed, output goes to a local folder)."""

import gzip
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sephora_snapshot import cadence, run, stale
from sephora_synth import details, pdp_html, trpc_json


def at(hhmm: str, day: int = 1) -> datetime:
    return datetime.fromisoformat(f"2026-10-{day:02d}T{hhmm}:00+00:00")


# ---------------------------------------------------------------- window
@pytest.mark.parametrize(
    ("start", "cutoff"),
    [
        (at("18:00"), at("01:55", 2)),
        (at("23:59"), at("01:55", 2)),
        (at("00:30", 2), at("01:55", 2)),
    ],
)
def test_cutoff_is_the_next_0155z(start: datetime, cutoff: datetime) -> None:
    assert cadence.auto_cutoff(start) == cutoff


@pytest.mark.parametrize("start", [at("01:55"), at("01:59"), at("02:00"), at("12:00"), at("17:59")])
def test_start_outside_the_window_is_refused(start: datetime) -> None:
    with pytest.raises(cadence.OutsideWindow):
        cadence.auto_cutoff(start)


def test_prefix_is_dated_by_the_start_to_the_second() -> None:
    assert cadence.auto_prefix(at("18:00")) == "auto-20261001T180000Z"


def test_prefix_carries_the_cloud_run_execution_and_attempt() -> None:
    first = cadence.auto_prefix(at("18:00"), "pi-sephora-auto-x7k2p", "0")
    retry = cadence.auto_prefix(at("18:00"), "pi-sephora-auto-x7k2p", "1")
    assert first == "auto-20261001T180000Z-x7k2p-0"
    assert retry == "auto-20261001T180000Z-x7k2p-1"


# ---------------------------------------------------------------- plan
def test_gap_first_order() -> None:
    seen = {
        "P2": cadence.Seen("2026-09-30T22:00:00+00:00", multi_price=False),
        "P3": cadence.Seen("2026-09-29T22:00:00+00:00", multi_price=False),
        "P4": cadence.Seen("2026-09-30T22:00:00+00:00", multi_price=True),
    }
    order, tiers = cadence.gap_first(["P1", "P2", "P3", "P4", "P5"], seen)
    assert set(order[:2]) == {"P1", "P5"}  # never read
    assert order[2:] == ["P4", "P3", "P2"]  # multi-price, then the longest-unread first
    assert tiers == {"unread": 2, "multi_price": 1, "rest": 2}


def test_unread_tier_keeps_the_seeded_shuffle() -> None:
    pids = [f"P{i}" for i in range(50)]
    order, _ = cadence.gap_first(pids, {})
    assert order != sorted(pids)
    assert order == cadence.gap_first(reversed(pids), {})[0]


@pytest.mark.parametrize("newest_first", [True, False])
def test_merge_keeps_the_newest_read_in_any_order(newest_first: bool) -> None:
    old = {"pdp_en": {"P1": {"at": "2026-09-29T22:00:00+00:00", "multi_price": True}}}
    new = {"pdp_en": {"P1": {"at": "2026-09-30T22:00:00+00:00", "multi_price": False}}}
    runs = [new, old] if newest_first else [old, new]
    assert cadence.merge_covered(runs) == {
        "P1": cadence.Seen("2026-09-30T22:00:00+00:00", multi_price=False)
    }


@pytest.mark.parametrize("newest_first", [True, False])
def test_merge_keeps_the_newest_failed_attempt_in_any_order(newest_first: bool) -> None:
    old = {"attempted_en": {"P1": {"at": "2026-09-29T22:00:00+00:00"}}}
    new = {"attempted_en": {"P1": {"at": "2026-09-30T22:00:00+00:00"}}}
    runs = [new, old] if newest_first else [old, new]
    assert cadence.merge_covered(runs) == {
        "P1": cadence.Seen("2026-09-30T22:00:00+00:00", multi_price=False)
    }


def test_a_failed_page_moves_out_of_the_unread_tier() -> None:
    runs: list[dict[str, Any]] = [
        {"pdp_en": {"P1": {"at": "2026-09-28T22:00:00+00:00", "multi_price": True}}},
        {"attempted_en": {"P1": {"at": "2026-09-30T22:00:00+00:00"}}},  # later read failed
        {"attempted_en": {"P2": {"at": "2026-09-30T22:00:00+00:00"}}},  # never read
    ]
    seen = cadence.merge_covered(runs)
    assert seen == {
        "P1": cadence.Seen("2026-09-30T22:00:00+00:00", multi_price=True),
        "P2": cadence.Seen("2026-09-30T22:00:00+00:00", multi_price=False),
    }
    order, tiers = cadence.gap_first(["P1", "P2", "P3"], seen)
    assert order == ["P3", "P1", "P2"]
    assert tiers == {"unread": 1, "multi_price": 1, "rest": 1}


def test_multi_price_compares_the_price_shown() -> None:
    d = details("P1")
    assert not cadence.multi_price(d)
    d["c_variantsInfo"].append({"c_price": 100, "c_salesPrice": 80})
    assert not cadence.multi_price(d)  # same sale price
    d["c_variantsInfo"].append({"c_price": 120})
    assert cadence.multi_price(d)


@pytest.mark.parametrize(
    ("stopped", "expected"),
    [
        ("complete", "complete"),
        ("cutoff", "cutoff"),
        ("outside_window", "outside_window"),
        ("refused: AUTO=1 derives PREFIX", "refused"),
        ("challenge: marker 'captcha' (http 200) at u", "blocked"),
        ("blocked: http 403 at u", "blocked"),
        ("3 consecutive 429", "rate_limited"),
        ("10 consecutive transport errors", "error"),
        ("sigterm", "error"),
        ("error: RuntimeError()", "error"),
        (None, "error"),
    ],
)
def test_outcome(stopped: str | None, expected: str) -> None:
    assert cadence.outcome(stopped) == expected


# ---------------------------------------------------------------- AUTO job
@pytest.fixture
def auto_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("BUCKET", f"file:{tmp_path}")
    monkeypatch.setenv("AUTO", "1")
    for key in ("PREFIX", "CUTOFF", "PLAN", "CLOUD_RUN_EXECUTION", "CLOUD_RUN_TASK_ATTEMPT"):
        monkeypatch.delenv(key, raising=False)
    return tmp_path


def _clock(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    class Clock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
            return now

    monkeypatch.setattr(run, "datetime", Clock)


def _stub(job: run.Job, monkeypatch: pytest.MonkeyPatch, pids: list[str]) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(
        job, "seed", lambda: {p: {"en": f"https://www.sephora.me/ae-en/p/x/{p}"} for p in pids}
    )

    def get(url: str, locale: str, kind: str) -> tuple[int, bytes, dict[str, Any]]:
        pid = (
            url.rsplit("/", 1)[-1]
            if kind == "html"
            else json.loads(url.split("input=")[1])["0"]["json"]["productId"]
        )
        calls.append(f"{kind}:{pid}")
        meta = {"url": url, "locale": locale, "at": "2026-10-01T22:00:00+00:00", "status": 200}
        body = json.dumps(trpc_json(pid)) if kind == "json" else pdp_html(details(pid))
        return 200, body.encode(), meta

    monkeypatch.setattr(job, "get", get)
    return calls


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("PREFIX", "price-20260930T1800Z"),
        ("CUTOFF", "2026-10-01T03:20:00+00:00"),
        ("PLAN", "plan_price_20260930.json.gz"),
    ],
)
def test_stale_one_shot_env_is_refused_with_a_status(
    auto_env: Path, monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    monkeypatch.setenv(key, value)
    _clock(monkeypatch, at("18:00"))
    job = run.Job()
    assert job.prefix == "auto-20261001T180000Z"  # never the stale PREFIX
    monkeypatch.setattr(job, "seed", lambda: pytest.fail("no request on a refused run"))
    monkeypatch.setattr(run, "Job", lambda: job)
    assert run.main() == 1
    assert [p.name for p in auto_env.iterdir()] == ["auto-20261001T180000Z"]
    status = json.loads((auto_env / "auto-20261001T180000Z" / "status.json").read_text())
    assert (status["outcome"], status["loadable"]) == ("refused", False)
    assert key in status["stopped"]


def test_an_existing_prefix_is_refused_before_anything_is_written(
    auto_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = auto_env / "auto-20261001T180000Z-x7k2p-0"
    out.mkdir()
    (out / "status.json").write_text("{}")
    monkeypatch.setenv("CLOUD_RUN_EXECUTION", "pi-sephora-auto-x7k2p")
    monkeypatch.setenv("CLOUD_RUN_TASK_ATTEMPT", "0")
    _clock(monkeypatch, at("18:00"))
    with pytest.raises(ValueError, match="already holds objects"):
        run.Job()
    assert [p.name for p in out.iterdir()] == ["status.json"]
    assert (out / "status.json").read_text() == "{}"


def test_an_unreadable_covered_file_is_skipped_and_counted(
    auto_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (auto_env / "auto-20260930T180000Z").mkdir()
    (auto_env / "auto-20260930T180000Z" / "covered.json.gz").write_bytes(b"not gzip")
    _clock(monkeypatch, at("18:00"))
    job = run.Job()
    calls = _stub(job, monkeypatch, ["P1"])
    job.run()
    assert calls == ["html:P1", "json:P1"]
    assert job.counts["plan_covered_unreadable"] == 1
    assert job.counts["plan_history_runs"] == 0


def test_auto_run_plans_from_earlier_runs_and_pairs_page_with_stock(
    auto_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    earlier = {"pdp_en": {"P1": {"at": "2026-09-30T22:00:00+00:00", "multi_price": False}}}
    (auto_env / "auto-20260930T180000Z").mkdir()
    (auto_env / "auto-20260930T180000Z" / "covered.json.gz").write_bytes(
        gzip.compress(json.dumps(earlier).encode())
    )
    _clock(monkeypatch, at("18:00"))
    job = run.Job()
    assert (job.prefix, job.cutoff, job.mode) == ("auto-20261001T180000Z", at("01:55", 2), "auto")
    calls = _stub(job, monkeypatch, ["P1", "P2"])
    job.run()
    assert calls == ["html:P2", "json:P2", "html:P1", "json:P1"]  # unread P2 first
    assert job.counts["plan_history_runs"] == 1
    assert job.covered["pdp_en"].keys() == {"P1", "P2"}
    assert job.covered["trpc"].keys() == {"P1", "P2"}
    assert job.covered["attempted_en"].keys() == {"P1", "P2"}


def test_auto_outside_window_fetches_nothing_and_says_so(
    auto_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clock(monkeypatch, at("12:00"))
    job = run.Job()
    monkeypatch.setattr(job, "seed", lambda: pytest.fail("no request outside the window"))
    monkeypatch.setattr(run, "Job", lambda: job)
    assert run.main() == 0
    status = json.loads((auto_env / "auto-20261001T120000Z" / "status.json").read_text())
    assert (status["outcome"], status["loadable"]) == ("outside_window", False)


def test_every_run_ends_with_status_and_covered(
    auto_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clock(monkeypatch, at("18:00"))
    job = run.Job()
    _stub(job, monkeypatch, ["P1"])
    monkeypatch.setattr(run, "Job", lambda: job)
    assert run.main() == 0
    out = auto_env / "auto-20261001T180000Z"
    status = json.loads((out / "status.json").read_text())
    assert status["state"] == "finished"
    assert (status["outcome"], status["stopped"], status["loadable"]) == (
        "complete",
        "complete",
        True,
    )
    covered = json.loads(gzip.decompress((out / "covered.json.gz").read_bytes()))
    assert covered["pdp_en"]["P1"]["multi_price"] is False


def test_an_unexpected_error_still_writes_status_and_fails(
    auto_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clock(monkeypatch, at("18:00"))
    job = run.Job()

    def boom() -> dict[str, dict[str, str]]:
        raise RuntimeError("synthetic")

    monkeypatch.setattr(job, "seed", boom)
    monkeypatch.setattr(run, "Job", lambda: job)
    assert run.main() == 1
    status = json.loads((auto_env / "auto-20261001T180000Z" / "status.json").read_text())
    assert status["outcome"] == "error"


# ---------------------------------------------------------------- day-10 check
NOW = at("12:00", 20)


def _state(prefix: str, age_days: int, **counts: int) -> cadence.RunState:
    return cadence.RunState(f"gs://b/{prefix}", NOW - timedelta(days=age_days), counts)


def test_unloaded_reports_only_old_loadable_unfinished_runs() -> None:
    runs = [
        _state("old-unloaded", 10, pdp_en_ok=5),
        _state("old-loaded", 12, pdp_en_ok=5),
        _state("young", 9, pdp_en_ok=5),
        _state("old-empty", 11, block_challenge=1),
        _state("old-stock-only", 13, trpc_http_200=3),
    ]
    late = cadence.unloaded(runs, {"gs://b/old-loaded"}, NOW)
    assert [r.prefix for r in late] == ["gs://b/old-stock-only", "gs://b/old-unloaded"]


def test_run_states_prefer_status_over_progress() -> None:
    files: list[tuple[str, dict[str, Any]]] = [
        ("r1/progress.json", {"started": "2026-10-01T18:00:00+00:00", "counts": {"x": 1}}),
        ("r1/status.json", {"started": "2026-10-01T18:00:00+00:00", "counts": {"pdp_en_ok": 2}}),
        ("r2/progress.json", {"started": "2026-10-02T18:00:00+00:00", "counts": {}}),
        ("r2/sub/status.json", {"started": "2026-10-02T18:00:00+00:00"}),  # not a run root
        ("r3/progress.json", {}),  # no start time: not a run
    ]
    states = stale.run_states("b", files)
    assert [(s.prefix, dict(s.counts)) for s in states] == [
        ("gs://b/r1", {"pdp_en_ok": 2}),
        ("gs://b/r2", {}),
    ]


def test_finished_prefix_matches_the_loaders_manifest_uri() -> None:
    manifest = "gs://b/auto-20261001T1800Z/progress.json#lang=en"  # load.Loader._run
    assert manifest.split("/progress.json#", 1)[0] == "gs://b/auto-20261001T1800Z"
    assert "split_part(manifest_uri, '/progress.json#', 1)" in stale.FINISHED_SQL
