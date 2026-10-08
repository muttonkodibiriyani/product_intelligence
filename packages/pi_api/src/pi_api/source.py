"""Validated, versioned dataset snapshots in memory (design §3).

Each configured object is loaded, validated with ``pi_dataset`` and swapped in atomically. A
document that fails validation is never served: the previous good one stays live, and with none
the API answers ``503 data_unavailable``. Generation checks run at most every
``refresh_seconds``, in a background thread, so a request never waits on storage after startup.

A path is served whole, or (ADR-0010) a source is assigned a path: then only that source's part
of the file is read, and the assigned sources of one scope are composed into one view
(``pi_dataset.compose``). Composed views are rebuilt only when every assigned file has a good
generation; until then the previous view stays live, and with none they are not served.

``matches`` (ADR-0012 §6) names a ``pi.matches/v1`` file applied to the composed view of its
scope (``pi_api.matches``); views of other scopes are composed without it. A new generation that
does not validate is ignored (the last good one stays applied; until one validates, the views are
composed without it), and one whose vertical is not its view's leaves the previous views live.

Every new generation is checked against the memory rule (``pi_dataset.gate``, pi-api-deploy §6)
before it is parsed: the decompressed bodies of every file held, this one in place of its own
path's current generation, at ``memory_mib`` (``PI_API_MEMORY_MIB``). A set over the fit loads
only when its largest body's ``admission_sha256`` is in ``admitted`` (``PI_API_ADMITTED``, baked
in at deploy from infra/pi-api/admission/) and the other files are within its record. A refused
generation fails like one that does not validate, so the last good one stays live; at cold start
the path is not served and the others are (it is retried once after them, so path order does
not decide). A new over-the-rule export therefore needs a re-measure, a new record and a new
revision.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import cached_property
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

from pi_api.content import packed
from pi_api.dq import Imported, imported_view
from pi_api.floor import FloorView, floor_view
from pi_api.ids import ProductIds, product_ids
from pi_api.matches import apply
from pi_dataset import DatasetError, DatasetV3, ProductV3, admission_sha256, load_any
from pi_dataset.compose import SourceInfo, compose, latest, only, source_infos
from pi_dataset.gate import DEFAULT_MEMORY_MIB, refusal
from pi_match.matchfile import MatchFile
from pi_metrics.view import as_v3

if TYPE_CHECKING:
    from pi_api.catalog import Families

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
    #: For latest-date reads: ``dataset`` with each stale source at its own last date.
    latest: DatasetV3 | None = None
    #: The sources whose own last date is before the view's (``pi_dataset.compose.latest``).
    stale: tuple[SourceInfo, ...] = field(default=())
    #: What the floor withheld in ``latest``: its flags mark latest-date reads (``current``).
    latest_floor: FloorView | None = None
    #: Merged products' old ids -> their product now (``pi_api.matches``).
    aliases: Mapping[str, str] = field(default_factory=dict)

    @property
    def unverified(self) -> frozenset[str]:
        """Context ids whose was-prices are withheld as unverified: promotions there are withheld
        (``pi_api.dq.WAS_PRICE_WITHHELD``; none since API 1.13.0)."""
        return frozenset(c for shop in self.imported if shop.withheld for c in shop.contexts)

    @property
    def imported_contexts(self) -> frozenset[str]:
        """Context ids of imported retailers: served as a dated snapshot, never the default."""
        return frozenset(c for shop in self.imported for c in shop.contexts)

    @cached_property
    def ids(self) -> ProductIds:
        """Current and old product ids (``pi_api.ids``), built once per generation at load."""
        return product_ids(self.dataset, self.aliases)

    @cached_property
    def families(self) -> Families:
        """Offers by (context, retailer family), for a product's other sizes; built once per
        generation, on the first product read."""
        from pi_api.catalog import family_index  # noqa: PLC0415 - avoids an import cycle

        return family_index(self.dataset)

    @property
    def current(self) -> DatasetV3:
        """The dataset for a latest-date read: ``latest`` if a source is stale."""
        return self.dataset if self.latest is None else self.latest

    @property
    def current_floor(self) -> FloorView:
        """The floor view of ``current``: a stale source's flags are as of its own last date."""
        return self.floor if self.latest_floor is None else self.latest_floor

    @cached_property
    def latest_products(self) -> Mapping[str, ProductV3]:
        """``latest``'s products by id, built once per generation at load (empty without it)."""
        return {} if self.latest is None else {p.id: p for p in self.latest.products}

    def as_of(self, product: ProductV3) -> ProductV3:
        """``product`` in the latest-date view: each stale source at its own last date (ADR-0010).

        ``pi_dataset.compose.latest`` keeps every product, so one missing there is a bug in the
        view, never a not-found: it raises ``AsOfViewError`` (a 500) rather than guess.
        """
        if self.latest is None:
            return product
        found = self.latest_products.get(product.id)
        if found is None:
            raise AsOfViewError(product.id)
        return found

    @property
    def markets(self) -> tuple[str, ...]:
        return tuple(m.country for m in self.dataset.meta.markets)

    @property
    def scope(self) -> str:
        return self.dataset.meta.scope


