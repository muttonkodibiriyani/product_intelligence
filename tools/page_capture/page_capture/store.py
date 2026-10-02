"""Output: a GCS bucket or a local directory (``file:<dir>``), plus batched JSONL parts."""

from __future__ import annotations

import gzip
import json
import os
from collections.abc import Callable
from typing import Any

GS = "gs://"


def split_gs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith(GS) or "/" not in uri[len(GS) :]:
        raise ValueError(f"not a gs://bucket/object URI: {uri!r}")
    bucket, _, name = uri[len(GS) :].partition("/")
    return bucket, name


class Store:
    def __init__(self, bucket: str, prefix: str) -> None:
        self.local = bucket.removeprefix("file:") if bucket.startswith("file:") else None
        self.bucket_name = bucket
        self.prefix = prefix.strip("/")
        self._client: Any = None

    def _gcs(self) -> Any:
        if self._client is None:
            from google.cloud import storage  # noqa: PLC0415 - only in the cloud job

            self._client = storage.Client()
        return self._client

    def uri(self, name: str) -> str:
        if self.local is not None:
            return os.path.join(self.local, self.prefix, name)
        return f"{GS}{self.bucket_name}/{self.prefix}/{name}"

    def put(self, name: str, data: bytes, *, gz: bool = True, content_type: str = "") -> str:
        """Write one object under the prefix; returns the object name relative to the prefix."""
        body = gzip.compress(data) if gz else data
        if self.local is not None:
            path = os.path.join(self.local, self.prefix, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(body)
            return name
        blob = self._gcs().bucket(self.bucket_name).blob(f"{self.prefix}/{name}")
        blob.upload_from_string(
            body, content_type=content_type or ("application/gzip" if gz else "")
        )
        return name

    def exists(self, name: str) -> bool:
        if self.local is not None:
            return os.path.exists(os.path.join(self.local, self.prefix, name))
        return bool(self._gcs().bucket(self.bucket_name).blob(f"{self.prefix}/{name}").exists())

    def read_uri(self, uri: str) -> bytes:
        """Bytes of a ``gs://bucket/name`` object or of a local file path."""
        if uri.startswith(GS):
            bucket, name = split_gs_uri(uri)
            data: bytes = self._gcs().bucket(bucket).blob(name).download_as_bytes()
            return data
        with open(uri, "rb") as fh:
            return fh.read()


class Parts:
    """Batched JSONL streams: ``<stream>/part-NNNN.jsonl.gz``."""

    def __init__(self, store: Store, batch: int = 100, on_flush: Callable[[], None] | None = None):
        self.store = store
        self.batch = batch
        self.on_flush = on_flush
        self.buf: dict[str, list[dict[str, Any]]] = {}
        self.parts: dict[str, int] = {}

    def emit(self, stream: str, rec: dict[str, Any]) -> None:
        self.buf.setdefault(stream, []).append(rec)
        if len(self.buf[stream]) >= self.batch:
            self.flush(stream)

    def flush(self, stream: str) -> str | None:
        recs = self.buf.get(stream) or []
        if not recs:
            return None
        n = self.parts.get(stream, 0)
        data = "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in recs)
        name = self.store.put(f"{stream}/part-{n:04d}.jsonl.gz", data.encode())
        self.parts[stream] = n + 1
        self.buf[stream] = []
        if self.on_flush is not None:
            self.on_flush()
        return name

    def flush_all(self) -> None:
        for stream in list(self.buf):
            self.flush(stream)
