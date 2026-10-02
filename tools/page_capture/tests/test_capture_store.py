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
