"""Report Sephora runs that are still unloaded at day 10 (ADR-0009; outputs are kept 14 days, #124).

Usage (host side, read-only)::

    PI_DATABASE_URL=... python -m sephora_snapshot.stale <bucket> [--days 10]

It reads each run's ``status.json`` (or, for runs made before it existed, ``progress.json``) from
the bucket, and the ``crawl_run`` rows the loader made for those prefixes, on a read-only
connection that is rolled back. A run counts as loaded once a ``crawl_run`` for its prefix has
``finished_at`` set. A run with nothing to load (no page or stock read) is never reported.

Output: one JSON line per unloaded run, then a summary line. Exit 1 when any run is reported, so
the host timer or monitoring can alert on it. It writes nothing anywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import psycopg

from sephora_snapshot import cadence

STATUS_FILES = ("status.json", "progress.json")  # newest first

FINISHED_SQL = """
SELECT DISTINCT split_part(manifest_uri, '/progress.json#', 1)
FROM crawl_run
WHERE manifest_uri LIKE %(like)s AND finished_at IS NOT NULL
"""


def run_states(bucket: str, files: Iterable[tuple[str, dict[str, Any]]]) -> list[cadence.RunState]:
    """One state per prefix from ``(object name, parsed JSON)`` pairs; status.json wins."""
    best: dict[str, tuple[int, dict[str, Any]]] = {}
    for name, body in files:
        prefix, _, leaf = name.rpartition("/")
        if not prefix or leaf not in STATUS_FILES or "/" in prefix:
            continue
        rank = STATUS_FILES.index(leaf)
        if prefix not in best or rank < best[prefix][0]:
            best[prefix] = (rank, body)
    return [
        cadence.RunState(
            prefix=f"gs://{bucket}/{prefix}",
            started=datetime.fromisoformat(body["started"]),
            counts=body.get("counts") or {},
        )
        for prefix, (_, body) in sorted(best.items())
        if body.get("started")
    ]


def finished_prefixes(database_url: str, bucket: str) -> set[str]:
    url = database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        conn.read_only = True
        rows = conn.execute(FINISHED_SQL, {"like": f"gs://{bucket}/%"}).fetchall()
        conn.rollback()
    return {str(row[0]) for row in rows}


def bucket_files(bucket: str) -> list[tuple[str, dict[str, Any]]]:
    from google.cloud import storage  # noqa: PLC0415 - host-side only

    client = storage.Client()
    out = []
    for leaf in STATUS_FILES:
        for blob in client.list_blobs(bucket, match_glob=f"*/{leaf}"):
            out.append((blob.name, json.loads(blob.download_as_bytes())))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sephora_snapshot.stale")
    ap.add_argument("bucket")
    ap.add_argument("--days", type=int, default=cadence.UNLOADED_ALERT_DAYS)
    args = ap.parse_args(argv)
    runs = run_states(args.bucket, bucket_files(args.bucket))
    done = finished_prefixes(os.environ["PI_DATABASE_URL"], args.bucket)
    late = cadence.unloaded(runs, done, datetime.now(UTC), args.days)
    for run in late:
        print(json.dumps({"unloaded": run.prefix, "started": run.started.isoformat()}))
    print(
        json.dumps(
            {
                "runs": len(runs),
                "loaded": len(done),
                "unloaded_at_day": args.days,
                "unloaded": len(late),
            }
        )
    )
    return 1 if late else 0


if __name__ == "__main__":
    sys.exit(main())
