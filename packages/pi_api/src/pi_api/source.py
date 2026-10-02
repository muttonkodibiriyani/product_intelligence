"""Validated, versioned dataset snapshots in memory (design §3).

Each configured object is loaded, validated with ``pi_dataset`` and swapped in atomically. A
document that fails validation is never served: the previous good one stays live, and with none
the API answers ``503 data_unavailable``. Generation checks run at most every
``refresh_seconds``, in a background thread, so a request never waits on storage after startup.

A path is served whole, or (ADR-0010) a source is assigned a path: then only that source's part
of the file is read, and the assigned sources of one scope are composed into one view
(``pi_dataset.compose``). Composed views are rebuilt only when every assigned file has a good
generation; until then the previous view stays live, and with none they are not served.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from pi_api.dq import Imported, imported_view
from pi_api.floor import FloorView, floor_view
from pi_dataset import DatasetError, DatasetV3, load_any
from pi_dataset.compose import SourceInfo, compose, only, source_infos
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
    #: Each source with its own file's cutoff, dates and capabilities.
    sources: tuple[SourceInfo, ...] = field(default=())
    #: Imported retailers the served ``dataset`` was corrected for at load (``pi_api.dq``).
    imported: tuple[Imported, ...] = ()
    #: Prices at or below 0.01 the served ``dataset`` withholds (``pi_api.floor``).
    floor: FloorView = field(default_factory=FloorView)

    @property
    def unverified(self) -> frozenset[str]:
        """Context ids whose was-prices are unverified: promotions there are withheld."""
        return frozenset(c for shop in self.imported for c in shop.contexts)

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
    def __init__(  # noqa: PLR0913 - store and paths, then keyword-only options
        self,
        store: ObjectStore,
        paths: Sequence[str],
        refresh_seconds: int = 60,
        clock: Callable[[], float] = time.monotonic,
        *,
        allow_test: bool = False,
        assigned: Mapping[str, str] = MappingProxyType({}),
    ) -> None:
        """``paths`` are served whole; ``assigned`` maps a source (retailer id) to its path."""
        self._allow_test = allow_test
        self._store = store
        self._paths = tuple(paths)
        self._assigned = dict(assigned)
        self._refresh = refresh_seconds
        self._clock = clock
        #: The latest good generation of every configured path.
        self._files: dict[str, Loaded] = {}
        #: Each path's file as served: its latest good generation with the dq view applied.
        self._served: dict[str, Loaded] = {}
        #: What is served: whole paths by path, composed views by scope.
        self._loaded: dict[str, Loaded] = {}
        self._lock = threading.Lock()
        self._checked = -float("inf")
        self._running = False

    def load_all(self) -> None:
        """Checks every path now, loading any new generation. Never raises for bad data."""
        changed = False
        for path in dict.fromkeys((*self._paths, *self._assigned.values())):
            loaded = self._load(path)
            if loaded is not None:
                self._files[path] = loaded
                if path in self._paths:
                    self._served[path] = _corrected(loaded)
                changed = True
        if not changed:
            return
        served = dict(self._served)
        groups = self._composed() if self._assigned else None
        with self._lock:
            kept = {k: v for k, v in self._loaded.items() if k not in self._paths}
            self._loaded = {**served, **(kept if groups is None else groups)}  # one swap

    def _load(self, path: str) -> Loaded | None:
        """The path's new generation, or ``None`` when unchanged or not loadable."""
        current = self._files.get(path)
        try:
            if current is not None and self._store.generation(path) == current.generation:
                return None
            data, generation = self._store.read(path)
            # Upgraded here, off the request path; a v2 that can't be is not loaded.
            dataset = parse(data, allow_test=self._allow_test)
        except (DatasetError, ValueError, OSError, zlib.error) as error:
            log.warning("dataset %s not loaded: %s", path, type(error).__name__)
            return None
        except Exception:  # storage client errors: keep serving what we have
            log.exception("dataset %s: storage error", path)
            return None
        log.info("dataset %s loaded at generation %s", path, generation)
        return Loaded(path, dataset, generation, source_infos(dataset))

    def _composed(self) -> dict[str, Loaded] | None:
        """One view per scope of the assigned sources; ``None`` keeps the previous views."""
        missing = sorted(s for s, p in self._assigned.items() if p not in self._files)
        if missing:
            log.warning("per-source view not rebuilt: no good file yet for %s", missing)
            return None
        by_path: dict[str, list[str]] = {}
        for source, path in self._assigned.items():
            by_path.setdefault(path, []).append(source)
        by_scope: dict[str, list[tuple[str, Loaded]]] = {}
        try:
            for path, sources in by_path.items():
                file = self._files[path]
                part = Loaded(path, only(file.dataset, sources), file.generation)
                label = ",".join(f"{s}={path}" for s in sources)
                by_scope.setdefault(part.scope, []).append((label, part))
            views = {f"scope:{scope}": _view(parts) for scope, parts in by_scope.items()}
        except ValueError as error:  # CompositionError, or the composed view fails validation
            log.error("per-source view not rebuilt: %s", error)
            return None
        return views

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
        return (
            *(loaded[p] for p in self._paths if p in loaded),
            *(v for k, v in loaded.items() if k not in self._paths),
        )

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


def _view(parts: list[tuple[str, Loaded]]) -> Loaded:
    """The parts of one scope as one view, with a generation that changes with any part's."""
    composed = compose([p.dataset for _, p in parts])
    if composed.merged_ids:
        log.info("per-source view: %d product ids merged across files", len(composed.merged_ids))
    stamp = "|".join(f"{label}@{p.generation}" for label, p in parts)
    generation = "c" + hashlib.sha256(stamp.encode()).hexdigest()[:16]
    path = ",".join(label for label, _ in parts)
    return _corrected(Loaded(path, composed.dataset, generation, composed.sources))


def _corrected(loaded: Loaded) -> Loaded:
    """The view as served: read-time views ``pi_api.floor``, then ``pi_api.dq`` (the file is
    unchanged).

    A collected source's ``cutoff`` is its own latest capture (``source_infos``); one without
    offers would fall back to the file's, so it is capped at the served (collected) cutoff and
    never reads as the import time.
    """
    floored, floor = floor_view(loaded.dataset)
    dataset, imported = imported_view(floored)
    if not imported:
        return replace(loaded, dataset=dataset, floor=floor)
    shops = {shop.retailer for shop in imported}
    cutoff = dataset.meta.cutoff
    sources = tuple(
        s if s.source in shops or s.cutoff <= cutoff else s.model_copy(update={"cutoff": cutoff})
        for s in loaded.sources
    )
    return replace(loaded, dataset=dataset, imported=imported, floor=floor, sources=sources)
