"""pg_backup against fake docker/pg tools and a fake upload (no database, no network)."""

import argparse
import base64
import hashlib
import io
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


COUNTS = {"public.brand": 158, "public.offer_observation": 5967}


def fake_run(
    listing: bytes = LISTING,
    counts: dict[str, dict[str, int]] | None = None,
    restore_fails: bool = False,
    dump_fails: bool = False,
) -> Any:
    """docker exec pg_dump / pg_restore / psql; `counts` maps database -> table -> rows."""
    counts = counts if counts is not None else {"pi": COUNTS, "*": COUNTS}
    calls: list[list[str]] = []

    def rows(db: str) -> dict[str, int]:
        return counts.get(db, counts.get("*", {}))

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        if "pg_dump" in argv:
            kwargs["stdout"].write(DUMP)
            if dump_fails:
                raise subprocess.CalledProcessError(1, argv)
            return subprocess.CompletedProcess(argv, 0, b"")
        if "pg_restore" in argv:
            assert kwargs["stdin"].read() == DUMP
            if "--list" in argv:
                return subprocess.CompletedProcess(argv, 0, listing)
            if restore_fails:
                err = b'pg_restore: error: type "field_state" does not exist'
                return subprocess.CompletedProcess(argv, 1, b"", err)
            return subprocess.CompletedProcess(argv, 0, b"")
        if "psql" in argv:
            db, sql = argv[argv.index("-d") + 1], argv[-1]
            if db == "postgres":
                return subprocess.CompletedProcess(argv, 0, b"")
            if sql == pg_backup.TABLES_SQL:
                out = "".join(f"{'\t'.join(t.split('.'))}\n" for t in sorted(rows(db)))
            else:
                out = "".join(f"{t}\t{n}\n" for t, n in sorted(rows(db).items()))
            return subprocess.CompletedProcess(argv, 0, out.encode())
        raise AssertionError(argv)

    run.calls = calls  # type: ignore[attr-defined]
    return run


def tools(run: Any) -> list[str]:
    return [c[4 if "-i" in c else 3] for c in run.calls]


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
    assert tools(run)[:3] == ["pg_dump", "pg_restore", "psql"]
    assert "pg_restore" in tools(run)[3:]  # the restore-verify into the scratch database
    assert run.calls[-1][-1] == f"DROP DATABASE IF EXISTS {pg_backup.VERIFY_DB}"
    dump_obj, counts_obj = uploads
    assert dump_obj["token"] == f"token-for-{pg_backup.UPLOADER}"
    assert dump_obj["bucket"] == pg_backup.BUCKET
    assert dump_obj["name"].startswith("postgres/pi/")
    assert counts_obj["name"] == dump_obj["name"] + ".counts.json"
    assert dump_obj["metadata"]["sha256"] == hashlib.sha256(DUMP).hexdigest()
    assert dump_obj["metadata"]["rows"] == str(sum(COUNTS.values()))
    (sidecar,) = tmp_path.glob("*.dump.counts.json")
    recorded = json.loads(sidecar.read_text())
    assert recorded["counts"] == COUNTS
    assert recorded["sha256"] == hashlib.sha256(DUMP).hexdigest()
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["status"] == "ok"
    assert status["lastSuccess"] == status["at"]
    assert not list(tmp_path.glob("*.partial"))


def test_local_backups_are_private(tmp_path: Path, uploads: list[dict[str, Any]]) -> None:
    state = tmp_path / "state"
    assert pg_backup.backup(args(state), fake_run()) == 0
    assert state.stat().st_mode & 0o777 == 0o700
    for path in state.iterdir():
        assert path.stat().st_mode & 0o077 == 0, path.name


def test_a_dump_that_does_not_restore_is_not_uploaded(
    tmp_path: Path, uploads: list[dict[str, Any]]
) -> None:
    run = fake_run(restore_fails=True)
    assert pg_backup.backup(args(tmp_path), run) == 1
    assert uploads == []
    assert run.calls[-1][-1] == f"DROP DATABASE IF EXISTS {pg_backup.VERIFY_DB}"
    error = json.loads((tmp_path / "status.json").read_text())["error"]
    assert 'pg_restore failed: pg_restore: error: type "field_state" does not exist' in error


def test_a_dump_that_restores_no_rows_is_not_uploaded(
    tmp_path: Path, uploads: list[dict[str, Any]]
) -> None:
    empty = {"public.brand": 0, "public.offer_observation": 0}
    assert pg_backup.backup(args(tmp_path), fake_run(counts={"*": empty})) == 1
    assert uploads == []


def test_a_failed_dump_leaves_no_partial_file(
    tmp_path: Path, uploads: list[dict[str, Any]]
) -> None:
    assert pg_backup.backup(args(tmp_path), fake_run(dump_fails=True)) == 1
    assert list(tmp_path.glob("*.partial")) == []
    assert list(tmp_path.glob("*.dump")) == []


