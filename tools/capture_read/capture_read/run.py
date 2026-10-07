"""Turn a page_capture run's saved pages into pi_capture readings, inside the bucket's region.

Reads ``<SRC_PREFIX>/pages/*.jsonl.gz`` (the page rows a capture run wrote), opens each saved
page body, checks it against the sha256 its row recorded, runs the reader for the row's retailer
and writes one ``ProductCapture`` JSON line per product row. Nothing here fetches a retailer:
every byte read comes from our own bucket.

Output, under ``<SRC_PREFIX>/<OUT>/``:

- ``<part>`` — one readings file per input page-row part, written only when the whole part has
  been read, so an interrupted run resumes by skipping parts already present. New parts that a
  still-running capture adds later are picked up by the next run.
- ``errors/<part>`` — one JSON line per page that produced no readings, with its reason
  (hash mismatch, not a product page, a product outside the reader's scope such as a
  non-beauty Ounass page, reader error). Written only when there is one.
- ``status.t<N>.json`` — this task's counts.

Parts are split across Cloud Run tasks by a stable hash of their name, so the split does not
change as a capture adds parts.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
import zlib
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from pi_capture.bloomingdales import LOOKED_FOR as BLOOMINGDALES_LOOKED_FOR
from pi_capture.bloomingdales import readings_from_bloomingdales
from pi_capture.faces import LOOKED_FOR as FACES_LOOKED_FOR
from pi_capture.faces import readings_from_faces
from pi_capture.generic import LOOKED_FOR as GENERIC_LOOKED_FOR
from pi_capture.generic import readings_from_generic
from pi_capture.landmark import LOOKED_FOR as LANDMARK_LOOKED_FOR
from pi_capture.landmark import LandmarkPageError, readings_from_landmark
from pi_capture.model import ProductCapture, Reading, dumps
from pi_capture.ounass import LOOKED_FOR as OUNASS_LOOKED_FOR
from pi_capture.ounass import readings_from_ounass
from pi_capture.page_json import NoProductObject, OutOfScopePage

ReadFn = Callable[[str, str, str | None], list[list[Reading]]]


@dataclass(frozen=True)
class Reader:
    name: str
    read: ReadFn
    looked_for: frozenset[str]


def _landmark(html: str, locale: str, url: str | None) -> list[list[Reading]]:
    return readings_from_landmark(html, locale=locale, url=url)


def _faces(html: str, locale: str, url: str | None) -> list[list[Reading]]:
    return [readings_from_faces(html, locale=locale, url=url)]


def _ounass(html: str, locale: str, url: str | None) -> list[list[Reading]]:
    return [readings_from_ounass(html, locale=locale, url=url)]


def _bloomingdales(html: str, locale: str, url: str | None) -> list[list[Reading]]:
    return [readings_from_bloomingdales(html, locale=locale, url=url)]


def _generic(html: str, locale: str, url: str | None) -> list[list[Reading]]:
    return [readings_from_generic(html, locale=locale, url=url)]


LANDMARK = Reader("landmark", _landmark, LANDMARK_LOOKED_FOR)
FACES = Reader("faces", _faces, FACES_LOOKED_FOR)
OUNASS = Reader("ounass", _ounass, OUNASS_LOOKED_FOR)
BLOOMINGDALES = Reader("bloomingdales", _bloomingdales, BLOOMINGDALES_LOOKED_FOR)
GENERIC = Reader("generic", _generic, GENERIC_LOOKED_FOR)

#: Retailer (the ``ref.retailer`` a capture plan gave the page) to its reader. Every other
#: retailer is read by the generic readers.
READERS: Mapping[str, Reader] = {
    "centrepoint": LANDMARK,
    "splash": LANDMARK,
    "babyshop": LANDMARK,
    "home_centre": LANDMARK,
    "max_fashion": LANDMARK,
    "faces": FACES,
    "ounass": OUNASS,
    "bloomingdales": BLOOMINGDALES,
}


def reader_for(retailer: str) -> Reader:
    return READERS.get(retailer, GENERIC)


class Bucket(Protocol):
    def names(self, prefix: str) -> list[str]: ...
    def get(self, name: str) -> bytes: ...
    def put(self, name: str, data: bytes) -> None: ...
    def exists(self, name: str) -> bool: ...


class LocalBucket:
    """A directory standing in for the bucket (tests and local runs)."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def names(self, prefix: str) -> list[str]:
        base = self.root / prefix
        if not base.is_dir():
            return []
        return sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file())

    def get(self, name: str) -> bytes:
        return (self.root / name).read_bytes()

    def put(self, name: str, data: bytes) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def exists(self, name: str) -> bool:
        return (self.root / name).is_file()


class GcsBucket:  # pragma: no cover - exercised only inside the cloud job
    def __init__(self, bucket: str) -> None:
        from google.cloud import storage  # noqa: PLC0415 - only in the cloud job

        self._bucket = storage.Client().bucket(bucket)

    def names(self, prefix: str) -> list[str]:
        return sorted(b.name for b in self._bucket.client.list_blobs(self._bucket, prefix=prefix))

    def get(self, name: str) -> bytes:
        data: bytes = self._bucket.blob(name).download_as_bytes()
        return data

    def put(self, name: str, data: bytes) -> None:
        self._bucket.blob(name).upload_from_string(data, content_type="application/gzip")

    def exists(self, name: str) -> bool:
        return bool(self._bucket.blob(name).exists())


@dataclass
class PageResult:
    state: str
    lines: list[str] = field(default_factory=list)
    reason: str | None = None


