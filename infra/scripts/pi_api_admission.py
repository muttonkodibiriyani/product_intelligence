#!/usr/bin/env python3
"""Measured admission of a pi_api dataset over ``V3_MAX_BYTES`` (docs/runbooks/pi-api-deploy.md §6).

A dataset body over the gate is served only on a record in ``infra/pi-api/admission/`` for its
exact bytes: the sha256 of the decompressed ``latest.json`` that pi_api parses (never the gzip
object, never the exporter's file). The record is measured with every ``PI_API_DATASETS`` file
resident together, the way pi_api serves them: a cold start, then four refreshes of the largest
file, RSS sampled every 20 ms. It passes only if the highest refresh peak is at most 75% of the
instance memory. A new export is a new sha: nothing carries over, it is measured again.

``measure`` writes a record; ``check`` (the deploy, step F) refuses unless every served body over
the gate has a passing record, measured at this memory with these files, and prints the
``PI_API_ADMITTED`` value to bake into the revision. pi_api enforces the same set at load.

    pi_api_admission.py measure --root DIR --datasets "$DATASETS" --memory-mib 3072 \
        --bench-commit "$(git rev-parse HEAD)" --out infra/pi-api/admission/ounass_ae.json
    pi_api_admission.py check --root DIR --datasets "$DATASETS" --memory-mib 3072

``--root`` holds a copy of each served object at its bucket path (stored gzip or plain).
"""

from __future__ import annotations

import argparse
import gzip
import os
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pi_api.config import dataset_entries
from pi_api.source import LocalStore, SnapshotSource
from pi_dataset import V3_MAX_BYTES, admission_sha256

SCHEMA = "pi.admission/v1"
ADMISSION_DIR = Path(__file__).resolve().parents[1] / "pi-api" / "admission"
#: The highest refresh peak may use this share of the instance memory (Coordinator, 2026-10-07).
SHARE = 0.75
REFRESHES = 4
_SHA256 = r"^[0-9a-f]{64}$"


