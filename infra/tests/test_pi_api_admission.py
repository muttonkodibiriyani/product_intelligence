"""The admission record and the deploy check (docs/runbooks/pi-api-deploy.md §6)."""

from __future__ import annotations

import copy
import gzip
import inspect
import json
from datetime import date
from fractions import Fraction
from pathlib import Path
from typing import Any

import pi_api_admission as admission
import publish_dataset
import pytest

from api_fixture import served_dataset, write
from pi_api.app import app_from_env
from pi_dataset import V3_MAX_BYTES, admission_sha256, dump_dataset
from pi_dataset import gate as rule
from pi_dataset.gate import ADMISSION_OTHERS_MAX_BYTES

BIG = "datasets/ae/ounass_ae/latest.json"
SMALL = "datasets/ae/faces/latest.json"
COMMIT = "0" * 40
#: Ounass's body beside Faces: 2,387 MiB fitted at 3Gi, over 2,304, so it needs a record.
OUNASS = 72_700_000
FACES = 1_400_000


def served(path: str, size: int, sha: str) -> admission.Served:
    return admission.Served(path=path, bytes=size, sha256=sha)


def record(**changes: object) -> admission.Record:
    fields: dict[str, object] = {
        "schema": admission.SCHEMA,
        "dataset": BIG,
        "sha256": "a" * 64,
        "bytes": OUNASS,
        "memoryMiB": 3072,
        "packContent": True,
        "served": [
            served(BIG, OUNASS, "a" * 64).model_dump(),
            served(SMALL, FACES, "b" * 64).model_dump(),
        ],
        "baselineMiB": 68,
        "coldStartPeakMiB": 1100,
        "refreshPeaksMiB": [1250, 1250, 1250, 1265],
        "measuredOn": "2026-10-07",
        "benchCommit": COMMIT,
    }
    return admission.Record.model_validate({**fields, **changes})


NOW = {BIG: served(BIG, OUNASS, "a" * 64), SMALL: served(SMALL, FACES, "b" * 64)}


def test_a_passing_record_admits_its_exact_sha_with_the_others_it_measured() -> None:
    assert not admission.fits(NOW, 3072)
    assert admission.check([record()], 3072, NOW) == ({"a" * 64: FACES}, [])


def test_a_sha_mismatch_is_refused() -> None:
    now = {**NOW, BIG: served(BIG, OUNASS, "c" * 64)}
    admitted, refused = admission.check([record()], 3072, now)
    assert admitted == {}
    assert refused == [
        f"REFUSED {BIG} {OUNASS} bytes sha256={'c' * 64}: the set's fitted peak 2387 MiB is "
        "over 75% of 3072 MiB and no admission record has this sha256"
    ]


def test_a_peak_over_75_percent_of_memory_is_refused() -> None:
    over = record(refreshPeaksMiB=[1967, 2305, 1967, 1967])
    assert admission.check([over], 3072, NOW) == (
        {},
        [
            f"REFUSED {BIG} sha256={'a' * 64}: refresh peak 2305 MiB is over 75% of 3072 MiB "
            "(2304 MiB)"
        ],
    )


def test_a_peak_at_exactly_75_percent_passes() -> None:
    at = record(refreshPeaksMiB=[2304, 1967, 1967, 1967])
    assert admission.check([at], 3072, NOW) == ({"a" * 64: FACES}, [])


def test_a_record_measured_at_another_memory_is_refused() -> None:
    _, refused = admission.check([record()], 2048, NOW)
    assert any("measured at 3072 MiB, this revision has 2048 MiB" in r for r in refused)


def test_a_record_measured_with_other_packing_is_refused() -> None:
    _, refused = admission.check([record(packContent=False)], 3072, NOW)
    assert refused == [
        f"REFUSED {BIG} sha256={'a' * 64}: measured with packContent=False, pi_api packs: True"
    ]
    assert admission.check([record(packContent=False)], 3072, NOW, pack=False)[1] == []


def test_deployed_pi_api_packs_content() -> None:
    # app_from_env passes no pack_content, so the deployed setting is SnapshotSource's default.
    assert admission.deployed_pack() is True
    assert "pack_content" not in inspect.getsource(app_from_env)


def test_others_at_the_admission_cap_are_admitted() -> None:
    others = ADMISSION_OTHERS_MAX_BYTES
    big = record(served=[served(BIG, OUNASS, "a" * 64), served(SMALL, others, "b" * 64)])
    now = {**NOW, SMALL: served(SMALL, others, "b" * 64)}
    assert admission.check([big], 3072, now) == ({"a" * 64: 50_000_000}, [])


