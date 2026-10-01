"""Validated, versioned dataset snapshots in memory (design §3).

Each configured object is loaded, validated with ``pi_dataset`` and swapped in atomically. A
document that fails validation is never served: the previous good one stays live, and with none
the API answers ``503 data_unavailable``. Generation checks run at most every
``refresh_seconds``, in a background thread, so a request never waits on storage after startup.
"""

from __future__ import annotations

import logging
import threading
import time
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pi_dataset import DatasetError, DatasetV3, load_any
from pi_metrics.view import as_v3

log = logging.getLogger(__name__)
_GZIP_MAGIC = b"\x1f\x8b"


class ObjectStore(Protocol):
    def generation(self, path: str) -> str:
        """The object's current generation (a metadata read, no download)."""
        ...

    def read(self, path: str) -> tuple[bytes, str]:
        """The object's bytes and the generation they belong to."""
        ...


class LocalStore:
    """A directory standing in for the bucket; the generation is the file's mtime_ns."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def _file(self, path: str) -> Path:
        return self._root / path

    def generation(self, path: str) -> str:
        return str(self._file(path).stat().st_mtime_ns)

    def read(self, path: str) -> tuple[bytes, str]:
        file = self._file(path)
        generation = self.generation(path)
        return file.read_bytes(), generation


class GcsStore:  # pragma: no cover - thin wrapper over the client; needs GCS credentials
    """Reads objects by name only: the runtime role has ``storage.objects.get`` and no list."""

    def __init__(self, bucket: str) -> None:
        from google.cloud import storage  # noqa: PLC0415 -- heavy import, only when deployed

        self._bucket = storage.Client().bucket(bucket)

    def generation(self, path: str) -> str:
        blob = self._bucket.blob(path)
        blob.reload()
        return str(blob.generation)

    def read(self, path: str) -> tuple[bytes, str]:
        blob = self._bucket.blob(path)
        blob.reload()
        generation = blob.generation
        data = blob.download_as_bytes(if_generation_match=generation)
        return data, str(generation)


@dataclass(frozen=True)
class Loaded:
    path: str
    #: Always v3: a v2 snapshot is upgraded once, at load (ADR-0008 §4).
    dataset: DatasetV3
    generation: str

    @property
    def markets(self) -> tuple[str, ...]:
        return tuple(m.country for m in self.dataset.meta.markets)

    @property
    def scope(self) -> str:
        return self.dataset.meta.scope


class DataUnavailableError(Exception):
    """No validated dataset is loaded for the request (503)."""


class NotFoundError(Exception):
    """No visible dataset matches the requested market and scope (404)."""


#: Refuse anything larger once decompressed; the UAE snapshot is a few MB.
MAX_DATASET_BYTES = 256 * 1024 * 1024


def _gunzip(data: bytes, limit: int) -> bytes:
    inflate = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    out = inflate.decompress(data, limit + 1)
    if len(out) > limit or inflate.unconsumed_tail:
        msg = f"dataset is larger than {limit} bytes once decompressed"
        raise ValueError(msg)
    return out


def parse(data: bytes, *, allow_test: bool = False, limit: int = MAX_DATASET_BYTES) -> DatasetV3:
    """A validated snapshot as v3: a ``pi.dataset/v3`` document as is, a v2 one upgraded.

    Raises ``UpgradeError`` (a ``ValueError``) for a v2 document that can't be read as v3.
    """
    if data.startswith(_GZIP_MAGIC):
        data = _gunzip(data, limit)
    if len(data) > limit:
        msg = f"dataset is larger than {limit} bytes"
        raise ValueError(msg)
    return as_v3(load_any(data.decode("utf-8"), allow_test=allow_test))


class SnapshotSource:
    def __init__(
        self,
        store: ObjectStore,
        paths: Sequence[str],
        refresh_seconds: int = 60,
        clock: Callable[[], float] = time.monotonic,
        *,
        allow_test: bool = False,
    ) -> None:
        self._allow_test = allow_test
        self._store = store
        self._paths = tuple(paths)
        self._refresh = refresh_seconds
        self._clock = clock
        self._loaded: dict[str, Loaded] = {}
        self._lock = threading.Lock()
        self._checked = -float("inf")
        self._running = False

    def load_all(self) -> None:
        """Checks every path now, loading any new generation. Never raises for bad data."""
        for path in self._paths:
            current = self._loaded.get(path)
            try:
                if current is not None and self._store.generation(path) == current.generation:
                    continue
                data, generation = self._store.read(path)
                # Upgraded here, off the request path; a v2 that can't be is not loaded.
                dataset = parse(data, allow_test=self._allow_test)
                loaded = Loaded(path=path, dataset=dataset, generation=generation)
            except (DatasetError, ValueError, OSError, zlib.error) as error:
                log.warning("dataset %s not loaded: %s", path, type(error).__name__)
                continue
            except Exception:  # storage client errors: keep serving what we have
                log.exception("dataset %s: storage error", path)
                continue
            with self._lock:
                self._loaded = {**self._loaded, path: loaded}  # one reference swap
            log.info("dataset %s loaded at generation %s", path, generation)

    def maybe_refresh(self) -> None:
        """Starts a background check if one is due; returns at once."""
        with self._lock:
            if self._running or self._clock() - self._checked < self._refresh:
                return
            self._running = True
            self._checked = self._clock()

        def run() -> None:
            try:
                self.load_all()
            finally:
                with self._lock:
                    self._running = False

        threading.Thread(target=run, name="pi-api-refresh", daemon=True).start()

    def datasets(self) -> tuple[Loaded, ...]:
        loaded = self._loaded
        return tuple(loaded[p] for p in self._paths if p in loaded)

    def select(self, market: str | None, scope: str | None) -> Loaded:
        """The one dataset for ``market``/``scope``; either may be omitted if unambiguous."""
        self.maybe_refresh()
        available = self.datasets()
        if not available:
            raise DataUnavailableError
        matches = [
            d
            for d in available
            if (market is None or market.upper() in d.markets)
            and (scope is None or scope == d.scope)
        ]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise NotFoundError
        msg = "several datasets match: pass market and scope"
        raise AmbiguousDatasetError(msg)


class AmbiguousDatasetError(ValueError):
    """More than one dataset matches; the caller must say which (422)."""
