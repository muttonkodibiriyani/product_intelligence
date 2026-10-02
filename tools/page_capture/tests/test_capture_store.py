"""Local file store and batched parts."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from page_capture import store


def test_split_gs_uri() -> None:
    assert store.split_gs_uri("gs://b/p/x.json") == ("b", "p/x.json")
    with pytest.raises(ValueError, match="gs://"):
        store.split_gs_uri("gs://bucket-only")
    with pytest.raises(ValueError, match="gs://"):
        store.split_gs_uri("/local/path")


def test_local_put_exists_read(tmp_path: Path) -> None:
    s = store.Store(f"file:{tmp_path}", "/run1/")
    assert s.uri("a.json") == str(tmp_path / "run1" / "a.json")
    assert s.put("a.json", b'{"x":1}', gz=False) == "a.json"
    assert s.put("raw/b.txt.gz", b"hello") == "raw/b.txt.gz"
    assert s.exists("a.json")
    assert not s.exists("missing")
    assert gzip.decompress((tmp_path / "run1" / "raw" / "b.txt.gz").read_bytes()) == b"hello"
    assert s.read_uri(str(tmp_path / "run1" / "a.json")) == b'{"x":1}'


def test_gcs_uri_and_lazy_client() -> None:
    s = store.Store("bucket", "pre")
    assert s.local is None
    assert s.uri("x") == "gs://bucket/pre/x"


def test_parts_batch_and_flush(tmp_path: Path) -> None:
    s = store.Store(f"file:{tmp_path}", "r")
    flushes: list[int] = []
    parts = store.Parts(s, batch=2, on_flush=lambda: flushes.append(1))
    parts.emit("pages", {"n": 1})
    assert parts.flush("empty") is None
    assert not (tmp_path / "r" / "pages").exists()
    parts.emit("pages", {"n": 2, "when": object()})  # default=str keeps odd values
    assert (tmp_path / "r" / "pages" / "part-0000.jsonl.gz").exists()
    parts.emit("pages", {"n": 3})
    parts.emit("images", {"n": 4})
    parts.flush_all()
    assert flushes == [1, 1, 1]
    lines = gzip.decompress((tmp_path / "r" / "pages" / "part-0001.jsonl.gz").read_bytes())
    assert json.loads(lines.decode()) == {"n": 3}
    assert (tmp_path / "r" / "images" / "part-0000.jsonl.gz").exists()


def test_file_ledger_store_versions_by_size_and_mtime(tmp_path: Path) -> None:
    path = str(tmp_path / "ledger.json")
    fs = store.FileLedgerStore(path)
    assert fs.load() is None
    (tmp_path / "ledger.json").write_bytes(b'{"used_bytes": 0}')
    got = fs.load()
    assert got is not None
    data, token = got
    assert data == b'{"used_bytes": 0}'
    assert fs.save(b'{"used_bytes": 1}', token)
    assert not fs.save(b'{"used_bytes": 2}', token)  # stale token: the file moved on
    got2 = fs.load()
    assert got2 is not None
    assert got2[0] == b'{"used_bytes": 1}'


class _Blob:
    def __init__(self, parent: _FakeGcs, name: str) -> None:
        self.parent, self.name = parent, name
        self.generation: int | None = None

    def exists(self) -> bool:
        return self.name in self.parent.objects

    def reload(self) -> None:
        self.generation = self.parent.objects[self.name][1]

    def download_as_bytes(self, if_generation_match: int) -> bytes:
        data, gen = self.parent.objects[self.name]
        assert gen == if_generation_match
        return data

    def upload_from_string(self, data: bytes, content_type: str, if_generation_match: int) -> None:
        current = self.parent.objects.get(self.name)
        if current is not None and current[1] != if_generation_match:
            raise _PreconditionError("generation mismatch")
        if self.name == "ledgers/broken.json":
            raise RuntimeError("storage down")
        self.parent.objects[self.name] = (data, if_generation_match + 1)


class _PreconditionError(Exception):
    code = store.PRECONDITION_FAILED


class _Bucket:
    def __init__(self, parent: _FakeGcs) -> None:
        self.parent = parent

    def blob(self, name: str) -> _Blob:
        return _Blob(self.parent, name)


class _FakeGcs:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, int]] = {}

    def bucket(self, name: str) -> _Bucket:
        return _Bucket(self)


def test_gcs_ledger_store_uses_generation_preconditions() -> None:
    gcs = _FakeGcs()
    ls = store.GcsLedgerStore("gs://b/ledgers/proxy.json", client=gcs)
    assert ls.load() is None
    gcs.objects["ledgers/proxy.json"] = (b"{}", 7)
    got = ls.load()
    assert got == (b"{}", 7)
    assert ls.save(b'{"a":1}', 7)
    assert gcs.objects["ledgers/proxy.json"] == (b'{"a":1}', 8)
    assert not ls.save(b'{"a":2}', 7)
    with pytest.raises(RuntimeError, match="storage down"):  # anything but 412 propagates
        store.GcsLedgerStore("gs://b/ledgers/broken.json", client=gcs).save(b"x", 0)
    assert isinstance(store.ledger_store("gs://b/x"), store.GcsLedgerStore)
    assert isinstance(store.ledger_store("ledgers/x.json"), store.FileLedgerStore)