def test_others_over_the_admission_cap_are_refused_even_when_measured() -> None:
    others = ADMISSION_OTHERS_MAX_BYTES + 1
    big = record(served=[served(BIG, OUNASS, "a" * 64), served(SMALL, others, "b" * 64)])
    now = {**NOW, SMALL: served(SMALL, others, "b" * 64)}
    _, refused = admission.check([big], 3072, now)
    assert refused == [
        f"REFUSED {BIG} sha256={'a' * 64}: the other files total {others} bytes, over 50000000"
    ]


def test_a_record_measured_with_other_files_is_refused() -> None:
    grown = {**NOW, SMALL: served(SMALL, FACES + 1, "d" * 64)}
    _, refused = admission.check([record()], 3072, grown)
    assert any(f"{SMALL} grew from {FACES} to {FACES + 1} bytes" in r for r in refused)
    extra = {**NOW, "datasets/ae/beauty/latest.json": served("x", 10, "e" * 64)}
    _, refused = admission.check([record()], 3072, extra)
    assert any("measured with" in r for r in refused)


def test_a_set_within_the_rule_needs_no_record() -> None:
    today = {"b": served("b", 17_050_000, "a" * 64), SMALL: served(SMALL, FACES, "b" * 64)}
    assert admission.check([], 1024, today) == ({}, [])


def test_the_record_names_a_file_it_served() -> None:
    with pytest.raises(ValueError, match="is not among the served files"):
        record(sha256="f" * 64)


def test_the_record_schema_is_closed() -> None:
    with pytest.raises(ValueError, match="Extra inputs"):
        record(note="hand-edited")
    with pytest.raises(ValueError, match="refreshPeaksMiB"):
        record(refreshPeaksMiB=[1967, 1967])
    with pytest.raises(ValueError, match="packContent"):
        admission.Record.model_validate(
            {k: v for k, v in record().model_dump(by_alias=True).items() if k != "packContent"}
        )


@pytest.fixture
def nothing_fits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every set over the rule, so the fixture's small files need a record."""
    monkeypatch.setattr(rule, "FIT_INTERCEPT_MIB", 10_000.0)


@pytest.mark.usefixtures("nothing_fits")
def test_measure_serves_every_file_and_writes_a_record_check_accepts(tmp_path: Path) -> None:
    dataset = served_dataset()
    small = dump_dataset(dataset, compact=True)
    (tmp_path / SMALL).parent.mkdir(parents=True)
    (tmp_path / SMALL).write_bytes(small)
    big = dump_dataset(dataset)  # indented, so larger; stored gzip as the publisher does
    (tmp_path / BIG).parent.mkdir(parents=True)
    (tmp_path / BIG).write_bytes(gzip.compress(big, mtime=0))
    datasets = f"{SMALL},{BIG}"

    rec = admission.measure(
        tmp_path, datasets, memory_mib=3072, bench_commit=COMMIT, today=date(2026, 10, 7)
    )

    assert rec.dataset == BIG
    assert rec.sha256 == admission_sha256(big)  # the decompressed body, not the gzip object
    assert rec.pack_content is True
    assert {s.path for s in rec.served} == {BIG, SMALL}
    assert rec.others_bytes == len(small)
    assert len(rec.refresh_peaks_mib) == admission.REFRESHES
    assert rec.cold_start_peak_mib >= rec.baseline_mib
    out = tmp_path / "admission"
    out.mkdir()
    (out / "ounass_ae.json").write_text(admission.dump(rec), encoding="utf-8")
    assert json.loads((out / "ounass_ae.json").read_text())["schema"] == "pi.admission/v1"
    now = admission.served(tmp_path, admission.served_paths(datasets))
    assert admission.check(admission.load_records(out), 3072, now) == (
        {rec.sha256: len(small)},
        [],
    )


def test_measure_refuses_when_the_set_is_within_the_rule(tmp_path: Path) -> None:
    write(tmp_path, served_dataset(), SMALL)
    with pytest.raises(SystemExit, match="within the rule"):
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


@pytest.mark.usefixtures("nothing_fits")
def test_the_check_command_stops_on_an_unadmitted_body(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, served_dataset(), SMALL)
    records = tmp_path / "admission"
    records.mkdir()
    args = ["check", "--root", str(tmp_path), "--datasets", SMALL, "--memory-mib", "3072"]
    assert admission.main([*args, "--admission-dir", str(records)]) == 1
    captured = capsys.readouterr()
    assert captured.out == "ADMISSION STOP\n"
    assert "no admission record has this sha256" in captured.err


