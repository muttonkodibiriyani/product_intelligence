#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["google-auth>=2.30,<3", "requests>=2.32,<3"]
# ///
"""Nightly PostgreSQL backup: pg_dump -Fc of the local stack, verified, uploaded to a bucket.

    uv run --script infra/scripts/pg_backup.py backup          # dump, verify, upload, prune
    uv run --script infra/scripts/pg_backup.py check           # exit 1 if failed or stale
    uv run --script infra/scripts/pg_backup.py restore-test F  # scratch-DB restore + counts

The upload runs as the uploader service account, which can only create objects in the backup
bucket. No key for it exists: the credentials already on the host (GOOGLE_APPLICATION_CREDENTIALS)
only mint a 15-minute token for it. See docs/runbooks/db-backup-restore.md.
"""

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT = "productintelligence-beeb3"
BUCKET = "productintelligence-beeb3-pg-backups"
UPLOADER = f"pi-db-backup@{PROJECT}.iam.gserviceaccount.com"
CONTAINER = "product-intelligence-postgres-1"
DB_USER = "pi"
DB_NAME = "pi"
STATE_DIR = Path.home() / ".local/state/pi-backup"
KEEP_LOCAL = 3
MAX_AGE = timedelta(hours=26)
SCRATCH_DB = "pi_restore_check"
UPLOAD_URL = "https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o"

Run = Callable[..., subprocess.CompletedProcess[bytes]]


def log(message: str) -> None:
    print(f"{datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ} {message}", flush=True)


