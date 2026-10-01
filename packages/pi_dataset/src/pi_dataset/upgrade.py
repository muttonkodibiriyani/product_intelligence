"""``upgrade(v2, profile) -> v3``: the only path from ``pi.dataset/v2`` to ``v3`` (ADR-0008 §0, §4).

Pure and deterministic, but not total: it fails loudly (``UpgradeError``) rather than drop data.
Per the ADR-0008 §4 table it sets ``schema``, ``meta.profile`` and ``meta.attributeSet`` from the
profile, one online, location-less context per retailer with the retailer's id (so every v2 offer
key is a valid context id), ``label``/``system`` ``null`` on sizes, empty offer attributes, ``null``
item keys and ``null`` ``notObserved[].context``. Everything else is copied unchanged.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from pi_core import Channel
from pi_dataset.models import Dataset
from pi_dataset.profiles import AttributeLevel, ProfileDeclaration
from pi_dataset.v3 import SCHEMA_ID_V3, DatasetV3


class UpgradeError(ValueError):
    """The v2 document can't be expressed under this profile without losing data."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("cannot upgrade to pi.dataset/v3: " + "; ".join(errors))


def upgrade(v2: Dataset, profile: ProfileDeclaration) -> DatasetV3:
    if v2.meta.vertical != profile.name:
        msg = f"meta.vertical {v2.meta.vertical} is not profile {profile.ref}"
        raise UpgradeError([msg])
    product_keys = {a.key for a in profile.attribute_set if a.level is AttributeLevel.PRODUCT}
    undeclared = [
        f"products.{p.id}.attributes.{key}: not declared by {profile.ref}"
        for p in v2.products
        for key in sorted(p.attributes)
        if key not in product_keys
    ]
    if undeclared:
        raise UpgradeError(undeclared)
    doc = v2.model_dump(mode="json", by_alias=True)
    doc["schema"] = SCHEMA_ID_V3
    meta = doc["meta"]
    meta["profile"] = profile.info().model_dump(mode="json", by_alias=True)
    meta["attributeSet"] = [a.model_dump(mode="json", by_alias=True) for a in profile.attribute_set]
    meta["contexts"] = [_context(v2, r.id, r.name) for r in v2.meta.retailers]
    for product in doc["products"]:
        for offer in product["offers"].values():
            if offer["size"] is not None:
                offer["size"] |= {"label": None, "system": None}
            offer["evidence"] |= {"itemKey": None, "itemKeyKind": None}
            offer["attributes"] = {}
    for window in doc["notObserved"]:
        window["context"] = None
    try:
        return DatasetV3.model_validate_json(json.dumps(doc), strict=True)
    except ValidationError as exc:
        raise UpgradeError(
            [f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()]
        ) from exc


def _context(v2: Dataset, retailer_id: str, name: str) -> dict[str, Any]:
    locale = v2.market_of(retailer_id).locales[0]
    return {
        "id": retailer_id,
        "retailer": retailer_id,
        "channel": str(Channel.ONLINE),
        "location": None,
        "label": {locale: name},
    }