class AsOfViewError(RuntimeError):
    """A product of the served view is missing from its latest-date view (an internal error)."""

    def __init__(self, product_id: str) -> None:
        super().__init__(f"product {product_id!r} is not in the latest-date view")


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
    return as_v3(load_any(data, allow_test=allow_test))


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
        matches: str | None = None,
        pack_content: bool = True,
        admitted: Mapping[str, int] = MappingProxyType({}),
        memory_mib: int = DEFAULT_MEMORY_MIB,
    ) -> None:
        """``paths`` are served whole; ``assigned`` maps a source (retailer id) to its path;
        ``matches`` is the match file applied to the composed views. ``pack_content`` keeps
        offer content compressed in memory (``pi_api.content``); off only to compare.
        ``admitted`` and ``memory_mib``: the memory rule's admission records and instance size."""
        self._admitted = dict(admitted)
        self._memory_mib = memory_mib
        #: Each good generation's decompressed size and ``admission_sha256``: what the rule counts.
        self._bodies: dict[str, tuple[int, str]] = {}
        #: Paths whose last new generation the rule refused.
        self._refused: set[str] = set()
        self._pack_content = pack_content
        self._matches_path = matches
        #: The latest good match file and its generation.
        self._matches: tuple[MatchFile, str] | None = None
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
        self._refused.clear()
        paths = list(dict.fromkeys((*self._paths, *self._assigned.values())))
        for path in paths:
            changed |= self._take(path)
        if changed:  # one retry: a refusal at cold start must not depend on path order
            for path in [p for p in paths if p in self._refused and p not in self._files]:
                changed |= self._take(path)
        if self._matches_path is not None and self._load_matches(self._matches_path):
            changed = True
        if not changed:
            return
        served = dict(self._served)
        groups = self._composed() if self._assigned else None
        with self._lock:
            kept = {k: v for k, v in self._loaded.items() if k not in self._paths}
            self._loaded = {**served, **(kept if groups is None else groups)}  # one swap

    def _take(self, path: str) -> bool:
        loaded = self._load(path)
        if loaded is None:
            return False
        self._files[path] = loaded
        if path in self._paths:
            self._served[path] = _with_ids(_corrected(loaded))
        return True

    def _load(self, path: str) -> Loaded | None:
        """The path's new generation, or ``None`` when unchanged or not loadable."""
        current = self._files.get(path)
        try:
            if current is not None and self._store.generation(path) == current.generation:
                return None
            data, generation = self._store.read(path)
            body = _gunzip(data, MAX_DATASET_BYTES) if data.startswith(_GZIP_MAGIC) else data
            stats = (len(body), admission_sha256(body))
            why = refusal({**self._bodies, path: stats}, self._admitted, self._memory_mib)
            if why is not None:
                self._refused.add(path)
                kept = "UNAVAILABLE" if current is None else f"kept at {current.generation}"
                log.error(
                    "MEMORY RULE: dataset %s generation %s REFUSED, %s: %s",
                    path,
                    generation,
                    kept,
                    why,
                )
                return None
            # Upgraded here, off the request path; a v2 that can't be is not loaded.
            dataset = parse(body, allow_test=self._allow_test)
            if self._pack_content:
                dataset = packed(dataset)
        except (DatasetError, ValueError, OSError, zlib.error) as error:
            log.warning("dataset %s not loaded: %s", path, type(error).__name__)
            return None
        except Exception:  # storage client errors: keep serving what we have
            log.exception("dataset %s: storage error", path)
            return None
        log.info("dataset %s loaded at generation %s", path, generation)
        self._bodies[path] = stats
        return Loaded(path, dataset, generation, source_infos(dataset))

    def _load_matches(self, path: str) -> bool:
        """Whether a new good generation of the match file was loaded."""
        try:
            if self._matches is not None and self._store.generation(path) == self._matches[1]:
                return False
            data, generation = self._store.read(path)
            if data.startswith(_GZIP_MAGIC):
                data = _gunzip(data, MAX_DATASET_BYTES)
            file = MatchFile.model_validate_json(data)
        except (ValueError, OSError, zlib.error) as error:
            log.warning("match file %s not loaded: %s", path, type(error).__name__)
            return False
        except Exception:  # storage client errors: keep serving what we have
            log.exception("match file %s: storage error", path)
            return False
        log.info("match file %s loaded at generation %s", path, generation)
        self._matches = (file, generation)
        return True

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
            matches = self._matches
            if matches is not None and matches[0].scope not in by_scope:
                log.warning("match file is for scope %r: no view of it", matches[0].scope)
            views = {
                f"scope:{scope}": _with_ids(
                    _view(parts, matches if matches and matches[0].scope == scope else None),
                    f"scope:{scope}",
                )
                for scope, parts in by_scope.items()
            }
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