def stamp(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def object_name(db: str, now: datetime) -> str:
    """Dated prefix so a day's dumps list together; the full stamp keeps every name unique."""
    now = now.astimezone(UTC)
    return f"postgres/{db}/{now:%Y/%m/%d}/{db}-{stamp(now)}.dump"


def digests(path: Path) -> tuple[str, str]:
    """(sha256 hex, md5 base64); GCS reports md5Hash in base64."""
    sha, md5 = hashlib.sha256(), hashlib.md5()  # noqa: S324 - md5 only to match GCS's checksum
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            sha.update(chunk)
            md5.update(chunk)
    return sha.hexdigest(), base64.b64encode(md5.digest()).decode()


def docker(container: str, *argv: str, stdin: bool = False) -> list[str]:
    return ["docker", "exec", *(["-i"] if stdin else []), container, *argv]


def dump(run: Run, container: str, db: str, target: Path) -> None:
    """pg_dump -Fc inside the container (server-matched version), written atomically."""
    partial = target.with_suffix(".partial")
    with partial.open("wb") as out:
        run(docker(container, "pg_dump", "-Fc", "-U", DB_USER, "-d", db), stdout=out, check=True)
    partial.rename(target)


def table_data_entries(listing: str) -> int:
    """TABLE DATA entries in `pg_restore --list` output (comment lines start with ';')."""
    return sum(
        1 for line in listing.splitlines() if not line.startswith(";") and " TABLE DATA " in line
    )


def verify(run: Run, container: str, path: Path) -> int:
    """The archive must be readable by pg_restore and carry table data; returns the entry count."""
    with path.open("rb") as fh:
        listing = run(
            docker(container, "pg_restore", "--list", stdin=True),
            stdin=fh,
            stdout=subprocess.PIPE,
            check=True,
        )
    entries = table_data_entries(listing.stdout.decode())
    if entries == 0:
        raise RuntimeError("archive has no TABLE DATA entries")
    return entries


def uploader_token(uploader: str) -> str:
    """A short-lived token for the uploader account, minted from the host's existing credentials."""
    import google.auth  # noqa: PLC0415 (lazy: the workspace and unit tests run without it)
    from google.auth import impersonated_credentials  # noqa: PLC0415
    from google.auth.transport.requests import Request  # noqa: PLC0415

    source, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    target = impersonated_credentials.Credentials(
        source_credentials=source,
        target_principal=uploader,
        target_scopes=["https://www.googleapis.com/auth/devstorage.read_write"],
        lifetime=900,
    )
    target.refresh(Request())
    return str(target.token)


def upload(
    token: str, bucket: str, name: str, path: Path, metadata: dict[str, str]
) -> dict[str, str]:
    """Create-only multipart upload (ifGenerationMatch=0): an existing object is never replaced."""
    boundary = "pi-backup-" + hashlib.sha256(name.encode()).hexdigest()[:16]
    head = json.dumps(
        {"name": name, "contentType": "application/octet-stream", "metadata": metadata}
    )
    body = b"".join(
        [
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode(),
            f"{head}\r\n".encode(),
            f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n".encode(),
            path.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    query = urllib.parse.urlencode({"uploadType": "multipart", "ifGenerationMatch": "0"})
    request = urllib.request.Request(  # noqa: S310 - fixed https endpoint
        f"{UPLOAD_URL.format(bucket=bucket)}?{query}",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
    )
    with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310
        result: dict[str, str] = json.load(response)
    return result


def prune(directory: Path, keep: int) -> list[Path]:
    """Keep the newest `keep` local dumps (names sort by stamp); returns what was removed."""
    dumps = sorted(directory.glob("*.dump"))
    removed = dumps[: max(len(dumps) - keep, 0)]
    for path in removed:
        path.unlink()
    return removed


def write_status(state: Path, status: dict[str, object]) -> None:
    partial = state / "status.json.partial"
    partial.write_text(json.dumps(status, indent=1) + "\n")
    partial.rename(state / "status.json")


def backup(args: argparse.Namespace, run: Run = subprocess.run) -> int:
    state: Path = args.state_dir
    state.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    status: dict[str, object] = {"status": "failed", "at": stamp(now)}
    try:
        path = state / f"{args.db}-{stamp(now)}.dump"
        dump(run, args.container, args.db, path)
        entries = verify(run, args.container, path)
        sha256, md5 = digests(path)
        size = path.stat().st_size
        log(f"dumped {path.name}: {size} bytes, {entries} table-data entries, sha256 {sha256}")
        name = object_name(args.db, now)
        meta = {
            "sha256": sha256,
            "source": f"{args.container}/{args.db}",
            "tableDataEntries": str(entries),
        }
        result = upload(uploader_token(args.uploader), args.bucket, name, path, meta)
        if result.get("md5Hash") != md5:
            raise RuntimeError(f"md5 mismatch after upload: {result.get('md5Hash')} != {md5}")
        log(f"uploaded gs://{args.bucket}/{name} generation {result.get('generation')}")
        for old in prune(state, KEEP_LOCAL):
            log(f"pruned local {old.name}")
        status.update(status="ok", object=f"gs://{args.bucket}/{name}", bytes=size, sha256=sha256)
        status["lastSuccess"] = stamp(now)
        return 0
    except Exception as exc:  # the cron log and status.json must say why
        status["error"] = f"{type(exc).__name__}: {exc}"[:500]
        log(f"FAILED {status['error']}")
        return 1
    finally:
        previous = read_status(state)
        if status["status"] != "ok" and previous.get("lastSuccess"):
            status["lastSuccess"] = previous["lastSuccess"]
        write_status(state, status)


def read_status(state: Path) -> dict[str, object]:
    try:
        loaded: dict[str, object] = json.loads((state / "status.json").read_text())
    except FileNotFoundError:
        return {}
    return loaded


def check_status(status: dict[str, object], now: datetime, max_age: timedelta) -> list[str]:
    """Why the backup needs attention; empty when the last run succeeded recently."""
    problems = []
    if not status:
        return ["no backup has run yet"]
    if status.get("status") != "ok":
        problems.append(f"last run {status.get('at')} failed: {status.get('error')}")
    last = status.get("lastSuccess")
    if not isinstance(last, str):
        problems.append("no successful backup recorded")
    elif now - datetime.strptime(last, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC) > max_age:
        problems.append(f"last successful backup {last} is older than {max_age}")
    return problems


def check(args: argparse.Namespace) -> int:
    problems = check_status(read_status(args.state_dir), datetime.now(UTC), MAX_AGE)
    for problem in problems:
        log(f"ATTENTION {problem}")
    if not problems:
        log("backup ok")
    return 1 if problems else 0


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def count_sql(tables: Sequence[tuple[str, str]]) -> str:
    """One statement counting every table; names come from the catalog and are quoted."""
    parts = [
        f"SELECT '{s}.{t}', count(*) FROM {quote_ident(s)}.{quote_ident(t)}"  # noqa: S608
        for s, t in tables
        if "'" not in s + t
    ]
    return " UNION ALL ".join(parts) + " ORDER BY 1"


TABLES_SQL = (
    "SELECT table_schema, table_name FROM information_schema.tables "
    "WHERE table_type = 'BASE TABLE' AND table_schema NOT IN ('pg_catalog', 'information_schema') "
    "ORDER BY 1, 2"
)


def row_counts(run: Run, container: str, db: str) -> dict[str, int]:
    def psql(sql: str) -> list[list[str]]:
        out = run(
            docker(container, "psql", "-U", DB_USER, "-d", db, "-AtF", "\t", "-c", sql),
            stdout=subprocess.PIPE,
            check=True,
        ).stdout.decode()
        return [line.split("\t") for line in out.splitlines() if line]

    tables = [(s, t) for s, t in psql(TABLES_SQL)]
    return {name: int(n) for name, n in psql(count_sql(tables))}


def compare_counts(live: dict[str, int], restored: dict[str, int]) -> tuple[list[str], bool]:
    """Markdown rows plus whether the restore is complete (every table present, none larger)."""
    rows, ok = ["| table | live now | restored | diff |", "|---|---:|---:|---:|"], True
    for name in sorted(live.keys() | restored.keys()):
        a, b = live.get(name), restored.get(name)
        if b is None or (a is not None and b > a):
            ok = False
        diff = "missing" if a is None or b is None else f"{b - a:+d}"
        rows.append(f"| {name} | {'-' if a is None else a} | {'-' if b is None else b} | {diff} |")
    return rows, ok


def restore_test(args: argparse.Namespace, run: Run = subprocess.run) -> int:
    """Restore into a scratch DB in the same container, compare counts with the live DB, drop it."""
    sha256, _ = digests(args.dump)
    log(f"restore-test {args.dump.name} sha256 {sha256}")
    admin = docker(args.container, "psql", "-U", DB_USER, "-d", "postgres", "-c")
    run([*admin, f"DROP DATABASE IF EXISTS {SCRATCH_DB}"], check=True)
    run([*admin, f"CREATE DATABASE {SCRATCH_DB}"], check=True)
    try:
        with args.dump.open("rb") as fh:
            run(
                docker(
                    args.container,
                    "pg_restore",
                    "-U",
                    DB_USER,
                    "-d",
                    SCRATCH_DB,
                    "--no-owner",
                    "--exit-on-error",
                    stdin=True,
                ),
                stdin=fh,
                check=True,
            )
        restored = row_counts(run, args.container, SCRATCH_DB)
        live = row_counts(run, args.container, args.db)
    finally:
        run([*admin, f"DROP DATABASE IF EXISTS {SCRATCH_DB}"], check=True)
    rows, ok = compare_counts(live, restored)
    print("\n".join(rows))
    total = sum(restored.values())
    log(f"restored {len(restored)} tables, {total} rows; {'COMPLETE' if ok else 'INCOMPLETE'}")
    return 0 if ok else 1


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--state-dir", type=Path, default=Path(os.environ.get("PI_BACKUP_STATE", STATE_DIR))
    )
    p.add_argument("--container", default=CONTAINER)
    p.add_argument("--db", default=DB_NAME)
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup", help="dump, verify, upload, prune")
    b.add_argument("--bucket", default=BUCKET)
    b.add_argument("--uploader", default=UPLOADER)
    sub.add_parser("check", help="exit 1 if the last run failed or is older than 26 h")
    r = sub.add_parser("restore-test", help="restore a dump into a scratch DB and compare counts")
    r.add_argument("dump", type=Path)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "backup":
        return backup(args)
    if args.command == "check":
        return check(args)
    return restore_test(args)


if __name__ == "__main__":
    sys.exit(main())
