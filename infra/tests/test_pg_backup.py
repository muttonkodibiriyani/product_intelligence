"""pg_backup against fake docker/pg tools and a fake upload (no database, no network)."""

import argparse
import base64
import hashlib
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pg_backup
import pytest

DUMP = b"PGDMP fake archive bytes"
LISTING = b"""; Archive created at 2026-09-30
;     dbname: pi
3401; 0 16390 TABLE DATA public brand pi
3402; 0 16400 TABLE DATA public offer_observation pi
3380; 1259 16385 TABLE public brand pi
"""


def fake_run(listing: bytes = LISTING) -> Any:
    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        if "pg_dump" in argv:
            kwargs["stdout"].write(DUMP)
            return subprocess.CompletedProcess(argv, 0, b"")
        if "pg_restore" in argv:
            assert kwargs["stdin"].read() == DUMP
            return subprocess.CompletedProcess(argv, 0, listing)
        raise AssertionError(argv)

    run.calls = calls  # type: ignore[attr-defined]
    return run


def args(state: Path) -> argparse.Namespace:
    return pg_backup.parser().parse_args(["--state-dir", str(state), "backup"])


@pytest.fixture
def uploads(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record uploads and echo back the md5 GCS would compute."""
    sent: list[dict[str, Any]] = []

    def upload(
        token: str, bucket: str, name: str, path: Path, metadata: dict[str, str]
    ) -> dict[str, str]:
        sent.append({"token": token, "bucket": bucket, "name": name, "metadata": metadata})
        md5 = base64.b64encode(hashlib.md5(path.read_bytes()).digest()).decode()  # noqa: S324
        return {"md5Hash": md5, "generation": "1"}

    monkeypatch.setattr(pg_backup, "uploader_token", lambda uploader: f"token-for-{uploader}")
    monkeypatch.setattr(pg_backup, "upload", upload)
    return sent


def test_object_names_are_dated_and_unique_per_second() -> None:
    now = datetime(2026, 9, 30, 2, 30, 5, tzinfo=UTC)
    assert pg_backup.object_name("pi", now) == "postgres/pi/2026/09/30/pi-20260930T023005Z.dump"


def test_table_data_entries_ignores_comments_and_schema_entries() -> None:
    assert pg_backup.table_data_entries(LISTING.decode()) == 2


def test_digests_match_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "x.dump"
    path.write_bytes(DUMP)
    sha, md5 = pg_backup.digests(path)
    assert sha == hashlib.sha256(DUMP).hexdigest()
    assert base64.b64decode(md5) == hashlib.md5(DUMP).digest()  # noqa: S324


def test_backup_dumps_verifies_uploads_as_the_uploader_and_records_success(
    tmp_path: Path, uploads: list[dict[str, Any]]
) -> None:
    run = fake_run()
    assert pg_backup.backup(args(tmp_path), run) == 0
    assert [c[4 if "-i" in c else 3] for c in run.calls] == ["pg_dump", "pg_restore"]
    (sent,) = uploads
    assert sent["token"] == f"token-for-{pg_backup.UPLOADER}"
    assert sent["bucket"] == pg_backup.BUCKET
    assert sent["name"].startswith("postgres/pi/")
    assert sent["metadata"]["sha256"] == hashlib.sha256(DUMP).hexdigest()
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["status"] == "ok"
    assert status["lastSuccess"] == status["at"]
    assert not list(tmp_path.glob("*.partial"))


def test_an_archive_without_table_data_is_not_uploaded(
    tmp_path: Path, uploads: list[dict[str, Any]]
) -> None:
    assert pg_backup.backup(args(tmp_path), fake_run(listing=b"; empty\n")) == 1
    assert uploads == []
    status = json.loads((tmp_path / "status.json").read_text())
    assert "no TABLE DATA" in status["error"]


def test_failure_keeps_the_previous_success_and_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "status.json").write_text(
        json.dumps({"status": "ok", "lastSuccess": "20260929T023000Z"})
    )
    monkeypatch.setattr(pg_backup, "uploader_token", lambda uploader: "t")

    def refuse(*a: Any) -> dict[str, str]:
        raise PermissionError("403 storage.objects.create denied")

    monkeypatch.setattr(pg_backup, "upload", refuse)
    assert pg_backup.backup(args(tmp_path), fake_run()) == 1
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["status"] == "failed"
    assert "403" in status["error"]
    assert status["lastSuccess"] == "20260929T023000Z"


def test_md5_mismatch_after_upload_is_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pg_backup, "uploader_token", lambda uploader: "t")
    monkeypatch.setattr(pg_backup, "upload", lambda *a: {"md5Hash": "bogus"})
    assert pg_backup.backup(args(tmp_path), fake_run()) == 1


def test_prune_keeps_the_newest_dumps(tmp_path: Path) -> None:
    for day in range(1, 6):
        (tmp_path / f"pi-202609{day:02d}T023000Z.dump").write_bytes(b"x")
    removed = pg_backup.prune(tmp_path, 3)
    assert [p.name for p in removed] == ["pi-20260901T023000Z.dump", "pi-20260902T023000Z.dump"]
    assert len(list(tmp_path.glob("*.dump"))) == 3


NOW = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
DAY = timedelta(hours=26)


def test_check_is_quiet_after_a_recent_success() -> None:
    assert (
        pg_backup.check_status({"status": "ok", "lastSuccess": "20261001T023000Z"}, NOW, DAY) == []
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ({}, "no backup has run yet"),
        ({"status": "ok", "lastSuccess": "20260929T023000Z"}, "older than"),
        ({"status": "failed", "at": "20261001T023000Z", "error": "boom"}, "failed: boom"),
    ],
)
def test_check_reports_missing_stale_and_failed_runs(
    status: dict[str, object], expected: str
) -> None:
    assert any(expected in p for p in pg_backup.check_status(status, NOW, DAY))


def test_count_sql_quotes_identifiers() -> None:
    sql = pg_backup.count_sql([("public", "brand"), ("pi", 'odd"name')])
    assert 'FROM "public"."brand"' in sql
    assert 'FROM "pi"."odd""name"' in sql


def test_compare_counts_accepts_rows_added_since_the_dump_but_not_missing_tables() -> None:
    rows, ok = pg_backup.compare_counts(
        {"public.a": 10, "public.b": 5}, {"public.a": 8, "public.b": 5}
    )
    assert ok
    assert "| public.a | 10 | 8 | -2 |" in rows
    _, ok = pg_backup.compare_counts({"public.a": 1, "public.b": 1}, {"public.a": 1})
    assert not ok
    _, ok = pg_backup.compare_counts({"public.a": 1}, {"public.a": 2})
    assert not ok
