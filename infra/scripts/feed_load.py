"""Host cron: load the feeds the scheduled UAE collection writes into the local pi_db.

    uv run --with 'google-auth>=2.30,<3' --with 'requests>=2.32,<3' \
      python infra/scripts/feed_load.py load    # every new feed, oldest first
    uv run python infra/scripts/feed_load.py check   # exit 1 if the last load failed or is stale

``load`` runs in the workspace environment (offline_import's database stack) plus google-auth for
the token, which the workspace itself does not carry.

The collection jobs (tools/uae_collect) write ``feeds/<source>/<run id>/<source>.feed.json`` and
``.mapping.json`` to the capture bucket; pi_db is local to this host, so the load runs here. It
reads as the feed-reader service account, which may only read and list ``feeds/`` in that bucket.
No key for it exists: the credentials already on the host (GOOGLE_APPLICATION_CREDENTIALS) mint a
15-minute read-only token for it, as in pg_backup.py.

Each feed goes through ``offline_import`` with ``--uri gs://…`` as its evidence. offline_import is
idempotent by the file's sha256, so a feed loaded twice inserts nothing the second time; the local
ledger only saves the download. Feeds load in run order, and the first failure stops the load,
so a later run never lands before an earlier one. PI_DATABASE_URL comes from the cron's own
environment file, written by the owner; this script never prints it.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT = "productintelligence-beeb3"
BUCKET = "pi-capture-productintelligence-beeb3"
READER = f"pi-feed-reader@{PROJECT}.iam.gserviceaccount.com"
PREFIX = "feeds/"
#: sources this loader accepts; a feed for any other source is left alone and reported
SOURCES = frozenset({"faces_ae"})
STATE_DIR = Path.home() / ".local/state/pi-feed-load"
KEEP_LOCAL = 30  # downloaded run folders kept per source
MAX_AGE = timedelta(hours=50)  # the jobs run daily; two missed days is worth a look
ATTENTION = "ATTENTION"
API = "https://storage.googleapis.com/storage/v1/b/{bucket}/o"
REPO = Path(__file__).resolve().parents[2]
FEED = re.compile(
    r"^feeds/(?P<source>[a-z0-9_]+)/(?P<run>[0-9TZ:-]+-[a-z]+)/(?P=source)\.feed\.json$"
)

Get = Callable[[str, str], bytes]
Run = Callable[..., subprocess.CompletedProcess[str]]


def log(message: str) -> None:
    print(f"{datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ} {message}", flush=True)


def reader_token(reader: str) -> str:  # pragma: no cover - needs the host's credentials
    """A short-lived read-only token for the reader account, minted from the host's credentials."""
    import google.auth  # noqa: PLC0415 (lazy: the unit tests run without it)
    from google.auth import impersonated_credentials  # noqa: PLC0415
    from google.auth.transport.requests import Request  # noqa: PLC0415

    source, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    target = impersonated_credentials.Credentials(
        source_credentials=source,
        target_principal=reader,
        target_scopes=["https://www.googleapis.com/auth/devstorage.read_only"],
        lifetime=900,
    )
    target.refresh(Request())
    return str(target.token)


def http_get(url: str, token: str) -> bytes:  # pragma: no cover - network
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - fixed https host
        data: bytes = response.read()
    return data


def list_names(get: Get, token: str, bucket: str, prefix: str) -> list[str]:
    names: list[str] = []
    page: str | None = None
    while True:
        query = {"prefix": prefix, "fields": "items(name),nextPageToken"}
        if page:
            query["pageToken"] = page
        doc: dict[str, Any] = json.loads(
            get(f"{API.format(bucket=bucket)}?{urllib.parse.urlencode(query)}", token)
        )
        names.extend(str(item["name"]) for item in doc.get("items", []))
        page = doc.get("nextPageToken")
        if not page:
            return names


def download(get: Get, token: str, bucket: str, name: str) -> bytes:
    quoted = urllib.parse.quote(name, safe="")
    return get(f"{API.format(bucket=bucket)}/{quoted}?alt=media", token)


