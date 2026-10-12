"""Missing-only crawl planning is deterministic, strict and never removal evidence."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest
from ulta_snapshot.missing import (
    FRONTEND_NOT_IN_SITEMAP,
    MISSING_URLS,
    PLAN,
    FrontendInventory,
    MissingPlanError,
    build_missing_plan,
    load_frontend_inventory,
    write_missing_plan,
)

from pi_dataset import dump_dataset
from pi_dataset.examples import ae_pilot

BASE = "https://www.ulta.ae/en/buy-"


def _inventory(*urls: str) -> FrontendInventory:
    return FrontendInventory(
        urls=frozenset(urls),
        dataset_file_sha256="f" * 64,
        dataset_content_sha256="c" * 64,
        product_count=len(urls),
        offer_count=len(urls),
    )


def test_plan_fetches_only_new_urls_and_never_calls_sitemap_absence_removal() -> None:
    kept = f"{BASE}kept"
    missing = f"{BASE}new"
    not_seen = f"{BASE}not-seen-this-time"
    plan = build_missing_plan([missing, kept, missing], _inventory(kept, not_seen))

    assert plan.missing_urls == (missing,)
    assert plan.frontend_not_in_sitemap == (not_seen,)
    manifest = plan.manifest()
    assert manifest["counts"] == {
        "frontendProducts": 2,
        "frontendOffers": 2,
        "frontendUrls": 2,
        "sitemapUrls": 2,
        "missingUrls": 1,
        "frontendNotInSitemap": 1,
    }
    assert "never removal or out_of_stock" in manifest["semantics"]["frontendNotInSitemap"]


def test_plan_files_are_create_once_or_byte_identical(tmp_path: Path) -> None:
    first = build_missing_plan([f"{BASE}new"], _inventory(f"{BASE}old"))
    write_missing_plan(tmp_path, first)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    write_missing_plan(tmp_path, first)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
    assert (tmp_path / MISSING_URLS).read_text().splitlines() == [f"{BASE}new"]
    assert (tmp_path / FRONTEND_NOT_IN_SITEMAP).read_text().splitlines() == [f"{BASE}old"]
    assert json.loads((tmp_path / PLAN).read_text())["schema"] == "pi.ulta-missing-plan/v1"

    changed = build_missing_plan([f"{BASE}other"], _inventory(f"{BASE}old"))
    with pytest.raises(MissingPlanError, match="different plan"):
        write_missing_plan(tmp_path, changed)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_partial_plan_is_never_filled_from_different_inputs(tmp_path: Path) -> None:
    first = build_missing_plan([f"{BASE}first"], _inventory(f"{BASE}old"))
    write_missing_plan(tmp_path, first)
    (tmp_path / PLAN).unlink()  # simulate interruption before the manifest commit marker
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    changed = build_missing_plan([f"{BASE}changed"], _inventory(f"{BASE}old"))
    with pytest.raises(MissingPlanError, match="different plan"):
        write_missing_plan(tmp_path, changed)

    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
    assert not (tmp_path / PLAN).exists()


@pytest.mark.parametrize("compressed", [False, True])
def test_served_dataset_is_strictly_loaded_from_plain_or_gzip(
    tmp_path: Path, compressed: bool
) -> None:
    dataset = ae_pilot()
    source = dataset.meta.retailers[0].id
    doc = json.loads(dump_dataset(dataset))
    expected: set[str] = set()
    for index, product in enumerate(doc["products"]):
        url = f"{BASE}product-{index}"
        product["offers"][source]["url"] = url
        expected.add(url)
    body = json.dumps(doc, separators=(",", ":")).encode()
    path = tmp_path / ("served.json.gz" if compressed else "served.json")
    path.write_bytes(gzip.compress(body, mtime=0) if compressed else body)

    inventory = load_frontend_inventory(path, source=source, allow_test=True)

    assert inventory.urls == expected
    assert inventory.product_count == len(doc["products"])
    assert inventory.offer_count == len(doc["products"])
    assert len(inventory.dataset_file_sha256) == 64
    assert len(inventory.dataset_content_sha256) == 64


def test_invalid_or_missing_frontend_url_refuses_missing_only_claim(tmp_path: Path) -> None:
    dataset = ae_pilot()
    source = dataset.meta.retailers[0].id
    path = tmp_path / "served.json"
    path.write_bytes(dump_dataset(dataset))  # example URLs are not ulta.ae

    with pytest.raises(MissingPlanError, match="unkeyable"):
        load_frontend_inventory(path, source=source, allow_test=True)


def test_retained_legacy_product_urls_match_the_current_buy_form(tmp_path: Path) -> None:
    dataset = ae_pilot()
    source = dataset.meta.retailers[0].id
    doc = json.loads(dump_dataset(dataset))
    for index, product in enumerate(doc["products"]):
        locale = "ar" if index % 2 else "en"
        product["offers"][source]["url"] = f"https://www.ulta.ae/{locale}/product-{index}"
    path = tmp_path / "served.json"
    path.write_text(json.dumps(doc))

    inventory = load_frontend_inventory(path, source=source, allow_test=True)

    assert inventory.urls == {
        f"https://www.ulta.ae/en/buy-product-{index}" for index in range(len(doc["products"]))
    }


def test_empty_sitemap_refuses_instead_of_reporting_zero() -> None:
    with pytest.raises(MissingPlanError, match="no Ulta UAE English product URLs"):
        build_missing_plan([], _inventory(f"{BASE}known"))


@pytest.mark.parametrize(
    "url",
    [
        "https://evil@www.ulta.ae/en/buy-product",
        "https://www.ulta.ae:444/en/buy-product",
        "https://www.ulta.ae/en//buy-product",
        "https://www.ulta.ae/en/buy-",
        "https://www.ulta.ae/en/buy-product?",
        "https://www.ulta.ae/en/buy-product#",
        "https://www.ulta.ae/en/product",
        "https://www.ulta.ae/en/buy-product%2Fother",
        "https://www.ulta.ae/en/buy-product/",
        "https://www.ulta.ae/en/buy-pro\tduct",
        "https://www.ulta.ae/en/buy-pro\nduct",
        "https://www.ulta.ae/en/buy-pro\rduct",
        " https://www.ulta.ae/en/buy-product",
        "",
    ],
)
def test_sitemap_url_aliases_and_non_current_forms_fail_closed(url: str) -> None:
    with pytest.raises(MissingPlanError):
        build_missing_plan([url], _inventory(f"{BASE}known"))


def test_one_blank_entry_refuses_the_entire_sitemap_observation() -> None:
    with pytest.raises(MissingPlanError, match="not an Ulta UAE product URL"):
        build_missing_plan([f"{BASE}valid", ""], _inventory(f"{BASE}known"))
