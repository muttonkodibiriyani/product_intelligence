"""Over-gate bodies load only on an admission record (pi-api-deploy.md §6): a refused new
generation keeps the last good one live, and the sha is of the decompressed body pi_api parses."""

from __future__ import annotations

import gzip
import os
from pathlib import Path

import pytest

from api_fixture import DATASET_PATH, make_client, served_dataset
from pi_api.config import Settings, admitted_shas
from pi_api.source import NotAdmittedError, SnapshotSource, admitted_body
from pi_dataset import V3_MAX_BYTES, admission_sha256, dump_dataset

COMPACT = dump_dataset(served_dataset(), compact=True)
#: The same dataset indented: a different, larger body for the next generation.
LARGER = dump_dataset(served_dataset())
GATE = len(COMPACT)


def publish(root: Path, data: bytes, mtime: int) -> None:
    target = root / DATASET_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    os.utime(target, ns=(mtime, mtime))


def generation(source: SnapshotSource) -> str:
    (served,) = source.datasets()
    return served.generation


def test_an_unadmitted_over_gate_generation_is_not_swapped_in(tmp_path: Path) -> None:
    publish(tmp_path, COMPACT, 1)
    _, source = make_client(tmp_path, gate=GATE)
    assert generation(source) == "1"  # at the gate: served without a record
    publish(tmp_path, LARGER, 2)
    source.load_all()
    assert generation(source) == "1"  # refused: the previous view stays live


def test_an_over_gate_body_loads_on_its_admitted_sha(tmp_path: Path) -> None:
    publish(tmp_path, LARGER, 1)
    _, source = make_client(tmp_path, gate=GATE, admitted=frozenset({admission_sha256(LARGER)}))
    assert generation(source) == "1"


def test_the_sha_is_of_the_decompressed_body_not_the_gzip_object(tmp_path: Path) -> None:
    stored = gzip.compress(LARGER, mtime=0)
    publish(tmp_path, stored, 1)
    _, source = make_client(tmp_path, gate=GATE, admitted=frozenset({admission_sha256(stored)}))
    assert source.datasets() == ()
    _, source = make_client(tmp_path, gate=GATE, admitted=frozenset({admission_sha256(LARGER)}))
    assert generation(source) == "1"


def test_with_no_good_generation_an_unadmitted_body_is_unavailable(tmp_path: Path) -> None:
    publish(tmp_path, LARGER, 1)
    _, source = make_client(tmp_path, gate=GATE)
    assert source.datasets() == ()


def test_the_default_gate_is_the_shared_constant() -> None:
    at_gate = b" " * V3_MAX_BYTES
    assert admitted_body(gzip.compress(at_gate, mtime=0), frozenset()) == at_gate
    over = at_gate + b" "
    del at_gate
    with pytest.raises(NotAdmittedError, match=f"over the {V3_MAX_BYTES}-byte gate"):
        admitted_body(over, frozenset())
    assert admitted_body(over, frozenset({admission_sha256(over)})) is over


def test_admitted_shas_come_from_the_environment() -> None:
    sha = admission_sha256(b"x")
    assert admitted_shas("") == frozenset()
    assert admitted_shas(f" {sha} ,") == frozenset({sha})
    with pytest.raises(ValueError, match="not lowercase sha256"):
        admitted_shas(sha.upper())
    env = {"PI_API_DATASETS": DATASET_PATH, "PI_API_LOCAL_DIR": ".", "PI_API_FIREBASE_PROJECT": "p"}
    assert Settings.from_env(env).admitted == frozenset()
    assert Settings.from_env({**env, "PI_API_ADMITTED": sha}).admitted == frozenset({sha})