class Served(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str
    bytes: int = Field(ge=0)
    sha256: str = Field(pattern=_SHA256)


class Record(BaseModel):
    """One measurement of one exact body, with every file served beside it."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    schema_: Literal["pi.admission/v1"] = Field(alias="schema")
    #: The admitted file (the largest served) and its decompressed body's sha256 and size.
    dataset: str
    sha256: str = Field(pattern=_SHA256)
    bytes: int = Field(gt=0)
    memory_mib: int = Field(alias="memoryMiB", gt=0)
    #: Every file resident during the measurement, the admitted one included.
    served: tuple[Served, ...] = Field(min_length=1)
    baseline_mib: int = Field(alias="baselineMiB", ge=0)
    cold_start_peak_mib: int = Field(alias="coldStartPeakMiB", gt=0)
    refresh_peaks_mib: tuple[int, int, int, int] = Field(alias="refreshPeaksMiB")
    measured_on: date = Field(alias="measuredOn")
    bench_commit: str = Field(alias="benchCommit", pattern=r"^[0-9a-f]{40}$")

    @model_validator(mode="after")
    def _admitted_is_served(self) -> Self:
        if Served(path=self.dataset, bytes=self.bytes, sha256=self.sha256) not in self.served:
            msg = f"{self.dataset} with sha256={self.sha256} is not among the served files"
            raise ValueError(msg)
        return self

    @property
    def peak_mib(self) -> int:
        return max(self.refresh_peaks_mib)

    @property
    def limit_mib(self) -> int:
        return int(self.memory_mib * SHARE)


def body(root: Path, path: str) -> bytes:
    """The object's body as pi_api parses it: gunzipped when stored gzip."""
    data = (root / path).read_bytes()
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def served_paths(datasets: str) -> tuple[str, ...]:
    """Every object ``PI_API_DATASETS`` serves, whole or per source, once each."""
    whole, sources = dataset_entries(datasets)
    return tuple(sorted({*whole, *sources.values()}))


def served(root: Path, paths: Sequence[str]) -> dict[str, Served]:
    out = {}
    for path in paths:
        data = body(root, path)
        out[path] = Served(path=path, bytes=len(data), sha256=admission_sha256(data))
    return out


def problems(
    record: Record, memory_mib: int, now: Mapping[str, Served], gate: int = V3_MAX_BYTES
) -> list[str]:
    """Why ``record`` does not admit its dataset into this revision; empty when it does."""
    out = []
    if record.memory_mib != memory_mib:
        out.append(f"measured at {record.memory_mib} MiB, this revision has {memory_mib} MiB")
    if record.peak_mib > record.limit_mib:
        out.append(
            f"refresh peak {record.peak_mib} MiB is over 75% of {record.memory_mib} MiB "
            f"({record.limit_mib} MiB)"
        )
    if {s.path for s in record.served} != set(now):
        out.append(f"measured with {sorted(s.path for s in record.served)}, serving {sorted(now)}")
    for then in record.served:
        current = now.get(then.path)
        if then.path != record.dataset and current is not None and current.bytes > then.bytes:
            out.append(f"{then.path} grew from {then.bytes} to {current.bytes} bytes")
    largest = max(now.values(), key=lambda s: s.bytes)
    if largest.path != record.dataset:
        out.append(f"{largest.path} is now the largest file, not {record.dataset}")
    if record.bytes <= gate:
        out.append(f"{record.bytes} bytes is within the gate: no record needed")
    return out


def check(
    records: Sequence[Record], memory_mib: int, now: Mapping[str, Served], gate: int = V3_MAX_BYTES
) -> tuple[frozenset[str], list[str]]:
    """The ``PI_API_ADMITTED`` set for the served files ``now``, and why any is refused."""
    admitted: set[str] = set()
    refused = []
    for file in sorted(now.values(), key=lambda s: s.path):
        if file.bytes <= gate:
            continue
        matching = [r for r in records if r.dataset == file.path and r.sha256 == file.sha256]
        if not matching:
            refused.append(
                f"REFUSED {file.path} {file.bytes} bytes sha256={file.sha256}: over the "
                f"{gate}-byte gate and no admission record has this sha256"
            )
            continue
        why = [p for r in matching for p in problems(r, memory_mib, now, gate)]
        if any(not problems(r, memory_mib, now, gate) for r in matching):
            admitted.add(file.sha256)
        else:
            refused.extend(f"REFUSED {file.path} sha256={file.sha256}: {p}" for p in why)
    return frozenset(admitted), refused


def load_records(directory: Path) -> list[Record]:
    return [Record.model_validate_json(p.read_bytes()) for p in sorted(directory.glob("*.json"))]


def rss_mib() -> int:
    """Resident set size of this process (Linux ``/proc``)."""
    pages = int(Path("/proc/self/statm").read_text(encoding="ascii").split()[1])
    return pages * os.sysconf("SC_PAGE_SIZE") // 2**20


class Peak:
    """The highest RSS since ``reset``, sampled every 20 ms in a background thread."""

    def __init__(self, sample: Callable[[], int] = rss_mib) -> None:
        self._sample = sample
        self.value = sample()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(0.02):
            self.value = max(self.value, self._sample())

    def reset(self) -> None:
        self.value = self._sample()

    def stop(self) -> int:
        self._stop.set()
        self._thread.join()
        return max(self.value, self._sample())


def measure(  # noqa: PLR0913 - the measurement's inputs, keyword-only
    root: Path,
    datasets: str,
    *,
    memory_mib: int,
    bench_commit: str,
    today: date,
    gate: int = V3_MAX_BYTES,
) -> Record:
    """Serve ``datasets`` from ``root`` as pi_api does, then refresh the largest file
    ``REFRESHES`` times, and record the peaks."""
    files = served(root, served_paths(datasets))
    largest = max(files.values(), key=lambda s: s.bytes)
    if largest.bytes <= gate:
        msg = f"the largest file, {largest.path}, is {largest.bytes} bytes: within the gate"
        raise SystemExit(msg)
    whole, sources = dataset_entries(datasets)
    baseline = rss_mib()
    peak = Peak()
    source = SnapshotSource(
        LocalStore(str(root)),
        whole,
        refresh_seconds=3600,
        assigned=sources,
        admitted=frozenset({largest.sha256}),
        gate=gate,
    )
    source.load_all()
    if len(source.datasets()) == 0:
        msg = "nothing loaded: check the files and DATASETS"
        raise SystemExit(msg)
    cold = peak.value
    refreshes = []
    target = root / largest.path
    for i in range(REFRESHES):
        peak.reset()
        stamp = time.time_ns() + i
        os.utime(target, ns=(stamp, stamp))
        source.load_all()
        refreshes.append(peak.value)
    peak.stop()
    return Record.model_validate(
        {
            "schema": SCHEMA,
            "dataset": largest.path,
            "sha256": largest.sha256,
            "bytes": largest.bytes,
            "memoryMiB": memory_mib,
            "served": [s.model_dump() for s in files.values()],
            "baselineMiB": baseline,
            "coldStartPeakMiB": cold,
            "refreshPeaksMiB": refreshes,
            "measuredOn": today,
            "benchCommit": bench_commit,
        }
    )


def dump(record: Record) -> str:
    return record.model_dump_json(by_alias=True, indent=2) + "\n"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("measure", "check"):
        command = sub.add_parser(name)
        command.add_argument("--root", type=Path, required=True)
        command.add_argument("--datasets", required=True, help="the revision's PI_API_DATASETS")
        command.add_argument("--memory-mib", type=int, required=True)
    sub.choices["measure"].add_argument("--bench-commit", required=True)
    sub.choices["measure"].add_argument("--out", type=Path, required=True)
    sub.choices["check"].add_argument("--admission-dir", type=Path, default=ADMISSION_DIR)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "measure":
        record = measure(
            args.root,
            args.datasets,
            memory_mib=args.memory_mib,
            bench_commit=args.bench_commit,
            today=datetime.now(UTC).date(),
        )
        args.out.write_text(dump(record), encoding="utf-8")
        verdict = "PASS" if record.peak_mib <= record.limit_mib else "FAIL"
        print(
            f"{verdict} {record.dataset} sha256={record.sha256} bytes={record.bytes} "
            f"cold={record.cold_start_peak_mib} refreshes={list(record.refresh_peaks_mib)} MiB, "
            f"limit {record.limit_mib} of {record.memory_mib} MiB; wrote {args.out}"
        )
        return 0 if verdict == "PASS" else 1
    now = served(args.root, served_paths(args.datasets))
    admitted, refused = check(
        load_records(args.admission_dir), args.memory_mib, now, gate=V3_MAX_BYTES
    )
    for line in refused:
        print(line, file=sys.stderr)
    if refused:
        print("ADMISSION STOP")
        return 1
    print(f"PI_API_ADMITTED={','.join(sorted(admitted))}")
    print("ADMISSION OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
