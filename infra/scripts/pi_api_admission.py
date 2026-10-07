#!/usr/bin/env python3
"""pi_api's memory rule at deploy: measured admission records and the live-service check
(docs/runbooks/pi-api-deploy.md §6).

pi_api loads a set of files only while the fitted peak (``pi_dataset.gate``) is within 75% of
``PI_API_MEMORY_MIB``. A set over the fit is served only on a record in
``infra/pi-api/admission/`` for its largest body: the sha256 of the decompressed ``latest.json``
pi_api parses (never the gzip object, never the exporter's file), measured with every
``PI_API_DATASETS`` file resident together the way pi_api serves them: a cold start, then four
refreshes of the largest file, RSS sampled every 20 ms, content packed as deployed. It passes only
if the highest refresh peak is at most 75% of the memory and the other files total at most
``OTHERS_MAX_BYTES``. A new export is a new sha: nothing carries over, it is measured again.

``measure`` writes a record. ``check`` (the deploy) refuses unless the served set is within the
fit or its largest body has a passing record measured at this memory with these files, and prints
the ``PI_API_ADMITTED`` value (``sha256:others_bytes``) to bake into the revision; pi_api enforces
the same rule at every load. ``service`` compares the live service (``gcloud run services describe
--format=json`` on stdin) with ``infra/pi-api/service.env`` and STOPs on any difference.

    pi_api_admission.py measure --root DIR --datasets "$DATASETS" --memory-mib 3072 \
        --bench-commit "$(git rev-parse HEAD)" --out infra/pi-api/admission/ounass_ae.json
    pi_api_admission.py check --root DIR --datasets "$DATASETS" --memory-mib 3072
    gcloud run services describe pi-api ... --format=json | pi_api_admission.py service

``--root`` holds a copy of each served object at its bucket path (stored gzip or plain).
"""

from __future__ import annotations

import argparse
import gzip
import inspect
import json
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pi_api.config import dataset_entries
from pi_api.source import LocalStore, SnapshotSource
from pi_dataset import admission_sha256
from pi_dataset import gate as rule

SCHEMA = "pi.admission/v1"
ADMISSION_DIR = Path(__file__).resolve().parents[1] / "pi-api" / "admission"
SERVICE_ENV = Path(__file__).resolve().parents[1] / "pi-api" / "service.env"
REFRESHES = 4
_SHA256 = r"^[0-9a-f]{64}$"


def deployed_pack() -> bool:
    """Whether deployed pi_api packs offer content: ``SnapshotSource``'s default, since
    ``app_from_env`` passes no ``pack_content``."""
    default = inspect.signature(SnapshotSource).parameters["pack_content"].default
    return default is True


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
    #: Whether offer content was packed in memory, as ``SnapshotSource(pack_content=...)``.
    pack_content: bool = Field(alias="packContent")
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
        return int(rule.limit_mib(self.memory_mib))

    @property
    def others_bytes(self) -> int:
        """The other files' total: the bound pi_api holds them to (``PI_API_ADMITTED``)."""
        return sum(s.bytes for s in self.served) - self.bytes


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


def fits(now: Mapping[str, Served], memory_mib: int) -> bool:
    return rule.fits((s.bytes for s in now.values()), memory_mib)


