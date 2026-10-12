"""Plan an Ulta crawl that fetches only product pages absent from the served frontend.

The served dataset is the authority for "already available".  Sitemap absence is never removal
evidence: URLs present in the frontend but absent from this sitemap observation are reported as
``frontend_not_in_sitemap`` and left untouched.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pi_dataset import DatasetV3, load_any

SOURCE = "ulta_ae"
MISSING_URLS = "urls_missing_en.txt"
FRONTEND_NOT_IN_SITEMAP = "frontend_urls_not_in_sitemap.txt"
PLAN = "missing_plan.json"
_GZIP_MAGIC = b"\x1f\x8b"
_PRODUCT_PATH = re.compile(r"^/(en|ar)/([A-Za-z0-9][A-Za-z0-9._~-]*)$")


class MissingPlanError(ValueError):
    """The inputs cannot prove a safe, stable missing-only crawl plan."""


@dataclass(frozen=True, slots=True)
class FrontendInventory:
    """Ulta product-page inventory from one strictly validated served dataset."""

    urls: frozenset[str]
    dataset_file_sha256: str
    dataset_content_sha256: str
    product_count: int
    offer_count: int


@dataclass(frozen=True, slots=True)
class MissingPlan:
    """A deterministic difference between one sitemap observation and one served dataset."""

    inventory: FrontendInventory
    sitemap_urls: tuple[str, ...]
    missing_urls: tuple[str, ...]
    frontend_not_in_sitemap: tuple[str, ...]

    def manifest(self) -> dict[str, Any]:
        """The stable audit record written beside the URL lists."""
        return {
            "schema": "pi.ulta-missing-plan/v1",
            "source": SOURCE,
            "servedDataset": {
                "fileSha256": self.inventory.dataset_file_sha256,
                "contentSha256": self.inventory.dataset_content_sha256,
            },
            "counts": {
                "frontendProducts": self.inventory.product_count,
                "frontendOffers": self.inventory.offer_count,
                "frontendUrls": len(self.inventory.urls),
                "sitemapUrls": len(self.sitemap_urls),
                "missingUrls": len(self.missing_urls),
                "frontendNotInSitemap": len(self.frontend_not_in_sitemap),
            },
            "hashes": {
                "sitemapUrlsSha256": _lines_sha256(self.sitemap_urls),
                "missingUrlsSha256": _lines_sha256(self.missing_urls),
                "frontendNotInSitemapSha256": _lines_sha256(self.frontend_not_in_sitemap),
            },
            "semantics": {
                "missingUrls": (
                    "present in this robots-approved sitemap observation and absent from the "
                    "served frontend dataset"
                ),
                "frontendNotInSitemap": "not_observed only; never removal or out_of_stock evidence",
            },
        }


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _lines(urls: Sequence[str]) -> bytes:
    return "".join(f"{url}\n" for url in urls).encode()


def _lines_sha256(urls: Sequence[str]) -> str:
    return _sha256(_lines(urls))


def _canonical_product_url(value: str, *, allow_legacy: bool) -> str:
    """Return one exact EN page key, rejecting URL forms that can alias another resource."""
    raw = value
    if raw != raw.strip() or any(
        character.isspace() or ord(character) == 0x7F for character in raw
    ):
        raise MissingPlanError(f"not an Ulta UAE product URL: {value!r}")
    try:
        parts = urlsplit(raw)
    except ValueError as exc:
        raise MissingPlanError(f"not an Ulta UAE product URL: {value!r}") from exc
    match = _PRODUCT_PATH.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.lower() not in {"ulta.ae", "www.ulta.ae"}
        or "?" in raw
        or "#" in raw
        or match is None
    ):
        raise MissingPlanError(f"not an Ulta UAE product URL: {value!r}")
    slug = match.group(2)
    if slug == "buy-" or (not allow_legacy and not slug.startswith("buy-")):
        raise MissingPlanError(f"not an Ulta UAE product URL: {value!r}")
    current_slug = slug if slug.startswith("buy-") else f"buy-{slug}"
    return f"https://www.ulta.ae/en/{current_slug}"


def _sitemap_product_url(value: str) -> str:
    return _canonical_product_url(value, allow_legacy=False)


def strict_sitemap_product_urls(values: Sequence[str]) -> tuple[str, ...]:
    """Validate every product-sitemap entry and return its canonical English pages."""
    english: set[str] = set()
    for value in values:
        canonical = _sitemap_product_url(value)
        match = _PRODUCT_PATH.fullmatch(urlsplit(value).path)
        if match is not None and match.group(1) == "en":
            english.add(canonical)
    if not english:
        raise MissingPlanError("sitemap observation has no Ulta UAE English product URLs")
    return tuple(sorted(english))


def _frontend_product_url(value: str) -> str:
    """Canonical EN URL for current ``/buy-`` and retained legacy ``/<slug>`` PDPs."""
    return _canonical_product_url(value, allow_legacy=True)


def _dataset_body(file_body: bytes) -> bytes:
    if not file_body.startswith(_GZIP_MAGIC):
        return file_body
    try:
        # Python 3.12 gzip.decompress supports complete, multi-member gzip input:
        # https://docs.python.org/3.12/library/gzip.html#gzip.decompress
        return gzip.decompress(file_body)
    except (EOFError, OSError) as exc:
        raise MissingPlanError(f"served dataset is not valid gzip: {exc}") from exc


def load_frontend_inventory(
    path: Path, *, source: str = SOURCE, allow_test: bool = False
) -> FrontendInventory:
    """Strictly load ``path`` and extract every product URL served for ``source``.

    A null or non-Ulta URL refuses the plan: without a stable page key the runner cannot prove it
    is scraping only products absent from the frontend.
    """
    try:
        file_body = path.read_bytes()
    except OSError as exc:
        raise MissingPlanError(f"cannot read served dataset {path}: {exc}") from exc
    body = _dataset_body(file_body)
    try:
        dataset = load_any(body, allow_test=allow_test)
    except ValueError as exc:
        raise MissingPlanError(f"served dataset is invalid: {exc}") from exc

    retailer_ids = {retailer.id for retailer in dataset.meta.retailers}
    if source not in retailer_ids:
        raise MissingPlanError(f"served dataset has no retailer {source!r}")
    contexts = (
        {context.id for context in dataset.meta.contexts if context.retailer == source}
        if isinstance(dataset, DatasetV3)
        else {source}
    )
    urls: set[str] = set()
    bad: list[str] = []
    product_count = 0
    offer_count = 0
    for product in dataset.products:
        own = [(key, offer) for key, offer in product.offers.items() if key in contexts]
        if own:
            product_count += 1
        for key, offer in own:
            offer_count += 1
            if offer.url is None:
                bad.append(f"{product.id}.{key}: URL is null")
                continue
            try:
                urls.add(_frontend_product_url(str(offer.url)))
            except MissingPlanError as exc:
                bad.append(f"{product.id}.{key}: {exc}")
    if bad:
        shown = "; ".join(bad[:10])
        more = "" if len(bad) <= 10 else f"; and {len(bad) - 10} more"
        raise MissingPlanError(f"served frontend has unkeyable {source} offers: {shown}{more}")
    if not urls or not offer_count:
        raise MissingPlanError(f"served dataset has no usable {source} product URLs")
    return FrontendInventory(
        urls=frozenset(urls),
        dataset_file_sha256=_sha256(file_body),
        dataset_content_sha256=_sha256(body),
        product_count=product_count,
        offer_count=offer_count,
    )


def build_missing_plan(sitemap_urls: Sequence[str], inventory: FrontendInventory) -> MissingPlan:
    """Return the URLs newly seen in the sitemap, never interpreting absence as removal."""
    normalized = strict_sitemap_product_urls(sitemap_urls)
    observed = frozenset(normalized)
    return MissingPlan(
        inventory=inventory,
        sitemap_urls=normalized,
        missing_urls=tuple(sorted(observed - inventory.urls)),
        frontend_not_in_sitemap=tuple(sorted(inventory.urls - observed)),
    )


def _require_same_if_exists(path: Path, body: bytes) -> None:
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise MissingPlanError(f"cannot read existing {path.name}: {exc}") from exc
        if existing != body:
            raise MissingPlanError(
                f"{path.name} already records a different plan; use a new OUT_DIR"
            )


def _create_once_or_same(path: Path, body: bytes) -> None:
    """Atomically create ``path`` without replacing a concurrently created plan file."""
    if path.exists():
        _require_same_if_exists(path, body)
        return
    descriptor, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # Linking a fully flushed same-directory temp file is atomic and fails if another
            # process committed the final name first; unlike replace(), it never overwrites.
            os.link(tmp, path)
        except FileExistsError:
            _require_same_if_exists(path, body)
    finally:
        tmp.unlink(missing_ok=True)


def write_missing_plan(out: Path, plan: MissingPlan) -> None:
    """Create the three plan files, or prove an existing plan is byte-identical."""
    out.mkdir(parents=True, exist_ok=True)
    manifest = (
        json.dumps(plan.manifest(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    bodies = (
        (out / MISSING_URLS, _lines(plan.missing_urls)),
        (out / FRONTEND_NOT_IN_SITEMAP, _lines(plan.frontend_not_in_sitemap)),
        # The manifest is the commit marker and is therefore created last.
        (out / PLAN, manifest),
    )
    # Refuse every mismatch before filling any absent file. This prevents a partial directory
    # from becoming a mixture of two plans; rerunning the same plan safely completes it.
    for path, body in bodies:
        _require_same_if_exists(path, body)
    for path, body in bodies:
        _create_once_or_same(path, body)


def main(argv: Sequence[str] | None = None) -> int:
    """Offline planner CLI; the integrated runner uses the same functions."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("served_dataset", type=Path)
    parser.add_argument("sitemap_urls", type=Path)
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args(argv)
    inventory = load_frontend_inventory(args.served_dataset)
    plan = build_missing_plan(args.sitemap_urls.read_text().splitlines(), inventory)
    write_missing_plan(args.out_dir, plan)
    print(json.dumps(plan.manifest(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
