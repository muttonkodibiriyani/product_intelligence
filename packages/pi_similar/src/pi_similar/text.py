"""The text-embedding seam. Tests use a fixed fake; offline runs plug in BGE-M3 (local CPU)."""

from collections.abc import Sequence
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float32]


class TextEmbedder(Protocol):
    """Maps texts to vectors; ``model_id`` names the model and revision exactly."""

    @property
    def model_id(self) -> str: ...

    def embed(self, texts: Sequence[str]) -> FloatArray:
        """One row per text, any scale (callers normalise)."""
        ...


def unit_rows(vectors: FloatArray) -> FloatArray:
    """Rows scaled to unit length in float64 (a float32 norm under- and overflows); zero stays 0."""
    wide = vectors.astype(np.float64)
    norms = np.linalg.norm(wide, axis=1, keepdims=True)
    return (wide / np.where(norms == 0, 1, norms)).astype(np.float32)
