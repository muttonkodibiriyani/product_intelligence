"""``pi.dataset/v3`` variants of the metrics fixture, built as JSON and validated.

``doc()`` is ``upgrade(metrics_dataset(), beauty@1)`` as JSON. ``split_shop_a`` turns ``shop_a``
into two contexts, ``WEB`` (online) and ``APP`` (delivery by default), every ``shop_a`` offer keyed
by ``a-<product id>``; the ``APP_PRODUCTS`` offers are copied into ``APP`` with the same key. A
beauty context is online-only, so splits go with ``profile(..., "food_menu")``.
"""

from __future__ import annotations

import copy
from typing import Any

from metrics_fixture import A, metrics_dataset
from pi_dataset import DatasetV3
from pi_metrics import view

WEB, APP = "shop_a_web", "shop_a_app"
APP_PRODUCTS = ("p01", "p02", "p03", "p04", "p05", "p06", "p10", "p12")
Doc = dict[str, Any]


def doc() -> Doc:
    upgraded = view.as_v3(metrics_dataset()).model_dump(mode="json", by_alias=True)
    return copy.deepcopy(upgraded)


def load(d: Doc) -> DatasetV3:
    return DatasetV3.model_validate(d)


def profile(d: Doc, name: str, *, labels_comparable: bool = True) -> Doc:
    """An uncommitted profile (only beauty@1 is committed; the validator accepts the rest)."""
    d["meta"]["vertical"] = name
    d["meta"]["profile"] = {
        "name": name,
        "version": 1,
        "sizeLabelsComparable": labels_comparable,
        "sizeSystemRequired": False,
    }
    return d


def _context(cid: str, channel: str) -> Doc:
    return {"id": cid, "retailer": A, "channel": channel, "location": None, "label": {"en": cid}}


def split_shop_a(d: Doc, *, app_channel: str = "delivery") -> Doc:
    contexts = [c for c in d["meta"]["contexts"] if c["id"] != A]
    d["meta"]["contexts"] = [_context(WEB, "online"), _context(APP, app_channel), *contexts]
    for product in d["products"]:
        offers = product["offers"]
        if A not in offers:
            continue
        offer = offers.pop(A)
        offer["evidence"] |= {"itemKey": f"a-{product['id']}", "itemKeyKind": "sku"}
        offers[WEB] = offer
        if product["id"] in APP_PRODUCTS:
            offers[APP] = copy.deepcopy(offer)
    return d


def offer(d: Doc, product_id: str, context_id: str) -> Doc:
    found: Doc = next(p for p in d["products"] if p["id"] == product_id)["offers"][context_id]
    return found


def size(value: str | None, unit: str | None, label: str | None, system: str | None = None) -> Doc:
    return {"value": value, "unit": unit, "label": label, "system": system}
