"""Image-similarity signal for cross-retailer matching (matching spec, Signals 3).

Supporting evidence and a candidate source only: equal packshots are reused across sizes,
EDP vs EDT, minis and refills, so an image never overrides a hard rule. See ``pi_image.cli``.
"""

from pi_image.candidates import generate
from pi_image.model import FetchStatus, ImageRef, ImageSignal, ImageStatus, ListingImage, Via
from pi_image.pipeline import Analysis, analyse, embeddings

__all__ = [
    "Analysis",
    "FetchStatus",
    "ImageRef",
    "ImageSignal",
    "ImageStatus",
    "ListingImage",
    "Via",
    "analyse",
    "embeddings",
    "generate",
]
