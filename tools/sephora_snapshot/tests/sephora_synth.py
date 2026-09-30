"""Synthetic Sephora-shaped payloads for tests. Invented ids, names and prices only."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

AT = "2026-09-30T22:00:00+00:00"


def details(pid: str, brand: str = "Acme Beauty", name: str = "Test Serum") -> dict[str, Any]:
    return {
        "id": pid,
        "name": name,
        "currency": "AED",
        "master": {"masterId": pid},
        "c_brand": {"id": "b1", "name": brand},
        "c_breadcrumbs": [{"name": "Skincare"}, {"name": "Serums"}],
        "c_bvAverageRating": 4.5,
        "c_bvReviewCount": 12,
        "c_variantsInfo": [
            {
                "product_id": f"{pid[1:]}1",
                "c_price": 100,
                "c_salesPrice": 80,
                "c_variation_attribute_name": "30 ml",
                "c_isSizeVariationTemplate": True,
            }
        ],
        "longDescription": "dropped",
    }


def pdp_html(d: dict[str, Any]) -> str:
    rsc = json.dumps(json.dumps({"productDetails": d}, separators=(",", ":")))  # RSC chunk
    ld = json.dumps({"@type": "Product", "description": "A synthetic serum."})
    return (
        f'<html><script type="application/ld+json">{ld}</script>'
        f"<script>self.__next_f.push([1,{rsc}])</script></html>"
    )


def trpc_json(pid: str, *, in_stock: bool = True) -> list[dict[str, Any]]:
    variant = {"product_id": f"{pid[1:]}1", "inStock": in_stock, "isLowStock": False}
    return [{"result": {"data": {"json": {"c_variantsInfo": [variant]}}}}]


def write_part(root: Path, stream: str, recs: list[dict[str, Any]], n: int = 0) -> None:
    (root / stream).mkdir(parents=True, exist_ok=True)
    data = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs).encode()
    (root / stream / f"part-{n:04d}.jsonl.gz").write_bytes(gzip.compress(data))


def pdp_rec(pid: str, lang: str, d: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "url": f"https://www.sephora.me/ae-{lang}/p/test/{pid}",
        "locale": f"{lang}-AE",
        "at": AT,
        "status": 200,
        "pid": pid,
        "lang": lang,
        "extract": {"productDetails": d or details(pid), "jsonld": [{"@type": "Product"}]},
    }


def trpc_rec(pid: str, *, status: int = 200, in_stock: bool = True) -> dict[str, Any]:
    return {
        "url": f"https://www.sephora.me/api/trpc/x?{pid}",
        "locale": "en-AE",
        "at": AT,
        "status": status,
        "pid": pid,
        "json": trpc_json(pid, in_stock=in_stock),
    }
