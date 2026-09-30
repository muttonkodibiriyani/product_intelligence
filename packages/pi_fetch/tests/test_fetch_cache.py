from pathlib import Path

import pytest

from pi_core import Locale, content_hash_of
from pi_fetch.cache import (
    CacheEntry,
    GcsEvidenceStore,
    LocalEvidenceStore,
    MemoryValidatorCache,
    entry_from_headers,
)


def test_local_store_is_content_addressed_and_append_only(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path)
    uri = store.put(b"payload", "text/html")
    digest = content_hash_of(b"payload")
    assert uri.endswith(f"/{digest[:2]}/{digest}")
    assert store.put(b"payload", None) == uri
    assert store.get(uri) == b"payload"


def test_local_store_get_unknown(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "a")
    with pytest.raises(KeyError):
        store.get("file:///elsewhere/x")
    with pytest.raises(KeyError):
        store.get((tmp_path / "a" / "ab" / "missing").as_uri())


class FakeBlob:
    def __init__(self, bucket: "FakeBucket", name: str) -> None:
        self.bucket, self.name = bucket, name

    def exists(self) -> bool:
        return self.name in self.bucket.objects

    def upload_from_string(self, data: bytes, content_type: str) -> None:
        self.bucket.objects[self.name] = (data, content_type)
        self.bucket.uploads += 1

    def download_as_bytes(self) -> bytes:
        return self.bucket.objects[self.name][0]


class FakeBucket:
    name = "pi-evidence"

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.uploads = 0

    def blob(self, blob_name: str) -> FakeBlob:
        return FakeBlob(self, blob_name)


def test_gcs_store() -> None:
    bucket = FakeBucket()
    store = GcsEvidenceStore(bucket)
    uri = store.put(b"{}", "application/json")
    assert uri.startswith("gs://pi-evidence/evidence/")
    assert store.put(b"{}", "application/json") == uri
    assert bucket.uploads == 1
    assert store.get(uri) == b"{}"
    store.put(b"x", None)
    assert (b"x", "application/octet-stream") in bucket.objects.values()
    with pytest.raises(KeyError):
        store.get("gs://other/evidence/x")
    with pytest.raises(KeyError):
        store.get("gs://pi-evidence/evidence/zz/missing")


def test_entry_from_headers_and_conditional_headers() -> None:
    assert entry_from_headers({}, evidence_uri="u", http_status=200, content_type=None) is None
    entry = entry_from_headers(
        {"etag": '"v1"', "last-modified": "Tue, 29 Sep 2026 10:00:00 GMT"},
        evidence_uri="file:///e",
        http_status=200,
        content_type="text/html",
    )
    assert entry is not None
    assert entry.conditional_headers() == {
        "If-None-Match": '"v1"',
        "If-Modified-Since": "Tue, 29 Sep 2026 10:00:00 GMT",
    }


def test_memory_cache_keys_by_url_and_locale() -> None:
    cache = MemoryValidatorCache()
    entry = CacheEntry(
        etag='"a"', last_modified=None, evidence_uri="u", http_status=200, content_type=None
    )
    cache.put("https://s.example/", Locale.EN, entry)
    assert cache.get("https://s.example/", Locale.EN) == entry
    assert cache.get("https://s.example/", Locale.AR) is None