def pending(names: Sequence[str], ledger: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(feeds to load in run order, feeds of sources this loader does not accept)."""
    present = set(names)
    todo: list[tuple[str, str, str]] = []
    foreign: list[str] = []
    for name in names:
        m = FEED.match(name)
        if not m or name in ledger:
            continue
        if m["source"] not in SOURCES:
            foreign.append(name)
        elif name.replace(".feed.json", ".mapping.json") in present:
            todo.append((m["run"], m["source"], name))
    return [name for _, _, name in sorted(todo)], foreign


def read_ledger(state: Path) -> dict[str, Any]:
    path = state / "ledger.json"
    doc: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {}
    return doc


def write_json(path: Path, doc: object) -> None:
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    partial.rename(path)


def import_feed(run: Run, bucket: str, name: str, feed: Path, mapping: Path) -> dict[str, Any]:
    """One ``offline_import`` load; returns its summary line (``load`` holds the run ids)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(REPO / "tools/offline_import"), env.get("PYTHONPATH", "")) if p
    )
    argv = [sys.executable, "-m", "offline_import", str(feed), "--mapping", str(mapping)]
    argv += ["--report", str(feed.with_suffix(".report.json")), "--uri", f"gs://{bucket}/{name}"]
    done = run(argv, env=env, cwd=REPO, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        tail = (done.stderr or "").strip().splitlines()[-1:] or ["no output"]
        raise RuntimeError(f"offline_import exit {done.returncode}: {tail[0]}")
    summary: dict[str, Any] = json.loads(done.stdout.strip().splitlines()[-1])
    if "load" not in summary:
        raise RuntimeError("offline_import printed no load result")
    return summary


def prune(state: Path, keep: int) -> None:
    for source in (state / "feeds").glob("*"):
        for old in sorted(p for p in source.iterdir() if p.is_dir())[:-keep]:
            shutil.rmtree(old)


def load(
    args: argparse.Namespace,
    token: Callable[[str], str] = reader_token,
    get: Get = http_get,
    run: Run = subprocess.run,
) -> int:
    os.umask(0o077)
    state: Path = args.state_dir
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    now = datetime.now(UTC)
    status: dict[str, Any] = {"status": "failed", "at": f"{now:%Y-%m-%dT%H:%M:%SZ}", "loaded": []}
    try:
        if not os.environ.get("PI_DATABASE_URL"):
            raise RuntimeError("PI_DATABASE_URL is not set (the cron's environment file)")
        ledger = read_ledger(state)
        bearer = token(READER)
        todo, foreign = pending(list_names(get, bearer, args.bucket, PREFIX), ledger)
        status["foreign"] = foreign
        for name in todo:
            m = FEED.match(name)
            assert m is not None  # noqa: S101 - pending() only returns matching names
            folder = state / "feeds" / m["source"] / m["run"]
            folder.mkdir(parents=True, exist_ok=True)
            feed, mapping = folder / Path(name).name, folder / f"{m['source']}.mapping.json"
            feed.write_bytes(download(get, bearer, args.bucket, name))
            mapping.write_bytes(
                download(get, bearer, args.bucket, name.replace(".feed.json", ".mapping.json"))
            )
            declared = json.loads(mapping.read_text())["source"]["name"]
            if declared != m["source"]:
                raise RuntimeError(f"{name}: mapping names source {declared!r}")
            summary = import_feed(run, args.bucket, name, feed, mapping)
            entry = {"at": f"{datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}", "sha256": summary["sha256"]}
            entry |= {
                k: summary["load"].get(k)
                for k in ("crawl_run_id", "replay", "observations_inserted", "rejected")
            }
            ledger[name] = entry
            write_json(state / "ledger.json", ledger)
            status["loaded"].append(name)
            log(f"loaded {name}: {json.dumps(entry, sort_keys=True)}")
        prune(state, KEEP_LOCAL)
        status["status"] = "ok"
        if foreign:
            log(f"{ATTENTION}: feeds for sources not accepted here: {', '.join(foreign)}")
    except Exception as exc:  # the cron log and status.json must say why
        status["error"] = str(exc)
        log(f"{ATTENTION}: feed load failed: {exc}")
    write_json(state / "status.json", status)
    return 0 if status["status"] == "ok" else 1


def check_status(status: dict[str, Any], now: datetime, max_age: timedelta) -> list[str]:
    problems: list[str] = []
    if status.get("status") != "ok":
        problems.append(f"last load {status.get('status', 'missing')}: {status.get('error', '')}")
    at = status.get("at")
    if (
        not at
        or now - datetime.strptime(str(at), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) > max_age
    ):
        problems.append(f"no load since {at or 'ever'}")
    return problems


def check(args: argparse.Namespace) -> int:
    path = args.state_dir / "status.json"
    status: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {}
    problems = check_status(status, datetime.now(UTC), MAX_AGE)
    for problem in problems:
        log(f"{ATTENTION}: {problem}")
    return 1 if problems else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="feed_load", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["load", "check"])
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    parser.add_argument("--bucket", default=BUCKET)
    args = parser.parse_args(argv)
    return load(args) if args.command == "load" else check(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
