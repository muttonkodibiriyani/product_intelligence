"""Similar / competing products across retailers (docs/design/similar-products.md).

A separate signal, never an identity match: nothing here writes a match edge, and no compare,
price-gap, index or match KPI reads ``pi.similar/v1``.
"""

from pi_similar.build import build_similar
from pi_similar.items import Department, Gender, Item, items
from pi_similar.model import SimilarFile, dump_similar, load_similar
from pi_similar.signals import WEIGHTS, WEIGHTS_VERSION, Signal, combine
from pi_similar.text import TextEmbedder

__all__ = [
    "WEIGHTS",
    "WEIGHTS_VERSION",
    "Department",
    "Gender",
    "Item",
    "Signal",
    "SimilarFile",
    "TextEmbedder",
    "build_similar",
    "combine",
    "dump_similar",
    "items",
    "load_similar",
]
