"""feed_load against a fake bucket and a fake offline_import (no network, no database)."""

import argparse
import json
import subprocess
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import feed_load
import pytest

B = "bkt"
DAY1, DAY2 = "2026-10-07T200000Z-daily", "2026-10-08T200000Z-full"


def _feed(source: str, run: str) -> dict[str, bytes]:
    base = f"feeds/{source}/{run}/{source}"
    mapping = {"source": {"name": source}, "complete_catalogue": False}
    return {
        f"{base}.feed.json": b'{"items": []}',
        f"{base}.mapping.json": json.dumps(mapping).encode(),
    }


class _Bucket:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.tokens: set[str] = set()

    def get(self, url: str, token: str) -> bytes:
        self.tokens.add(token)
        parts = urllib.parse.urlsplit(url)
        api = feed_load.API.format(bucket=B)
        if url.startswith(f"{api}?"):
            query = dict(urllib.parse.parse_qsl(parts.query))
            names = sorted(n for n in self.objects if n.startswith(query["prefix"]))
            start = int(query.get("pageToken", "0"))
            doc: dict[str, Any] = {"items": [{"name": n} for n in names[start : start + 2]]}
            if start + 2 < len(names):
                doc["nextPageToken"] = str(start + 2)
            return json.dumps(doc).encode()
        name = urllib.parse.unquote(parts.path.rsplit("/o/", 1)[1])
        return self.objects[name]


class _Import:
    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        assert "tools/offline_import" in kw["env"]["PYTHONPATH"]
        if self.fail_on and self.fail_on in argv[-1]:
            return subprocess.CompletedProcess(argv, 2, "", "offline_import: bad mapping\n")
        load = {"crawl_run_id": len(self.calls), "replay": False, "observations_inserted": 3}
        out = json.dumps({"sha256": f"h{len(self.calls)}", "rows": 3, "load": load})
        return subprocess.CompletedProcess(argv, 0, f"noise\n{out}\n", "")


def _args(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(state_dir=tmp_path / "state", bucket=B)


def _status(tmp_path: Path) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((tmp_path / "state/status.json").read_text())
    return doc


@pytest.fixture(autouse=True)
def _db_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PI_DATABASE_URL", "postgresql://example.invalid/none")


def test_loads_new_feeds_in_run_order_once(tmp_path: Path) -> None:
    bucket = _Bucket(_feed("faces_ae", DAY2) | _feed("faces_ae", DAY1) | {"feeds/x.txt": b""})
    run = _Import()
    assert feed_load.load(_args(tmp_path), lambda sa: f"tok:{sa}", bucket.get, run) == 0
    assert [Path(c[3]).parent.name for c in run.calls] == [DAY1, DAY2]
    assert run.calls[0][-2:] == ["--uri", f"gs://{B}/feeds/faces_ae/{DAY1}/faces_ae.feed.json"]
    assert bucket.tokens == {f"tok:{feed_load.READER}"}
    status = _status(tmp_path)
    assert status["status"] == "ok"
    assert len(status["loaded"]) == 2
    ledger = json.loads((tmp_path / "state/ledger.json").read_text())
    assert ledger[f"feeds/faces_ae/{DAY1}/faces_ae.feed.json"]["crawl_run_id"] == 1

    again = _Import()
    assert feed_load.load(_args(tmp_path), lambda sa: "t", bucket.get, again) == 0
    assert again.calls == []


def test_first_failure_stops_the_load(tmp_path: Path) -> None:
    bucket = _Bucket(_feed("faces_ae", DAY1) | _feed("faces_ae", DAY2))
    run = _Import(fail_on=DAY1)
    assert feed_load.load(_args(tmp_path), lambda sa: "t", bucket.get, run) == 1
    assert len(run.calls) == 1  # DAY2 never lands before DAY1
    status = _status(tmp_path)
    assert status["status"] == "failed"
    assert "bad mapping" in status["error"]
    assert not (tmp_path / "state/ledger.json").exists()


def test_foreign_sources_and_incomplete_runs_are_left_alone(tmp_path: Path, capsys: Any) -> None:
    objects = _feed("faces_ae", DAY1) | _feed("ounass_ae", DAY1)
    del objects[f"feeds/faces_ae/{DAY1}/faces_ae.mapping.json"]  # still being written
    run = _Import()
    assert feed_load.load(_args(tmp_path), lambda sa: "t", _Bucket(objects).get, run) == 0
    assert run.calls == []
    assert _status(tmp_path)["foreign"] == [f"feeds/ounass_ae/{DAY1}/ounass_ae.feed.json"]
    assert "ATTENTION" in capsys.readouterr().out


def test_mapping_must_name_its_folder_source(tmp_path: Path) -> None:
    objects = _feed("faces_ae", DAY1)
    objects[f"feeds/faces_ae/{DAY1}/faces_ae.mapping.json"] = b'{"source": {"name": "other"}}'
    run = _Import()
    assert feed_load.load(_args(tmp_path), lambda sa: "t", _Bucket(objects).get, run) == 1
    assert run.calls == []


def test_refuses_without_database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PI_DATABASE_URL")
    assert feed_load.load(_args(tmp_path), lambda sa: "t", _Bucket({}).get, _Import()) == 1
    assert "PI_DATABASE_URL" in _status(tmp_path)["error"]


def test_prune_keeps_the_newest_run_folders(tmp_path: Path) -> None:
    for n in range(5):
        (tmp_path / "feeds/faces_ae" / f"2026-10-0{n}T000000Z-daily").mkdir(parents=True)
    feed_load.prune(tmp_path, 2)
    assert sorted(p.name[:10] for p in (tmp_path / "feeds/faces_ae").iterdir()) == [
        "2026-10-03",
        "2026-10-04",
    ]


def test_check(tmp_path: Path) -> None:
    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    fresh = {"status": "ok", "at": "2026-10-09T02:00:00Z"}
    assert feed_load.check_status(fresh, now, timedelta(hours=50)) == []
    assert len(feed_load.check_status({}, now, timedelta(hours=50))) == 2
    stale = fresh | {"at": "2026-10-01T02:00:00Z"}
    assert feed_load.check_status(stale, now, timedelta(hours=50)) == [
        "no load since 2026-10-01T02:00:00Z"
    ]
    args = _args(tmp_path)
    assert feed_load.check(args) == 1
    args.state_dir.mkdir()
    (args.state_dir / "status.json").write_text(
        json.dumps({"status": "ok", "at": f"{datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}"})
    )
    assert feed_load.check(args) == 0
    assert feed_load.main(["check", "--state-dir", str(args.state_dir)]) == 0
