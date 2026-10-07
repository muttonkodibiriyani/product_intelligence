"""Synthetic datasets for pi_similar tests, built on the committed contract example."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np

from pi_dataset import Dataset, load_dataset
from pi_match.normalise import fold
from pi_similar.text import FloatArray

EXAMPLE = Path(__file__).resolve().parents[3] / "docs" / "contracts" / "examples" / "ae-pilot.json"
NORTH, SOUTH = "example_north_ae", "example_south_ae"
DIMS = 64


@dataclass(frozen=True)
class Off:
    """One offer: a price in AED (None: never priced) and a size label."""

    price: str | None = "100.00"
    size: tuple[str, str] | None = ("50", "ml")
    early: bool = False


@dataclass(frozen=True)
class Prod:
    id: str
    name: str
    category: Sequence[str]
    offers: Mapping[str, Off]
    brand: str = "Example Beauty"
    attributes: Mapping[str, Any] = field(default_factory=dict)


def _money(amount: str) -> dict[str, Any]:
    return {"amount": amount, "minor": int(Decimal(amount) * 100), "currency": "AED"}


def dataset(products: Sequence[Prod]) -> Dataset:
    raw: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    template = raw["products"][0]["offers"][NORTH]
    days = len(raw["meta"]["dates"])
    out = []
    for p in products:
        offers = {}
        for retailer, o in p.offers.items():
            offer = json.loads(json.dumps(template))
            offer["sku"] = f"{retailer}-{p.id}"
            offer["early"] = o.early
            offer["size"] = None if o.size is None else {"value": o.size[0], "unit": o.size[1]}
            offer["series"] = {
                "price": [None if o.price is None else _money(o.price)] * days,
                "regular": None,
                "availability": None,
            }
            offer["evidence"]["source"] = f"example:{retailer}"
            offers[retailer] = offer
        out.append(
            {
                "id": p.id,
                "brand": p.brand,
                "name": p.name,
                "category": list(p.category),
                "unit": None,
                "offers": offers,
                "matches": [],
                "shades": [],
                "attributes": dict(p.attributes),
                "image": None,
            }
        )
    raw["products"] = out
    raw["notObserved"] = []
    return load_dataset(json.dumps(raw), allow_test=True)


class WordsEmbedder:
    """Deterministic bag of folded words hashed into ``DIMS`` buckets (no model, no download)."""

    model_id = "test/words@1"

    def __init__(self, salt: str = "") -> None:
        self.salt = salt

    def embed(self, texts: Sequence[str]) -> FloatArray:
        out = np.zeros((len(texts), DIMS), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in fold(text).split():
                digest = hashlib.sha256((self.salt + word).encode()).digest()
                out[row, digest[0] % DIMS] += 1.0
        return out