def test_upload_is_create_only_and_sends_the_md5_for_server_side_checking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "x.dump"
    path.write_bytes(DUMP)
    seen: list[Any] = []

    class Response(io.BytesIO):
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *a: object) -> None:
            pass

    def urlopen(request: Any, timeout: int) -> Response:
        seen.append(request)
        return Response(b'{"md5Hash": "m", "generation": "1"}')

    monkeypatch.setattr(pg_backup.urllib.request, "urlopen", urlopen)
    assert pg_backup.upload("t", "b", "o", path, {"k": "v"})["generation"] == "1"
    (request,) = seen
    assert "ifGenerationMatch=0" in request.full_url
    head = json.loads(request.data.split(b"\r\n")[3])
    assert head["md5Hash"] == pg_backup.digests(path)[1]
    assert head["metadata"] == {"k": "v"}


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


def test_prune_keeps_the_newest_dumps_and_their_counts(tmp_path: Path) -> None:
    for day in range(1, 6):
        (tmp_path / f"pi-202609{day:02d}T023000Z.dump").write_bytes(b"x")
        (tmp_path / f"pi-202609{day:02d}T023000Z.dump.counts.json").write_bytes(b"{}")
    removed = pg_backup.prune(tmp_path, 3)
    assert [p.name for p in removed] == ["pi-20260901T023000Z.dump", "pi-20260902T023000Z.dump"]
    assert len(list(tmp_path.glob("*.dump"))) == 3
    assert len(list(tmp_path.glob("*.counts.json"))) == 3


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


def test_check_raises_and_clears_the_attention_flag(tmp_path: Path) -> None:
    check = pg_backup.parser().parse_args(["--state-dir", str(tmp_path), "check"])
    (tmp_path / "status.json").write_text(json.dumps({"status": "failed", "error": "403"}))
    assert pg_backup.check(check) == 1
    assert "failed: 403" in (tmp_path / "ATTENTION").read_text()
    fresh = pg_backup.stamp(datetime.now(UTC))
    (tmp_path / "status.json").write_text(json.dumps({"status": "ok", "lastSuccess": fresh}))
    assert pg_backup.check(check) == 0
    assert not (tmp_path / "ATTENTION").exists()


def test_count_sql_quotes_identifiers() -> None:
    sql = pg_backup.count_sql([("public", "brand"), ("pi", 'odd"name')])
    assert 'FROM "public"."brand"' in sql
    assert 'FROM "pi"."odd""name"' in sql


def test_compare_counts_requires_exactly_the_counts_at_dump_time() -> None:
    dumped = {"public.a": 10, "public.b": 5}
    rows, ok = pg_backup.compare_counts(dumped, dict(dumped), {"public.a": 12, "public.b": 5})
    assert ok
    assert "| public.a | 10 | 10 | 12 |" in rows
    for restored in (
        {"public.a": 8, "public.b": 5},
        {"public.a": 10},
        {"public.a": 0, "public.b": 0},
    ):
        rows, ok = pg_backup.compare_counts(dumped, restored)
        assert not ok
        assert any("MISMATCH" in r for r in rows)
    assert not pg_backup.compare_counts({}, {})[1]


def restore_args(dump: Path) -> argparse.Namespace:
    return pg_backup.parser().parse_args(["restore-test", str(dump)])


def write_dump(tmp_path: Path, counts: dict[str, int], sha: str | None = None) -> Path:
    dump = tmp_path / "pi-20261001T023000Z.dump"
    dump.write_bytes(DUMP)
    recorded = {"sha256": sha or hashlib.sha256(DUMP).hexdigest(), "counts": counts}
    pg_backup.counts_path(dump).write_text(json.dumps(recorded))
    return dump


def test_restore_test_is_complete_when_restored_counts_equal_the_dump_time_counts(
    tmp_path: Path,
) -> None:
    grown = {"public.brand": 160, "public.offer_observation": 9000}
    run = fake_run(counts={"pi": grown, pg_backup.SCRATCH_DB: COUNTS})
    assert pg_backup.restore_test(restore_args(write_dump(tmp_path, COUNTS)), run) == 0


def test_restore_test_fails_when_fewer_rows_come_back_than_were_dumped(tmp_path: Path) -> None:
    truncated = {"public.brand": 158, "public.offer_observation": 2000}
    run = fake_run(counts={"pi": COUNTS, pg_backup.SCRATCH_DB: truncated})
    assert pg_backup.restore_test(restore_args(write_dump(tmp_path, COUNTS)), run) == 1


def test_restore_test_refuses_counts_recorded_for_another_dump(tmp_path: Path) -> None:
    run = fake_run()
    assert (
        pg_backup.restore_test(restore_args(write_dump(tmp_path, COUNTS, sha="0" * 64)), run) == 1
    )
    assert run.calls == []
