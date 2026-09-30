"""Conditional requests (ETag / If-Modified-Since) and the raw-payload evidence store.

Every payload the fetcher receives, blocked ones included, is written to an ``EvidenceStore``
under its content hash (DAT-04), so each result names the exact bytes behind it. Storage is
append-only: an existing object is never overwritten.
"""

import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from pi_core import PiModel, content_hash_of
from pi_core.types import NonEmptyStr


class EvidenceStore(Protocol):
    """Content-addressed payload storage."""

    def put(self, body: bytes, content_type: str | None) -> str:
        """Store ``body`` (idempotent) and return its URI."""
        ...

    def get(self, uri: str) -> bytes:
        """Return the payload stored at ``uri``; raise ``KeyError`` when absent."""
        ...


def _object_name(prefix: str, digest: str) -> str:
    return f"{prefix}{digest[:2]}/{digest}"


class LocalEvidenceStore:
    """Evidence on the local filesystem (dev, tests): ``file://<root>/<ab>/<sha256>``."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def put(self, body: bytes, content_type: str | None) -> str:
        """Write once under the content hash."""
        path = self._root / _object_name("", content_hash_of(body))
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(body)
            tmp.replace(path)
        return path.as_uri()

    def get(self, uri: str) -> bytes:
        """Read a ``file://`` URI written by this store."""
        prefix = self._root.as_uri() + "/"
        if not uri.startswith(prefix):
            raise KeyError(uri)
        path = self._root / uri.removeprefix(prefix)
        if not path.is_file():
            raise KeyError(uri)
        return path.read_bytes()


class GcsBlob(Protocol):
    """The subset of ``google.cloud.storage.Blob`` the GCS store uses."""

    def exists(self) -> bool: ...

    def upload_from_string(self, data: bytes, content_type: str) -> None: ...

    def download_as_bytes(self) -> bytes: ...


class GcsBucket(Protocol):
    """The subset of ``google.cloud.storage.Bucket`` the GCS store uses."""

    name: str

    def blob(self, blob_name: str) -> GcsBlob: ...


class GcsEvidenceStore:
    """Evidence in Cloud Storage: ``gs://<bucket>/<prefix><ab>/<sha256>``.

    Takes a bucket object so pi_fetch needs no Google SDK; the pipeline passes a real bucket.
    """

    def __init__(self, bucket: GcsBucket, prefix: str = "evidence/") -> None:
        self._bucket = bucket
        self._prefix = prefix

    def put(self, body: bytes, content_type: str | None) -> str:
        """Upload once under the content hash."""
        name = _object_name(self._prefix, content_hash_of(body))
        blob = self._bucket.blob(name)
        if not blob.exists():
            blob.upload_from_string(body, content_type=content_type or "application/octet-stream")
        return f"gs://{self._bucket.name}/{name}"

    def get(self, uri: str) -> bytes:
        """Download a ``gs://`` URI in this store's bucket."""
        prefix = f"gs://{self._bucket.name}/"
        if not uri.startswith(prefix):
            raise KeyError(uri)
        blob = self._bucket.blob(uri.removeprefix(prefix))
        if not blob.exists():
            raise KeyError(uri)
        return blob.download_as_bytes()


class CacheEntry(PiModel):
    """Validators from the last good response to a URL, and where its payload is stored."""

    etag: NonEmptyStr | None
    last_modified: NonEmptyStr | None
    evidence_uri: NonEmptyStr
    http_status: int
    content_type: str | None

    def conditional_headers(self) -> dict[str, str]:
        """``If-None-Match`` / ``If-Modified-Since`` for a revalidation."""
        headers: dict[str, str] = {}
        if self.etag is not None:
            headers["If-None-Match"] = self.etag
        if self.last_modified is not None:
            headers["If-Modified-Since"] = self.last_modified
        return headers


def entry_from_headers(
    headers: Mapping[str, str], *, evidence_uri: str, http_status: int, content_type: str | None
) -> CacheEntry | None:
    """A cache entry when the (lower-cased) headers carry a validator, else None."""
    etag = headers.get("etag") or None
    last_modified = headers.get("last-modified") or None
    if etag is None and last_modified is None:
        return None
    return CacheEntry(
        etag=etag,
        last_modified=last_modified,
        evidence_uri=evidence_uri,
        http_status=http_status,
        content_type=content_type,
    )


class ValidatorCache(Protocol):
    """Where the fetcher keeps ``CacheEntry`` per (URL, locale)."""

    def get(self, url: str, locale: str) -> CacheEntry | None: ...

    def put(self, url: str, locale: str, entry: CacheEntry) -> None: ...


class MemoryValidatorCache:
    """In-process ``ValidatorCache``."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], CacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, url: str, locale: str) -> CacheEntry | None:
        """The entry for (url, locale), if any."""
        with self._lock:
            return self._entries.get((url, locale))

    def put(self, url: str, locale: str, entry: CacheEntry) -> None:
        """Replace the entry for (url, locale)."""
        with self._lock:
            self._entries[(url, locale)] = entry
