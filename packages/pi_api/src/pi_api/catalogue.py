"""Optional archived SKU catalogues; authenticated by the same API wrapper as prices."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pi_api.catalog import EvidenceHosts, evidence_url
from pi_api.source import (
    MAX_DATASET_BYTES,
    AmbiguousDatasetError,
    DataUnavailableError,
    Loaded,
    NotFoundError,
    ObjectStore,
    _gunzip,
)
from pi_core.types import UtcDatetime
from pi_dataset import ContractModel
from pi_dataset.catalogue import CatalogueDataset, CatalogueRecord, SkuReference, SourceIds
from pi_dataset.text import SourceText

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadedCatalogue:
    dataset: CatalogueDataset
    generation: str


class CatalogueSource:
    """Validate before atomic replacement; a bad refresh never discards the last good copy."""

    def __init__(
        self,
        store: ObjectStore,
        paths: Sequence[str],
        refresh_seconds: int = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.store, self.paths, self.refresh_seconds, self.clock = (
            store,
            tuple(paths),
            refresh_seconds,
            clock,
        )
        self.loaded: dict[str, LoadedCatalogue] = {}
        self.lock = threading.Lock()
        self.checked = -float("inf")
        self.running = False

    def load_all(self) -> None:
        for path in self.paths:
            current = self.loaded.get(path)
            try:
                if current and self.store.generation(path) == current.generation:
                    continue
                raw, generation = self.store.read(path)
                if len(raw) > MAX_DATASET_BYTES:
                    raise ValueError("catalogue exceeds size limit")
                if raw.startswith(b"\x1f\x8b"):
                    raw = _gunzip(raw, MAX_DATASET_BYTES)
                dataset = CatalogueDataset.model_validate_json(raw)
            except Exception as error:  # Includes storage errors; keep last validated generation.
                log.warning("catalogue %s not loaded: %s", path, type(error).__name__)
                continue
            with self.lock:
                self.loaded = {**self.loaded, path: LoadedCatalogue(dataset, generation)}

    def maybe_refresh(self) -> None:
        with self.lock:
            if self.running or self.clock() - self.checked < self.refresh_seconds:
                return
            self.running, self.checked = True, self.clock()

        def run() -> None:
            try:
                self.load_all()
            finally:
                with self.lock:
                    self.running = False

        threading.Thread(target=run, name="pi-catalogue-refresh", daemon=True).start()

    def select(self, retailer: str, prices: Loaded) -> LoadedCatalogue:
        if retailer not in {c.retailer for c in prices.dataset.meta.contexts} or not self.paths:
            raise NotFoundError
        self.maybe_refresh()
        available = tuple(self.loaded.values())
        if not available:
            raise DataUnavailableError
        matches = [
            c
            for c in available
            if c.dataset.retailer == retailer
            and c.dataset.market in prices.markets
            and c.dataset.scope == prices.scope
        ]
        if not matches:
            raise NotFoundError
        if len(matches) != 1:
            raise AmbiguousDatasetError("several catalogues match this market and scope")
        return matches[0]


class CatalogueSummary(ContractModel):
    retailer: str
    generation: str
    generated_at: UtcDatetime
    imported_at: UtcDatetime
    captured_from: UtcDatetime
    captured_to: UtcDatetime
    source_sha256: str
    provenance: str
    sku_records: int
    variant_skus: int
    excluded_parent_summaries: int
    parent_child_links: int
    unresolved_skus: int
    image_assets: int
    unique_image_contents: int
    skus_with_images: int


def summary(loaded: LoadedCatalogue) -> CatalogueSummary:
    ds = loaded.dataset
    rows = tuple(ds.records.values())
    missing = {r.sku for row in rows for r in (*row.parents, *row.children)} - ds.records.keys()
    return CatalogueSummary(
        retailer=ds.retailer,
        generation=loaded.generation,
        generated_at=ds.generated_at,
        imported_at=ds.imported_at,
        captured_from=min(r.captured_at for r in rows),
        captured_to=max(r.captured_at for r in rows),
        source_sha256=ds.source_sha256,
        provenance=ds.provenance,
        sku_records=len(rows),
        variant_skus=sum(r.is_variant for r in rows),
        excluded_parent_summaries=sum(r.excluded_parent_summary for r in rows),
        parent_child_links=sum(len(r.children) for r in rows),
        unresolved_skus=len(missing),
        image_assets=len(ds.assets),
        unique_image_contents=len({a.sha256 for a in ds.assets.values()}),
        skus_with_images=sum(bool(r.image_ids) for r in rows),
    )


class GalleryImage(ContractModel):
    asset_id: str
    url: SourceText | None
    source_url: SourceText | None
    sha256: str
    width: int
    height: int
    caption: SourceText
    roles: tuple[SourceText, ...]


class RelatedSku(ContractModel):
    sku: str
    resolved: bool
    name: SourceText | None
    source_ids: SourceIds | None
    selections: tuple[SourceText, ...]
    selection_labels: tuple[SourceText, ...]


class CatalogueDetail(ContractModel):
    retailer: str
    generation: str
    imported_at: UtcDatetime
    provenance: str
    record: CatalogueRecord
    parents: tuple[RelatedSku, ...]
    children: tuple[RelatedSku, ...]
    images: tuple[GalleryImage, ...]
    duplicate_images_removed: int


def detail(loaded: LoadedCatalogue, sku: str, hosts: EvidenceHosts) -> CatalogueDetail:
    ds = loaded.dataset
    row = ds.records.get(sku)
    if row is None:
        raise NotFoundError

    def related(ref: SkuReference, parent: CatalogueRecord | None) -> RelatedSku:
        target = ds.records.get(ref.sku)
        return RelatedSku(
            sku=ref.sku,
            resolved=target is not None,
            name=target.name if target else None,
            source_ids=target.source_ids if target else None,
            selections=ref.selections,
            selection_labels=tuple(
                parent.option_values[s]
                for s in ref.selections
                if parent and s in parent.option_values
            ),
        )

    seen: set[str] = set()
    images: list[GalleryImage] = []
    for asset_id in row.image_ids:
        asset = ds.assets[asset_id]
        if asset.sha256 in seen:
            continue
        seen.add(asset.sha256)
        images.append(
            GalleryImage(
                asset_id=asset.asset_id,
                url=evidence_url(asset.url, ds.retailer, hosts),
                source_url=evidence_url(asset.source_url, ds.retailer, hosts),
                sha256=asset.sha256,
                width=asset.width,
                height=asset.height,
                caption=asset.label,
                roles=asset.roles,
            )
        )
    return CatalogueDetail(
        retailer=ds.retailer,
        generation=loaded.generation,
        imported_at=ds.imported_at,
        provenance=ds.provenance,
        record=row,
        parents=tuple(related(r, ds.records.get(r.sku)) for r in row.parents),
        children=tuple(related(r, row) for r in row.children),
        images=tuple(images),
        duplicate_images_removed=len(row.image_ids) - len(images),
    )
