"""The admission record and the deploy check (docs/runbooks/pi-api-deploy.md §6)."""

from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path

import pi_api_admission as admission
import publish_dataset
import pytest

from api_fixture import served_dataset, write
from pi_dataset import V3_MAX_BYTES, admission_sha256, dump_dataset

BIG = "datasets/ae/ounass_ae/latest.json"
SMALL = "datasets/ae/faces/latest.json"
COMMIT = "0" * 40
GATE = 1000


def served(path: str, size: int, sha: str) -> admission.Served:
    return admission.Served(path=path, bytes=size, sha256=sha)


def record(**changes: object) -> admission.Record:
    fields: dict[str, object] = {
        "schema": admission.SCHEMA,
        "dataset": BIG,
        "sha256": "a" * 64,
        "bytes": 5000,
        "memoryMiB": 3072,
        "served": [
            served(BIG, 5000, "a" * 64).model_dump(),
            served(SMALL, 500, "b" * 64).model_dump(),
        ],
        "baselineMiB": 68,
        "coldStartPeakMiB": 1474,
        "refreshPeaksMiB": [1967, 1967, 1967, 1993],
        "measuredOn": "2026-10-07",
        "benchCommit": COMMIT,
    }
    return admission.Record.model_validate({**fields, **changes})


NOW = {BIG: served(BIG, 5000, "a" * 64), SMALL: served(SMALL, 500, "b" * 64)}


def test_a_passing_record_admits_its_exact_sha() -> None:
    admitted, refused = admission.check([record()], 3072, NOW, GATE)
    assert refused == []
    assert admitted == frozenset({"a" * 64})


def test_a_sha_mismatch_is_refused() -> None:
    now = {**NOW, BIG: served(BIG, 5000, "c" * 64)}
    admitted, refused = admission.check([record()], 3072, now, GATE)
    assert admitted == frozenset()
    assert refused == [
        f"REFUSED {BIG} 5000 bytes sha256={'c' * 64}: over the 1000-byte gate and no "
        "admission record has this sha256"
    ]


def test_a_peak_over_75_percent_of_memory_is_refused() -> None:
    over = record(refreshPeaksMiB=[1967, 2305, 1967, 1967])
    admitted, refused = admission.check([over], 3072, NOW, GATE)
    assert admitted == frozenset()
    assert refused == [
        f"REFUSED {BIG} sha256={'a' * 64}: refresh peak 2305 MiB is over 75% of 3072 MiB (2304 MiB)"
    ]


def test_a_peak_at_exactly_75_percent_passes() -> None:
    at = record(refreshPeaksMiB=[2304, 1967, 1967, 1967])
    assert admission.check([at], 3072, NOW, GATE) == (frozenset({"a" * 64}), [])


def test_a_record_measured_at_another_memory_is_refused() -> None:
    _, refused = admission.check([record()], 2048, NOW, GATE)
    assert any("measured at 3072 MiB, this revision has 2048 MiB" in r for r in refused)


def test_a_record_measured_with_other_files_is_refused() -> None:
    grown = {**NOW, SMALL: served(SMALL, 900, "d" * 64)}
    _, refused = admission.check([record()], 3072, grown, GATE)
    assert any(f"{SMALL} grew from 500 to 900 bytes" in r for r in refused)
    extra = {**NOW, "datasets/ae/beauty/latest.json": served("x", 10, "e" * 64)}
    _, refused = admission.check([record()], 3072, extra, GATE)
    assert any("measured with" in r for r in refused)


def test_files_within_the_gate_need_no_record() -> None:
    assert admission.check([], 3072, NOW, 5000) == (frozenset(), [])


def test_the_record_names_a_file_it_served() -> None:
    with pytest.raises(ValueError, match="is not among the served files"):
        record(sha256="f" * 64)


def test_the_record_schema_is_closed() -> None:
    with pytest.raises(ValueError, match="Extra inputs"):
        record(note="hand-edited")
    with pytest.raises(ValueError, match="refreshPeaksMiB"):
        record(refreshPeaksMiB=[1967, 1967])


def test_measure_serves_every_file_and_writes_a_record_check_accepts(tmp_path: Path) -> None:
    dataset = served_dataset()
    small = len(dump_dataset(dataset, compact=True))
    (tmp_path / SMALL).parent.mkdir(parents=True)
    (tmp_path / SMALL).write_bytes(dump_dataset(dataset, compact=True))
    big = dump_dataset(dataset)  # indented, so larger; stored gzip as the publisher does
    (tmp_path / BIG).parent.mkdir(parents=True)
    (tmp_path / BIG).write_bytes(gzip.compress(big, mtime=0))
    gate = (len(big) + small) // 2
    assert small <= gate < len(big)
    datasets = f"{SMALL},{BIG}"

    rec = admission.measure(
        tmp_path, datasets, memory_mib=3072, bench_commit=COMMIT, today=date(2026, 10, 7), gate=gate
    )

    assert rec.dataset == BIG
    assert rec.sha256 == admission_sha256(big)  # the decompressed body, not the gzip object
    assert {s.path for s in rec.served} == {BIG, SMALL}
    assert len(rec.refresh_peaks_mib) == admission.REFRESHES
    assert rec.cold_start_peak_mib >= rec.baseline_mib
    out = tmp_path / "admission"
    out.mkdir()
    (out / "ounass_ae.json").write_text(admission.dump(rec), encoding="utf-8")
    assert json.loads((out / "ounass_ae.json").read_text())["schema"] == "pi.admission/v1"
    now = admission.served(tmp_path, admission.served_paths(datasets))
    assert admission.check(admission.load_records(out), 3072, now, gate) == (
        frozenset({rec.sha256}),
        [],
    )


def test_measure_refuses_when_nothing_is_over_the_gate(tmp_path: Path) -> None:
    write(tmp_path, served_dataset(), SMALL)
    with pytest.raises(SystemExit, match="within the gate"):
        admission.measure(
            tmp_path, SMALL, memory_mib=3072, bench_commit=COMMIT, today=date(2026, 10, 7)
        )


def test_the_check_command_prints_the_admitted_set_or_stops(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, served_dataset(), SMALL)
    records = tmp_path / "admission"
    records.mkdir()
    args = ["check", "--root", str(tmp_path), "--datasets", SMALL, "--memory-mib", "3072"]
    assert admission.main([*args, "--admission-dir", str(records)]) == 0
    assert capsys.readouterr().out == "PI_API_ADMITTED=\nADMISSION OK\n"
    assert len((tmp_path / SMALL).read_bytes()) < V3_MAX_BYTES


def test_the_check_command_stops_on_an_unadmitted_body(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tmp_path, served_dataset(), SMALL)
    monkeypatch.setattr(admission, "V3_MAX_BYTES", 10)
    records = tmp_path / "admission"
    records.mkdir()
    args = ["check", "--root", str(tmp_path), "--datasets", SMALL, "--memory-mib", "3072"]
    assert admission.main([*args, "--admission-dir", str(records)]) == 1
    captured = capsys.readouterr()
    assert captured.out == "ADMISSION STOP\n"
    assert "no admission record has this sha256" in captured.err


def test_the_peak_sampler_keeps_the_highest_sample() -> None:
    samples = iter([10, 50])
    peak = admission.Peak(lambda: next(samples, 20))
    assert peak.stop() == 50
    peak.reset()
    assert peak.value == 20


def test_the_publisher_prints_the_sha_pi_api_checks() -> None:
    body = dump_dataset(served_dataset(), compact=True)
    line = publish_dataset.admission_line(gzip.compress(body, mtime=0))
    assert line == f"admission body={len(body)}B sha256={admission_sha256(body)}"
