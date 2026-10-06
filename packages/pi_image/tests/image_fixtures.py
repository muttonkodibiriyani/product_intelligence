"""Synthetic packshots for tests. The repo is public, so no retailer photo is committed: these
stand in for them and exercise the same differences (re-encoding, margin, crop, transparency)."""

import io
import random
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw


def packshot(seed: int, size: int = 256, background: str = "white") -> Image.Image:
    """A bottle-like product: body, cap and a label band; ``seed`` changes shape and colours."""
    image = Image.new("RGB", (size, size), background)
    draw = ImageDraw.Draw(image)
    w = 60 + (seed * 37) % 70
    h = 110 + (seed * 53) % 90
    x0, y0 = (size - w) // 2, size - h - 20
    body = ((seed * 71) % 200, (seed * 113) % 200, (seed * 151) % 200)
    draw.rectangle((x0, y0, x0 + w, y0 + h), fill=body)
    cap = 18 + (seed * 13) % 30
    draw.rectangle((x0 + w // 4, y0 - cap, x0 + 3 * w // 4, y0), fill=(30, 30, 30))
    band = y0 + h // 3 + (seed * 7) % (h // 3)
    draw.rectangle((x0, band, x0 + w, band + 18), fill=(240, 230, 210))
    rng = random.Random(seed)  # noqa: S311 -- a seeded "label print" for text and artwork
    for _ in range(14):
        lx = rng.randrange(x0, x0 + w - 6)
        ly = rng.randrange(y0, y0 + h - 4)
        shade = rng.randrange(0, 255)
        draw.rectangle(
            (lx, ly, lx + rng.randrange(4, 30), ly + rng.randrange(2, 12)),
            fill=(shade, shade, shade),
        )
    if seed % 2:
        draw.ellipse((x0 + 8, y0 + 8, x0 + w - 8, y0 + w - 8), outline=(250, 250, 250), width=4)
    return image


def as_bytes(image: Image.Image, fmt: str = "PNG", **kw: object) -> bytes:
    """Encode."""
    out = io.BytesIO()
    image.save(out, format=fmt, **kw)
    return out.getvalue()


def with_margin(image: Image.Image, margin: int) -> Image.Image:
    """The same picture with a wider white border (another retailer's crop)."""
    out = Image.new("RGB", (image.width + 2 * margin, image.height + 2 * margin), "white")
    out.paste(image, (margin, margin))
    return out


def transparent(image: Image.Image) -> Image.Image:
    """White background made transparent (a PNG cut-out of the same packshot)."""
    rgba = image.convert("RGBA")
    white = image.convert("L").point(lambda v: 0 if v == 255 else 255)
    rgba.putalpha(white)
    return rgba


class GridEmbedder:
    """A deterministic stand-in for SigLIP: mean colour of a 4x4 grid (48 dims)."""

    model_id = "test/grid@1"

    def __init__(self) -> None:
        self.calls: list[int] = []

    def embed(self, images: Sequence[Image.Image]) -> NDArray[np.float32]:
        self.calls.append(len(images))
        rows = [
            np.asarray(i.convert("RGB").resize((4, 4), Image.Resampling.BOX), np.float32).ravel()
            - 128.0
            for i in images
        ]
        return np.stack(rows).astype(np.float32)
