"""Identity/galleries preserve missing variants and reject unsafe or duplicate source records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from api_fixture import bearer, make_client, served_dataset, write
from pi_api.catalogue import CatalogueSource, LoadedCatalogue, detail, summary
from pi_api.config import Settings
from pi_api.source import LocalStore
from pi_dataset.catalogue import CatalogueDataset

CATALOGUE = "catalogues/ae/beauty/shop_a.json"
STAMP = "2026-10-01T01:00:00Z"


def document() -> dict[str, Any]:
    image = {
        "assetId": "image1",
        "url": "https://media.example/a.jpg",
        "sourceUrl": "https://media.example/original.jpg",
        "sha256": "a" * 64,
        "width": 300,
        "height": 400,
        "bytes": 1234,
        "contentType": "image/jpeg",
    }
    parent = {
        "sku": "parent",
        "name": "Lipstick",
        "productType": "configurable",
        "isVariant": False,
        "sourceIds": {"catalogueId": "opaque-id", "stockId": 123},
        "children": [{"sku": "child", "selections": ["colour"]}, {"sku": "missing"}],
        "groupingMasterSku": "parent",
        "excludedParentSummary": True,
        "capturedAt": STAMP,
        "optionValues": {"colour": "Red"},
        "imageIds": ["image1"],
    }
    child = {
        **parent,
        "sku": "child",
        "isVariant": True,
        "productType": "simple",
        "parents": [{"sku": "parent", "selections": ["colour"]}],
        "children": [],
        "excludedParentSummary": False,
        "imageIds": ["image1", "image2"],
    }
    return {
        "retailer": "shop_a",
        "market": "AE",
        "scope": "fixture",
        "generatedAt": STAMP,
        "importedAt": STAMP,
        "sourceSha256": "b" * 64,
        "records": {"parent": parent, "child": child},
        "assets": {"image1": image, "image2": {**image, "assetId": "image2"}},
    }


def test_full_gallery_dedupes_bytes_without_deleting_skus_and_keeps_missing_links() -> None:
    loaded = LoadedCatalogue(CatalogueDataset.model_validate(document()), "gen1")
    result = detail(loaded, "child", {"shop_a": frozenset({"media.example"})})
    assert len(result.images) == 1
    assert result.duplicate_images_removed == 1
    assert result.parents[0].source_ids is not None
    assert result.parents[0].selection_labels == ("Red",)
    missing = detail(loaded, "parent", {}).children[1]
    assert missing.sku == "missing"
    assert not missing.resolved
    assert missing.source_ids is None
    stats = summary(loaded)
    assert (stats.sku_records, stats.image_assets, stats.unique_image_contents) == (2, 2, 1)
    assert stats.unresolved_skus == 1
    assert stats.excluded_parent_summaries == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://media.example.evil/a",
        "http://media.example/a",
        "https://user@media.example/a",
        "https://media.example:99/a",
        "https://media.example\\@evil/a",
        "javascript:alert(1)",
    ],
)
def test_gallery_urls_use_exact_retailer_image_hosts(url: str) -> None:
    doc = document()
    doc["assets"]["image1"].update(url=url, sourceUrl=url)
    result = detail(
        LoadedCatalogue(CatalogueDataset.model_validate(doc), "1"),
        "child",
        {
            "shop_a": frozenset({"media.example"}),
        },
    )
    assert result.images[0].url is None
    assert result.images[0].source_url is None


@pytest.mark.parametrize(
    "issue", ["duplicate_link", "duplicate_image", "missing_asset", "one_way", "timestamp"]
)
def test_invalid_catalogues_fail_before_loading(issue: str) -> None:
    doc = document()
    if issue == "duplicate_link":
        doc["records"]["parent"]["children"].append({"sku": "child"})
    elif issue == "duplicate_image":
        doc["records"]["child"]["imageIds"].append("image1")
    elif issue == "missing_asset":
        del doc["assets"]["image1"]
    elif issue == "one_way":
        doc["records"]["child"]["parents"] = []
    else:
        doc["records"]["child"]["capturedAt"] = "2027-01-01T00:00:00Z"
    with pytest.raises(ValidationError):
        CatalogueDataset.model_validate(doc)


def test_catalogue_api_auth_scope_404_and_last_good_refresh(tmp_path: Path) -> None:
    write(tmp_path, served_dataset())
    path = tmp_path / CATALOGUE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document()))
    source = CatalogueSource(LocalStore(tmp_path), [CATALOGUE], clock=lambda: 0)
    source.load_all()
    # Pin the test clock after the explicit load so requests do not start a worker.
    source.checked = 0
    client, _ = make_client(
        tmp_path, catalogues=source, image_hosts={"shop_a": frozenset({"media.example"})}
    )
    base = "/api/v1/catalogues/shop_a"
    assert client.get(base).status_code == 401
    assert client.get(base, headers=bearer(role=None)).status_code == 403
    response = client.get(base + "/skus/child", headers=bearer())
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["record"]["sourceIds"]["stockId"] == 123
    assert len(data["images"]) == 1
    assert data["parents"][0]["resolved"]
    assert response.headers["cache-control"] == "private, no-store"
    assert client.get(base, headers=bearer()).json()["data"]["skuRecords"] == 2
    assert client.get(base + "/skus/missing", headers=bearer()).status_code == 404
    assert client.get(base + "?scope=elsewhere", headers=bearer()).status_code == 404
    assert client.get("/api/v1/catalogues/shop_b", headers=bearer()).status_code == 404
    assert client.get("/api/v1/catalogues/unknown", headers=bearer()).status_code == 404
    path.write_text('{"invalid":true}')
    source.load_all()
    assert client.get(base + "/skus/child", headers=bearer()).json()["data"] == data
    empty = CatalogueSource(LocalStore(tmp_path), [CATALOGUE], clock=lambda: 0)
    empty.checked = 0
    empty.load_all()
    broken, _ = make_client(tmp_path, catalogues=empty)
    assert broken.get(base, headers=bearer()).status_code == 503
    legacy, _ = make_client(tmp_path)
    assert legacy.get(base, headers=bearer()).status_code == 404


def test_optional_catalogue_paths_are_validated() -> None:
    env = {"PI_API_FIREBASE_PROJECT": "test", "PI_API_LOCAL_DIR": ".", "PI_API_DATASETS": "a.json"}
    assert Settings.from_env(env).catalogues == ()
    assert Settings.from_env({**env, "PI_API_CATALOGUES": CATALOGUE}).catalogues == (CATALOGUE,)
    with pytest.raises(ValueError, match=r"plain \.json"):
        Settings.from_env({**env, "PI_API_CATALOGUES": "../secrets.json"})


def test_the_published_catalogue_schema_matches_the_model() -> None:
    path = Path(__file__).parents[3] / "docs" / "contracts" / "pi-catalogue-v1.schema.json"
    assert json.loads(path.read_text()) == CatalogueDataset.model_json_schema(by_alias=True)
