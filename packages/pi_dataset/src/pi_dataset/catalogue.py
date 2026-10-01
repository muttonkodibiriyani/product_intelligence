"""SKU identities and image galleries, separate from grouped price observations.

An archived catalogue does not advance the price dataset's cutoff. Missing linked SKUs remain
references, not invented records. Assets retain source URLs and downloaded content hashes.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from pi_core.types import UtcDatetime
from pi_dataset.models import ContractModel, ProductId, ScopeId, SourceKey
from pi_dataset.text import SourceText

Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class SourceIds(ContractModel):
    catalogue_id: SourceText | None = None
    stock_id: int | None = None
    structured_product_id: SourceText | int | None = None
    structured_id: SourceText | int | None = None
    external_id: SourceText | None = None


class SkuReference(ContractModel):
    sku: ProductId
    selections: tuple[SourceText, ...] = ()


class CatalogueImage(ContractModel):
    asset_id: ProductId
    url: SourceText
    source_url: SourceText
    sha256: Sha256
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    bytes: int = Field(gt=0)
    content_type: SourceText
    label: SourceText = ""
    roles: tuple[SourceText, ...] = ()


class CatalogueRecord(ContractModel):
    sku: ProductId
    name: SourceText
    product_type: SourceText
    is_variant: bool
    source_ids: SourceIds
    parents: tuple[SkuReference, ...] = ()
    children: tuple[SkuReference, ...] = ()
    grouping_master_sku: ProductId
    excluded_parent_summary: bool
    #: Original archived capture, never the time the metadata was normalised or published.
    captured_at: UtcDatetime
    image_ids: tuple[ProductId, ...] = ()
    option_values: dict[str, SourceText] = Field(default_factory=dict)


class CatalogueDataset(ContractModel):
    schema_version: Literal["pi.catalogue/v1"] = "pi.catalogue/v1"
    retailer: SourceKey
    market: str
    scope: ScopeId
    generated_at: UtcDatetime
    imported_at: UtcDatetime
    source_sha256: Sha256
    provenance: Literal["archived_public_website_scrape"] = "archived_public_website_scrape"
    records: dict[str, CatalogueRecord] = Field(min_length=1)
    assets: dict[str, CatalogueImage]

    @model_validator(mode="after")
    def relationships(self) -> Self:
        referenced: set[str] = set()
        for sku, row in self.records.items():
            if sku != row.sku or row.grouping_master_sku not in self.records:
                raise ValueError("record key or grouping master does not resolve")
            if row.captured_at > self.imported_at or self.imported_at > self.generated_at:
                raise ValueError("capture, import and generation timestamps are out of order")
            if len(set(row.image_ids)) != len(row.image_ids):
                raise ValueError("duplicate gallery asset reference")
            expected_parent = row.product_type == "configurable" and any(
                child.sku in self.records for child in row.children
            )
            if row.excluded_parent_summary != expected_parent:
                raise ValueError("parent exclusion does not match captured child records")
            referenced.update(row.image_ids)
            for links, inverse in ((row.parents, "children"), (row.children, "parents")):
                keys = [link.sku for link in links]
                if sku in keys or len(set(keys)) != len(keys):
                    raise ValueError("self link or duplicate SKU relationship")
                for link in links:
                    other = self.records.get(link.sku)
                    if other and sku not in {r.sku for r in getattr(other, inverse)}:
                        raise ValueError("present SKU relationship is not reciprocal")
        if referenced != self.assets.keys():
            raise ValueError("gallery assets are missing or unreferenced")
        if any(key != image.asset_id for key, image in self.assets.items()):
            raise ValueError("asset key does not match asset ID")
        return self
