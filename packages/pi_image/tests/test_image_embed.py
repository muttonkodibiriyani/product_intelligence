import hashlib
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays
from PIL import Image

from image_fixtures import GridEmbedder, packshot
from pi_image.embed import (
    SIGLIP_BASE,
    EmbeddingCache,
    FloatArray,
    OnnxModel,
    SiglipOnnx,
    embed_all,
    l2_normalise,
    model_file,
    siglip_pixels,
)


@given(
    arrays(
        np.float32,
        st.tuples(st.integers(1, 5), st.integers(1, 8)),
        elements=st.floats(width=32, allow_nan=False, allow_infinity=False),
    )
)
@example(np.array([[7.27e-23]], dtype=np.float32))  # float32 norm underflowed: length 0.971
@example(np.array([[3e38, 3e38]], dtype=np.float32))  # float32 norm overflows to inf
def test_l2_normalise_gives_unit_or_zero_rows(vectors: FloatArray) -> None:
    norms = np.linalg.norm(l2_normalise(vectors), axis=1)
    for row, norm in zip(vectors, norms, strict=True):
        assert norm == 0 if not row.any() else np.isclose(norm, 1.0, atol=1e-4)


def test_embed_all_batches_dedupes_and_caches(tmp_path: Path) -> None:
    model = GridEmbedder()
    cache = EmbeddingCache(tmp_path, model.model_id)
    loads: list[str] = []

    def item(url: str, seed: int) -> tuple[str, Callable[[], Image.Image]]:
        def load() -> Image.Image:
            loads.append(url)
            return packshot(seed)

        return url, load

    items = [item("u1", 1), item("u2", 2), item("u1", 1), item("u3", 3)]
    out = embed_all(items, model, cache, batch=2)
    assert sorted(out) == ["u1", "u2", "u3"]
    assert model.calls == [2, 1]
    assert loads == ["u1", "u2", "u3"]
    assert out["u1"].dtype == np.float32
    other = EmbeddingCache(tmp_path, "another/model@2")
    assert other.get("u1") is None  # a model change never reuses vectors
    cached = EmbeddingCache(tmp_path, model.model_id).get("u1")
    assert cached is not None
    assert np.array_equal(cached, out["u1"])


def test_siglip_pixels_shape_and_range() -> None:
    pixels = siglip_pixels([packshot(1), Image.new("L", (10, 30), 0)], 32)
    assert pixels.shape == (2, 3, 32, 32)
    assert pixels.dtype == np.float32
    assert pixels.min() >= -1.0
    assert pixels.max() <= 1.0
    assert pixels[1].max() == -1.0  # black is -1


class FakeSession:
    def __init__(self) -> None:
        self.feeds: list[dict[str, FloatArray]] = []

    def run(self, output_names: list[str], input_feed: dict[str, FloatArray]) -> Sequence[object]:
        assert output_names == ["pooler_output"]
        self.feeds.append(input_feed)
        batch = input_feed["pixel_values"].shape[0]
        return [np.ones((batch, 768), dtype=np.float64)]


def test_siglip_onnx_with_a_fake_session() -> None:
    session = FakeSession()
    model = SiglipOnnx(session)
    assert model.model_id == (
        "Xenova/siglip-base-patch16-224/onnx/vision_model_quantized.onnx"
        "@4649052661e53c7000355844105f8a1792088239"
    )
    out = model.embed([packshot(1), packshot(2)])
    assert out.shape == (2, 768)
    assert out.dtype == np.float32
    assert session.feeds[0]["pixel_values"].shape == (2, 3, 224, 224)
    assert SIGLIP_BASE.url.startswith(
        "https://huggingface.co/Xenova/siglip-base-patch16-224/resolve/4649052"
    )


def test_model_file_downloads_once_and_checks_sha(tmp_path: Path) -> None:
    body = b"onnx bytes"
    model = OnnxModel("r/m", "rev", "onnx/m.onnx", hashlib.sha256(body).hexdigest(), 8, "out")
    downloads: list[str] = []

    def download(url: str, dest: Path) -> None:
        downloads.append(url)
        dest.write_bytes(body)

    path = model_file(model, tmp_path, download)
    assert path.read_bytes() == body
    assert model_file(model, tmp_path, download) == path
    assert downloads == ["https://huggingface.co/r/m/resolve/rev/onnx/m.onnx"]
    wrong = OnnxModel("r/m", "rev", "onnx/m.onnx", "0" * 64, 8, "out")
    with pytest.raises(ValueError, match="is not the pinned"):
        model_file(wrong, tmp_path, download)
    assert not (tmp_path / ("0" * 16) / "m.onnx").exists()  # a bad file is removed