def _view(parts: list[tuple[str, Loaded]], matches: tuple[MatchFile, str] | None = None) -> Loaded:
    """The parts of one scope as one view, with a generation that changes with any part's (and
    the match file's, when one applies)."""
    composed = compose([p.dataset for _, p in parts])
    if composed.merged_ids:
        log.info("per-source view: %d product ids merged across files", len(composed.merged_ids))
    stamp = "|".join(f"{label}@{p.generation}" for label, p in parts)
    aliases: Mapping[str, str] = {}
    if matches is not None:
        applied = apply(composed.dataset, matches[0])  # MatchFileError: the previous view stays
        log.info(
            "per-source view: match file %s applied: %s, %d products split",
            matches[0].generated_at,
            dict(applied.counts),
            len(applied.split),
        )
        composed = replace(composed, dataset=applied.dataset)
        aliases = applied.aliases
        stamp += f"|matches@{matches[1]}"
    generation = "c" + hashlib.sha256(stamp.encode()).hexdigest()[:16]
    path = ",".join(label for label, _ in parts)
    as_of = latest(composed)
    if as_of.stale:
        log.info("per-source view: %s read at their own last date", [s.source for s in as_of.stale])
    return _corrected(
        Loaded(
            path,
            composed.dataset,
            generation,
            composed.sources,
            latest=as_of.dataset if as_of.stale else None,
            stale=as_of.stale,
            aliases=aliases,
        )
    )


def _with_ids(loaded: Loaded, name: str | None = None) -> Loaded:
    """``loaded`` with its product ids (``pi_api.ids``) and its latest-date index
    (``latest_products``) built now, at load, off the request path."""
    ids = loaded.ids
    loaded.latest_products  # noqa: B018 - builds the cached index
    log.info(
        "dataset %s loaded at generation %s: %d old product ids, %d dropped as "
        "ambiguous, %d pairs with hashed or ambiguous ids (their members' old ids can't be "
        "found)",
        name or loaded.path,
        loaded.generation,
        len(ids.aliases),
        ids.dropped,
        ids.opaque_pairs,
    )
    return loaded


def _corrected(loaded: Loaded) -> Loaded:
    """The view as served: read-time views ``pi_api.floor``, then ``pi_api.dq`` (the file is
    unchanged).

    The latest-date view (``latest``) gets the same correction, so a stale source's read never
    brings back what the view withholds. A collected source's ``cutoff`` is its own latest
    capture (``source_infos``); one without offers would fall back to the file's, so it is capped
    at the served (collected) cutoff and never reads as the import time.
    """
    floored, floor = floor_view(loaded.dataset)
    dataset, imported = imported_view(floored)
    current, latest_floor = None, None
    if loaded.latest is not None:
        latest, latest_floor = floor_view(loaded.latest)
        current = imported_view(latest)[0]
    if not imported:
        return replace(
            loaded, dataset=dataset, floor=floor, latest=current, latest_floor=latest_floor
        )
    shops = {shop.retailer for shop in imported}
    cutoff = dataset.meta.cutoff
    sources = tuple(
        s if s.source in shops or s.cutoff <= cutoff else s.model_copy(update={"cutoff": cutoff})
        for s in loaded.sources
    )
    return replace(
        loaded,
        dataset=dataset,
        imported=imported,
        floor=floor,
        sources=sources,
        latest=current,
        latest_floor=latest_floor,
    )
