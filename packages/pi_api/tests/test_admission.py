"""pi_api loads under the memory rule (pi-api-deploy.md §6), live at every load: a new generation
that would break it at ``PI_API_MEMORY_MIB`` keeps the last good one, a refused path at cold start
is unavailable while the others serve, and an admission record is keyed on the decompressed sha.

Sizes are scaled: ``MB`` is patched to 20 kB and bodies are padded (trailing whitespace is valid
JSON) to exact sizes, so the rule's real constants decide at today's real file sizes in MB."""

from __future__ import annotations

import gzip
import logging
import os
from collections import Counter
from pathlib import Path

import pytest

from api_fixture import DATASET_PATH, make_client, served_dataset
from pi_api.config import Settings, admitted_entries, memory_mib
from pi_api.source import LocalStore, SnapshotSource
from pi_dataset import admission_sha256, dump_dataset
from pi_dataset import gate as rule

UNIT = 20_000
COMPACT = dump_dataset(served_dataset(), compact=True)
OTHER = "datasets/ae/faces/latest.json"
ENV = {"PI_API_DATASETS": DATASET_PATH, "PI_API_LOCAL_DIR": ".", "PI_API_FIREBASE_PROJECT": "p"}


@pytest.fixture(autouse=True)
def scaled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rule, "MB", UNIT)


def sized(mb: float) -> bytes:
    size = int(mb * UNIT)
    assert size >= len(COMPACT)
    return COMPACT + b" " * (size - len(COMPACT))


def publish(root: Path, data: bytes, mtime: int, path: str = DATASET_PATH) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    os.utime(target, ns=(mtime, mtime))


def generations(source: SnapshotSource) -> dict[str, str]:
    return {d.path: d.generation for d in source.datasets()}


@pytest.mark.parametrize(("memory_mib", "served"), [(1024, False), (2048, True), (3072, True)])
def test_the_rule_follows_the_memory(tmp_path: Path, memory_mib: int, served: bool) -> None:
    publish(tmp_path, sized(25), 1)
    _, source = make_client(tmp_path, memory_mib=memory_mib)
    assert generations(source) == ({DATASET_PATH: "1"} if served else {})


def test_beauty_growing_to_25_mb_on_1gi_stays_on_the_last_good_generation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    publish(tmp_path, sized(17.05), 1)
    publish(tmp_path, sized(1.4), 1, OTHER)
    _, source = make_client(tmp_path, paths=(DATASET_PATH, OTHER), memory_mib=1024)
    assert generations(source) == {DATASET_PATH: "1", OTHER: "1"}
    publish(tmp_path, sized(25), 2)
    with caplog.at_level(logging.ERROR, "pi_api.source"):
        source.load_all()
    assert generations(source) == {DATASET_PATH: "1", OTHER: "1"}
    assert f"MEMORY RULE: dataset {DATASET_PATH} generation 2 REFUSED, kept at 1" in caplog.text
    publish(tmp_path, sized(20), 3)  # back within the rule: loads at the next check
    source.load_all()
    assert generations(source)[DATASET_PATH] == "3"


def test_17_mb_beside_10_mb_of_others_is_refused_at_1gi_and_the_others_serve(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    publish(tmp_path, sized(10), 1, OTHER)
    publish(tmp_path, sized(17), 1)
    with caplog.at_level(logging.ERROR, "pi_api.source"):
        _, source = make_client(tmp_path, paths=(OTHER, DATASET_PATH), memory_mib=1024)
    assert generations(source) == {OTHER: "1"}  # cold start: never loaded, never crashed
    assert f"dataset {DATASET_PATH} generation 1 REFUSED, UNAVAILABLE: 806 MiB" in caplog.text


class CountingStore(LocalStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.reads: Counter[str] = Counter()

    def read(self, path: str) -> tuple[bytes, str]:
        self.reads[path] += 1
        return super().read(path)


def test_a_path_shared_by_two_sources_is_parsed_and_counted_once(tmp_path: Path) -> None:
    # Live: sephora_me and ulta_ae both read beauty. Once, 17.05 + 1.4 MB is 635 MiB, within
    # 1Gi; counted per source it would be 976 MiB and refused.
    publish(tmp_path, sized(17.05), 1)
    publish(tmp_path, sized(1.4), 1, OTHER)
    store = CountingStore(tmp_path)
    shared = {"sephora_me": DATASET_PATH, "ulta_ae": DATASET_PATH, "faces_ae": OTHER}
    source = SnapshotSource(store, (), assigned=shared, memory_mib=1024)
    source.load_all()
    assert store.reads == {DATASET_PATH: 1, OTHER: 1}
    assert source._bodies.keys() == {DATASET_PATH, OTHER}
    assert rule.refusal(source._bodies, {}, 1024) is None
    assert round(rule.peak_mib(s for s, _ in source._bodies.values())) == 635


def test_cold_start_does_not_depend_on_path_order(tmp_path: Path) -> None:
    # Alone, 25 MB breaks 1Gi; beside an admitted 40 MB file whose record measured 30 MB of
    # others, it is within that record. Listed first, it is refused, then taken on the retry.
    big = sized(40)
    publish(tmp_path, sized(25), 1)
    publish(tmp_path, big, 1, OTHER)
    admitted = {admission_sha256(big): 30 * UNIT}
    _, source = make_client(
        tmp_path, paths=(DATASET_PATH, OTHER), memory_mib=1024, admitted=admitted
    )
    assert generations(source) == {DATASET_PATH: "1", OTHER: "1"}


def test_the_admission_is_of_the_decompressed_body_not_the_gzip_object(tmp_path: Path) -> None:
    body = sized(25)
    stored = gzip.compress(body, mtime=0)
    publish(tmp_path, stored, 1)
    _, source = make_client(tmp_path, memory_mib=1024, admitted={admission_sha256(stored): 0})
    assert generations(source) == {}
    _, source = make_client(tmp_path, memory_mib=1024, admitted={admission_sha256(body): 0})
    assert generations(source) == {DATASET_PATH: "1"}


def test_the_memory_is_read_from_the_environment_and_fails_closed_to_1gi(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert Settings.from_env({**ENV, "PI_API_MEMORY_MIB": "3072"}).memory_mib == 3072
    with caplog.at_level(logging.ERROR, "pi_api.config"):
        assert Settings.from_env(ENV).memory_mib == 1024
        assert "PI_API_MEMORY_MIB is None: assuming 1024 MiB" in caplog.text
        assert memory_mib("3Gi") == 1024
        assert memory_mib("0") == 1024
    assert "PI_API_MEMORY_MIB is '3Gi': assuming 1024 MiB" in caplog.text


def test_admitted_entries_come_from_the_environment() -> None:
    sha = admission_sha256(b"x")
    assert admitted_entries("") == {}
    assert admitted_entries(f" {sha}:1400000 ,") == {sha: 1_400_000}
    for bad in (sha, sha.upper() + ":1", f"{sha}:-1"):
        with pytest.raises(ValueError, match="is not sha256:others_bytes"):
            admitted_entries(bad)
    assert Settings.from_env(ENV).admitted == {}
    assert Settings.from_env({**ENV, "PI_API_ADMITTED": f"{sha}:0"}).admitted == {sha: 0}
