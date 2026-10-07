"""Image embeddings (SigLIP on CPU through ONNX Runtime) with an on-disk cache.

``Embedder`` is the seam: tests use a deterministic fake, offline runs use ``SiglipOnnx``. The
model file is downloaded once from Hugging Face at a pinned revision and checked against its
SHA-256 before it is loaded; nothing billable is involved.
"""

import hashlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from pi_image.fetch import url_key

FloatArray = NDArray[np.float32]


class Embedder(Protocol):
    """Maps packshots to vectors; ``model_id`` names the model and revision exactly."""

    @property
    def model_id(self) -> str:
        """Stable id; part of the cache key, so a model change never reuses old vectors."""
        ...

    def embed(self, images: Sequence[Image.Image]) -> FloatArray:
        """One row per image, any scale (callers L2-normalise)."""
        ...


def l2_normalise(vectors: FloatArray) -> FloatArray:
    """Rows scaled to unit length; an all-zero row stays zero.

    The norm is taken in float64: in float32 the squares of a tiny row underflow (and of a huge
    row overflow), so a row like ``[7.27e-23]`` came out with length 0.971, not 1.
    """
    wide = vectors.astype(np.float64)
    norms = np.linalg.norm(wide, axis=1, keepdims=True)
    return (wide / np.where(norms == 0, 1, norms)).astype(np.float32)


class EmbeddingCache:
    """One ``.npy`` per (model, image URL) under ``<root>/<model slug>/``."""

    def __init__(self, root: Path, model_id: str) -> None:
        slug = hashlib.sha256(model_id.encode("utf-8")).hexdigest()[:16]
        self.folder = root / slug

    def _path(self, url: str) -> Path:
        key = url_key(url)
        return self.folder / key[:2] / f"{key}.npy"

    def get(self, url: str) -> FloatArray | None:
        """The cached unit vector, or None."""
        path = self._path(url)
        if not path.is_file():
            return None
        loaded: FloatArray = np.load(path, allow_pickle=False)
        return loaded

    def put(self, url: str, vector: FloatArray) -> None:
        """Store a unit vector atomically."""
        path = self._path(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp.npy")
        np.save(tmp, vector.astype(np.float32), allow_pickle=False)
        tmp.replace(path)


def embed_all(
    items: Iterable[tuple[str, Callable[[], Image.Image]]],
    embedder: Embedder,
    cache: EmbeddingCache,
    batch: int = 16,
) -> dict[str, FloatArray]:
    """Unit vectors by image URL: cached ones are read, the rest loaded and embedded in batches.

    Images are loaded lazily, one batch at a time, so a full catalogue never sits in memory.
    """
    out: dict[str, FloatArray] = {}
    pending: list[tuple[str, Callable[[], Image.Image]]] = []
    queued: set[str] = set()

    def flush() -> None:
        if not pending:
            return
        vectors = l2_normalise(embedder.embed([load() for _, load in pending]))
        for (url, _), vector in zip(pending, vectors, strict=True):
            cache.put(url, vector)
            out[url] = vector
        pending.clear()

    for url, load in items:
        if url in out or url in queued:
            continue
        hit = cache.get(url)
        if hit is not None:
            out[url] = hit
            continue
        queued.add(url)
        pending.append((url, load))
        if len(pending) >= batch:
            flush()
    flush()
    return out


# ---------------------------------------------------------------- SigLIP via ONNX Runtime


@dataclass(frozen=True, slots=True)
class OnnxModel:
    """A pinned ONNX vision encoder on Hugging Face."""

    repo: str
    revision: str
    path: str
    sha256: str
    size: int  # input side in pixels
    output: str  # the pooled image embedding

    @property
    def model_id(self) -> str:
        """Repo, file and revision."""
        return f"{self.repo}/{self.path}@{self.revision}"

    @property
    def url(self) -> str:
        """The pinned download URL."""
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{self.path}"


#: SigLIP base, patch 16, 224 px; int8-quantised vision tower (~100 MB), CPU friendly.
SIGLIP_BASE = OnnxModel(
    repo="Xenova/siglip-base-patch16-224",
    revision="4649052661e53c7000355844105f8a1792088239",
    path="onnx/vision_model_quantized.onnx",
    sha256="ef14a954f3d57e1806666432bd9785004c1dc27100aa260eee0cb0f10a5de058",
    size=224,
    output="pooler_output",
)


def siglip_pixels(images: Sequence[Image.Image], size: int) -> FloatArray:
    """SigLIP preprocessing: RGB, bicubic resize to ``size`` square, scale to [-1, 1], NCHW."""
    arrays = [
        np.asarray(i.convert("RGB").resize((size, size), Image.Resampling.BICUBIC), np.float32)
        for i in images
    ]
    stacked = np.stack(arrays) / 255.0
    return ((stacked - 0.5) / 0.5).transpose(0, 3, 1, 2).astype(np.float32)


def model_file(model: OnnxModel, root: Path, download: Callable[[str, Path], None]) -> Path:
    """The model file under ``root``, downloaded if absent; raises if its SHA-256 differs."""
    path = root / model.sha256[:16] / Path(model.path).name
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        download(model.url, tmp)
        tmp.replace(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != model.sha256:
        path.unlink()
        msg = f"{model.model_id}: SHA-256 {digest} is not the pinned {model.sha256}"
        raise ValueError(msg)
    return path


class Session(Protocol):
    """The slice of ``onnxruntime.InferenceSession`` used here."""

    def run(
        self, output_names: list[str], input_feed: dict[str, FloatArray]
    ) -> Sequence[object]: ...


class SiglipOnnx:
    """SigLIP image embeddings from an ONNX Runtime session (``pi-image[embed]``)."""

    def __init__(self, session: Session, model: OnnxModel = SIGLIP_BASE) -> None:
        self._session = session
        self._model = model

    @property
    def model_id(self) -> str:
        """The pinned model id."""
        return self._model.model_id

    def embed(self, images: Sequence[Image.Image]) -> FloatArray:
        """Pooled embeddings, one row per image."""
        pixels = siglip_pixels(images, self._model.size)
        (pooled,) = self._session.run([self._model.output], {"pixel_values": pixels})
        return np.asarray(pooled, dtype=np.float32)


def open_session(path: Path, threads: int = 4) -> Session:  # pragma: no cover - needs ORT
    """An ONNX Runtime CPU session (import is lazy: the ``embed`` extra is optional)."""
    import onnxruntime as ort  # type: ignore[import-not-found,import-untyped,unused-ignore]  # noqa: PLC0415

    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    session: Session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
    return session