def problems(
    record: Record, memory_mib: int, now: Mapping[str, Served], pack: bool | None = None
) -> list[str]:
    """Why ``record`` does not admit its dataset into this revision; empty when it does."""
    pack = deployed_pack() if pack is None else pack
    out = []
    if record.memory_mib != memory_mib:
        out.append(f"measured at {record.memory_mib} MiB, this revision has {memory_mib} MiB")
    if record.pack_content != pack:
        out.append(f"measured with packContent={record.pack_content}, pi_api packs: {pack}")
    if record.peak_mib > record.limit_mib:
        out.append(
            f"refresh peak {record.peak_mib} MiB is over 75% of {record.memory_mib} MiB "
            f"({record.limit_mib} MiB)"
        )
    if record.others_bytes > rule.OTHERS_MAX_BYTES:
        out.append(
            f"the other files total {record.others_bytes} bytes, over {rule.OTHERS_MAX_BYTES}"
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
    return out


def check(
    records: Sequence[Record], memory_mib: int, now: Mapping[str, Served], pack: bool | None = None
) -> tuple[dict[str, int], list[str]]:
    """The ``PI_API_ADMITTED`` entries (sha256: others' bytes) for the served files ``now``, and
    why the set is refused. A set within the fit needs no record."""
    if fits(now, memory_mib):
        return {}, []
    file = max(now.values(), key=lambda s: (s.bytes, s.path))
    peak = rule.peak_mib(s.bytes for s in now.values())
    matching = [r for r in records if r.dataset == file.path and r.sha256 == file.sha256]
    if not matching:
        return {}, [
            f"REFUSED {file.path} {file.bytes} bytes sha256={file.sha256}: the set's fitted "
            f"peak {peak:.0f} MiB is over 75% of {memory_mib} MiB and no admission record has "
            "this sha256"
        ]
    for r in matching:
        if not problems(r, memory_mib, now, pack):
            return {file.sha256: r.others_bytes}, []
    why = [p for r in matching for p in problems(r, memory_mib, now, pack)]
    return {}, [f"REFUSED {file.path} sha256={file.sha256}: {p}" for p in why]


def load_records(directory: Path) -> list[Record]:
    return [Record.model_validate_json(p.read_bytes()) for p in sorted(directory.glob("*.json"))]


_QUANTITY = re.compile(r"^([0-9]+)(Gi|Mi|G|M)$")
_UNIT = {
    "Gi": Fraction(1024),
    "Mi": Fraction(1),
    "G": Fraction(10**9, 2**20),
    "M": Fraction(10**6, 2**20),
}


def quantity_mib(value: str) -> Fraction:
    """A Cloud Run memory limit in MiB: ``1Gi`` and ``1024Mi`` are both 1024."""
    match = _QUANTITY.fullmatch(value)
    if match is None:
        msg = f"memory limit {value!r} is not <n>Gi, <n>Mi, <n>G or <n>M"
        raise ValueError(msg)
    return int(match[1]) * _UNIT[match[2]]


def read_env(path: Path) -> dict[str, str]:
    """``KEY=value`` lines of a sourced shell file; ``#`` comments and blank lines skipped."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, sep, value = line.partition("=")
            if not sep:
                msg = f"{path}: {line!r} is not KEY=value"
                raise ValueError(msg)
            out[key.strip()] = value.strip()
    return out


def _dig(doc: Any, *keys: str | int) -> str | None:
    for key in keys:
        try:
            doc = doc[key]
        except (KeyError, IndexError, TypeError):
            return None
    return doc if isinstance(doc, str) else None


def service(describe: str, env: Mapping[str, str]) -> list[str]:
    """Each live value beside its ``service.env`` entry, ``ok`` or ``STOP``. An empty or
    unreadable describe, or a missing value, is a STOP: never a pass."""
    try:
        doc = json.loads(describe)
    except json.JSONDecodeError:
        doc = None
    if not isinstance(doc, dict) or not doc:
        return ["STOP: the describe is empty or not JSON (region and project explicit?)"]
    template = ("spec", "template")
    live = {
        "PI_API_REGION": _dig(doc, "metadata", "labels", "cloud.googleapis.com/location"),
        "PI_API_MEMORY_MIB": _dig(
            doc, *template, "spec", "containers", 0, "resources", "limits", "memory"
        ),
        "PI_API_MAX_SCALE_REVISION": _dig(
            doc, *template, "metadata", "annotations", "autoscaling.knative.dev/maxScale"
        ),
        "PI_API_MAX_SCALE_SERVICE": _dig(
            doc, "metadata", "annotations", "run.googleapis.com/maxScale"
        ),
    }
    out = []
    for key, have in live.items():
        want = env.get(key)
        shown = f"{key} live=[{have if have is not None else ''}] service.env=[{want or ''}]"
        if have is None or not want:
            out.append(f"STOP: {shown}: missing")
            continue
        try:
            same = quantity_mib(have) == int(want) if key == "PI_API_MEMORY_MIB" else have == want
        except ValueError as error:
            out.append(f"STOP: {shown}: {error}")
            continue
        out.append(f"{'ok' if same else 'STOP'}: {shown}")
    return out


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
    pack: bool | None = None,
) -> Record:
    """Serve ``datasets`` from ``root`` as pi_api does, then refresh the largest file
    ``REFRESHES`` times, and record the peaks."""
    pack = deployed_pack() if pack is None else pack
    files = served(root, served_paths(datasets))
    if fits(files, memory_mib):
        msg = f"the files are within the rule at {memory_mib} MiB: no record needed"
        raise SystemExit(msg)
    largest = max(files.values(), key=lambda s: (s.bytes, s.path))
    others = sum(s.bytes for s in files.values()) - largest.bytes
    whole, sources = dataset_entries(datasets)
    baseline = rss_mib()
    peak = Peak()
    source = SnapshotSource(
        LocalStore(str(root)),
        whole,
        refresh_seconds=3600,
        assigned=sources,
        pack_content=pack,
        admitted={largest.sha256: others},
        memory_mib=memory_mib,
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
            "packContent": pack,
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
    sub.add_parser("service").add_argument("--env", type=Path, default=SERVICE_ENV)
    return result


def main(argv: Sequence[str] | None = None, stdin: Callable[[], str] = sys.stdin.read) -> int:
    args = parser().parse_args(argv)
    if args.command == "service":
        lines = service(stdin(), read_env(args.env))
        print("\n".join(lines))
        stop = any(line.startswith("STOP") for line in lines)
        print("SERVICE STOP" if stop else "SERVICE OK")
        return 1 if stop else 0
    if args.command == "measure":
        record = measure(
            args.root,
            args.datasets,
            memory_mib=args.memory_mib,
            bench_commit=args.bench_commit,
            today=datetime.now(UTC).date(),
        )
        args.out.write_text(dump(record), encoding="utf-8")
        verdict = (
            "PASS"
            if not problems(record, record.memory_mib, {s.path: s for s in record.served})
            else "FAIL"
        )
        print(
            f"{verdict} {record.dataset} sha256={record.sha256} bytes={record.bytes} "
            f"cold={record.cold_start_peak_mib} refreshes={list(record.refresh_peaks_mib)} MiB, "
            f"limit {record.limit_mib} of {record.memory_mib} MiB; wrote {args.out}"
        )
        return 0 if verdict == "PASS" else 1
    now = served(args.root, served_paths(args.datasets))
    admitted, refused = check(load_records(args.admission_dir), args.memory_mib, now)
    for line in refused:
        print(line, file=sys.stderr)
    if refused:
        print("ADMISSION STOP")
        return 1
    print(f"PI_API_ADMITTED={','.join(f'{k}:{v}' for k, v in sorted(admitted.items()))}")
    print("ADMISSION OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