#: pi-api as step F leaves it (the f3gi revision, 2026-10-07; before it: 1Gi, 3 and 20), cut to
#: what is checked.
LIVE: dict[str, Any] = {
    "metadata": {
        "name": "pi-api",
        "labels": {"cloud.googleapis.com/location": "me-central1"},
        "annotations": {"run.googleapis.com/maxScale": "1"},
    },
    "spec": {
        "template": {
            "metadata": {
                "annotations": {
                    "autoscaling.knative.dev/maxScale": "1",
                    "autoscaling.knative.dev/minScale": "0",
                }
            },
            "spec": {
                "containerConcurrency": 80,
                "containers": [{"resources": {"limits": {"cpu": "1", "memory": "3Gi"}}}],
            },
        }
    },
}


def live(**changes: str | None) -> str:
    doc = copy.deepcopy(LIVE)
    service_level = doc["metadata"]["annotations"]
    template = doc["spec"]["template"]
    for key, value in changes.items():
        target, name = {
            "service": (service_level, "run.googleapis.com/maxScale"),
            "revision": (template["metadata"]["annotations"], "autoscaling.knative.dev/maxScale"),
            "memory": (template["spec"]["containers"][0]["resources"]["limits"], "memory"),
        }[key]
        if value is None:
            del target[name]
        else:
            target[name] = value
    return json.dumps(doc)


def test_the_service_env_matches_the_live_service(capsys: pytest.CaptureFixture[str]) -> None:
    assert admission.main(["service"], stdin=lambda: json.dumps(LIVE)) == 0
    assert capsys.readouterr().out == (
        "ok: PI_API_REGION live=[me-central1] service.env=[me-central1]\n"
        "ok: PI_API_MEMORY_MIB live=[3Gi] service.env=[3072]\n"
        "ok: PI_API_MAX_SCALE_REVISION live=[1] service.env=[1]\n"
        "ok: PI_API_MAX_SCALE_SERVICE live=[1] service.env=[1]\n"
        "SERVICE OK\n"
    )
    env = admission.read_env(admission.SERVICE_ENV)
    assert min(int(env["PI_API_MAX_SCALE_REVISION"]), int(env["PI_API_MAX_SCALE_SERVICE"])) == 1


def stops(describe: str) -> list[str]:
    env = admission.read_env(admission.SERVICE_ENV)
    return [line for line in admission.service(describe, env) if line.startswith("STOP")]


def test_any_difference_from_service_env_stops() -> None:
    assert stops(live(service="20")) == ["STOP: PI_API_MAX_SCALE_SERVICE live=[20] service.env=[1]"]
    assert stops(live(service=None)) == [
        "STOP: PI_API_MAX_SCALE_SERVICE live=[] service.env=[1]: missing"
    ]
    assert stops(live(revision="3")) == ["STOP: PI_API_MAX_SCALE_REVISION live=[3] service.env=[1]"]
    assert stops(live(memory="1Gi")) == ["STOP: PI_API_MEMORY_MIB live=[1Gi] service.env=[3072]"]
    assert stops(live(memory="lots")) == [
        "STOP: PI_API_MEMORY_MIB live=[lots] service.env=[3072]: memory limit 'lots' is not "
        "<n>Gi, <n>Mi, <n>G or <n>M"
    ]
    assert stops(live(memory="3072Mi")) == []


@pytest.mark.parametrize("describe", ["", "{}", "null", "not json"])
def test_an_empty_describe_stops(describe: str) -> None:
    assert stops(describe) == [
        "STOP: the describe is empty or not JSON (region and project explicit?)"
    ]


def test_memory_limits_are_normalised_to_mib() -> None:
    assert admission.quantity_mib("1Gi") == admission.quantity_mib("1024Mi") == 1024
    assert admission.quantity_mib("3Gi") == 3072
    assert admission.quantity_mib("1G") == Fraction(10**9, 2**20)
    assert admission.quantity_mib("512M") == Fraction(512 * 10**6, 2**20)


def test_service_env_reads_key_value_lines(tmp_path: Path) -> None:
    env = tmp_path / "service.env"
    env.write_text("# comment\n\nA=1\n B = x \n", encoding="utf-8")
    assert admission.read_env(env) == {"A": "1", "B": "x"}
    env.write_text("A\n", encoding="utf-8")
    with pytest.raises(ValueError, match="is not KEY=value"):
        admission.read_env(env)


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


def test_a_path_shared_by_two_sources_counts_once_in_the_others() -> None:
    beauty, faces = "datasets/ae/beauty/latest.json", "datasets/ae/faces_ae/latest.json"
    live = f"sephora_me={beauty},ulta_ae={beauty},faces_ae={faces}"
    assert admission.served_paths(live) == (beauty, faces)  # as SnapshotSource.load_all