def read_page(rec: Mapping[str, Any], body: bytes, egress: str) -> PageResult:
    """Readings for one saved page; ``state`` is ``ok`` or why there are none."""
    if hashlib.sha256(body).hexdigest() != rec["sha256"]:
        return PageResult("sha_mismatch", reason="body does not match the recorded sha256")
    retailer = str(rec["ref"]["retailer"])
    reader = reader_for(retailer)
    url = rec.get("final_url") or rec["url"]
    try:
        lists = reader.read(body.decode("utf-8", "replace"), rec["locale"], url)
        lines = [
            dumps(
                ProductCapture(
                    source=str(rec["ref"]["source"]),
                    retailer=retailer,
                    url=url,
                    locale=rec["locale"],
                    retrieved_at=datetime.fromisoformat(rec["at"]),
                    egress=egress,
                    page_sha256=rec["sha256"],
                    readings=tuple(readings),
                    looked_for=tuple(sorted(reader.looked_for)),
                )
            )
            for readings in lists
        ]
    except (LandmarkPageError, NoProductObject) as exc:
        return PageResult("not_product", reason=str(exc))
    except OutOfScopePage as exc:  # a product, just not one this capture is for
        return PageResult("out_of_scope", reason=str(exc))
    except Exception as exc:  # counted and written to errors/, never silent
        return PageResult("reader_error", reason=f"{type(exc).__name__}: {str(exc)[:300]}")
    if not lines:
        return PageResult("no_rows", reason="reader returned no product rows")
    return PageResult("ok", lines)


def mine(part: str, index: int, count: int) -> bool:
    """Whether ``part`` belongs to task ``index``: a stable hash, not list position."""
    return zlib.crc32(part.rsplit("/", 1)[-1].encode()) % count == index


@dataclass(frozen=True)
class Job:
    src_prefix: str
    locale: str
    egress: str
    out: str = "readings"
    retailers: frozenset[str] | None = None
    index: int = 0
    count: int = 1


def _wanted(rec: Mapping[str, Any], job: Job) -> bool:
    if rec.get("state") != "ok" or rec.get("locale") != job.locale:
        return False
    return job.retailers is None or rec["ref"]["retailer"] in job.retailers


def read_part(bucket: Bucket, part: str, job: Job, counts: Counter[str]) -> None:
    lines: list[str] = []
    errors: list[str] = []
    for raw_line in gzip.decompress(bucket.get(part)).decode("utf-8").splitlines():
        if not raw_line.strip():
            continue
        rec = json.loads(raw_line)
        if not _wanted(rec, job):
            continue
        counts["pages"] += 1
        body = gzip.decompress(bucket.get(f"{job.src_prefix}/{rec['raw']}"))
        result = read_page(rec, body, job.egress)
        counts[f"pages_{result.state}"] += 1
        if result.state == "ok":
            lines.extend(result.lines)
            counts["rows"] += len(result.lines)
        else:
            errors.append(
                json.dumps({"url": rec["url"], "state": result.state, "reason": result.reason})
            )
    name = part.rsplit("/", 1)[-1]
    if errors:
        data = "".join(e + "\n" for e in errors).encode()
        bucket.put(f"{job.src_prefix}/{job.out}/errors/{name}", gzip.compress(data))
    data = "".join(line + "\n" for line in lines).encode()
    bucket.put(f"{job.src_prefix}/{job.out}/{name}", gzip.compress(data))
    counts["parts_read"] += 1


def run(bucket: Bucket, job: Job) -> dict[str, int]:
    """Read every part this task owns that has no readings file yet; returns the counts."""
    counts: Counter[str] = Counter()
    parts = [
        p
        for p in bucket.names(f"{job.src_prefix}/pages/")
        if p.endswith(".jsonl.gz") and mine(p, job.index, job.count)
    ]
    for part in parts:
        name = part.rsplit("/", 1)[-1]
        if bucket.exists(f"{job.src_prefix}/{job.out}/{name}"):
            counts["parts_already_read"] += 1
            continue
        read_part(bucket, part, job, counts)
    status = dict(sorted(counts.items()))
    bucket.put(
        f"{job.src_prefix}/{job.out}/status.t{job.index}.json",
        json.dumps(status, indent=1).encode(),
    )
    return status


def job_from_env(env: Mapping[str, str]) -> tuple[str, Job]:
    """``(bucket, job)`` from the environment; missing required settings raise ``KeyError``."""
    retailers = env.get("RETAILERS", "").strip()
    return env["BUCKET"], Job(
        src_prefix=env["SRC_PREFIX"].strip("/"),
        locale=env["LOCALE"],
        egress=env["CAPTURE_EGRESS"],
        out=env.get("OUT", "readings").strip("/") or "readings",
        retailers=frozenset(r.strip() for r in retailers.split(",") if r.strip()) or None,
        index=int(env.get("CLOUD_RUN_TASK_INDEX", "0")),
        count=int(env.get("CLOUD_RUN_TASK_COUNT", "1")),
    )


def main(env: Mapping[str, str] | None = None, bucket: Bucket | None = None) -> int:
    name, job = job_from_env(os.environ if env is None else env)
    target: Bucket
    if bucket is not None:
        target = bucket
    elif name.startswith("file:"):
        target = LocalBucket(name.removeprefix("file:"))
    else:  # pragma: no cover - cloud only
        target = GcsBucket(name)
    status = run(target, job)
    print(json.dumps({"task": job.index, **status}), flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
