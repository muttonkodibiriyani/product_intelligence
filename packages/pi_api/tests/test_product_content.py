"""``Offer.content`` on the product detail (API 1.12.0): every field carries its state, a v3
snapshot written before the field existed serves ``not_captured``, and image URLs pass the
same per-retailer host allowlist as the card image."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from api_fixture import DATASET_PATH, Client, bearer, make_client, served_dataset, write
from pi_api.catalogue import CatalogueSource
from pi_api.source import LocalStore
from pi_dataset import DatasetV3
from pi_metrics import view
from test_catalogue import CATALOGUE
from test_catalogue import document as catalogue_document

API = "/api/v1"
HOSTS = {"shop_a": frozenset({"media.example"}), "shop_b": frozenset({"img.example"})}
GTIN = "4006381333931"
ALL = ["description", "ingredients", "images", "shade", "gtin"]
OLD_V3 = Path(__file__).parent / "fixtures" / "v3-main-66bc083.json"


def base() -> dict[str, Any]:
    doc: dict[str, Any] = view.as_v3(served_dataset()).model_dump(mode="json", by_alias=True)
    return doc


def offer(doc: dict[str, Any], product_id: str, context: str) -> dict[str, Any]:
    found: dict[str, Any] = next(p for p in doc["products"] if p["id"] == product_id)["offers"][
        context
    ]
    return found


def full_doc() -> dict[str, Any]:
    doc = base()
    offer(doc, "p01", "shop_a")["content"] = {
        "captured": ALL,
        "description": "A matte lipstick.",
        "ingredients": "Ricinus communis seed oil",
        "images": [
            "https://media.example/p01-1.jpg",
            "https://evil.example/p01-2.jpg",
            "https://media.example/p01-3.jpg",
        ],
        "variants": [
            {"sku": "A1", "shade": "Ruby", "gtin": GTIN},
            {"sku": "A2", "shade": None, "gtin": None},
        ],
        "family": "fam-1",
    }
    offer(doc, "p02", "shop_a")["content"] = {"captured": [], "family": "fam-1"}
    offer(doc, "p01", "shop_b")["content"] = {"captured": ["description", "images"]}
    return doc


def client_for(tmp_path: Path, doc: dict[str, Any], **kwargs: Any) -> Client:
    write(tmp_path, DatasetV3.model_validate(doc))
    return make_client(tmp_path, image_hosts=HOSTS, **kwargs)[0]


def contents(client: Client, product_id: str = "p01") -> dict[str, Any]:
    response = client.get(f"{API}/products/{product_id}", headers=bearer())
    assert response.status_code == 200, response.text
    return {o["context"]: o["content"] for o in response.json()["data"]["offers"]}


def states(content: dict[str, Any]) -> dict[str, str]:
    return {k: v["state"] for k, v in content.items() if k != "sizes"}


def test_a_full_offer_serves_every_field_observed(tmp_path: Path) -> None:
    content = contents(client_for(tmp_path, full_doc()))["shop_a"]
    assert states(content) == dict.fromkeys(
        ("description", "ingredients", "images", "variants"), "observed"
    )
    assert content["description"]["text"] == "A matte lipstick."
    assert content["ingredients"]["text"] == "Ricinus communis seed oil"
    # The off-allowlist URL is dropped; the order of the rest is kept.
    assert content["images"] == {
        "state": "observed",
        "source": "page",
        "items": [
            {"url": "https://media.example/p01-1.jpg"},
            {"url": "https://media.example/p01-3.jpg"},
        ],
    }
    first, second = content["variants"]["items"]
    assert first == {
        "sku": "A1",
        "shade": {"state": "observed", "text": "Ruby"},
        "gtin": {"state": "observed", "barcode": GTIN},
    }
    # Captured for the source, absent on this listing: not_published, never an empty value.
    assert second["shade"] == {"state": "not_published", "text": None}
    assert second["gtin"] == {"state": "not_published", "barcode": None}


def test_sizes_list_other_products_of_the_same_family_in_the_context(tmp_path: Path) -> None:
    client = client_for(tmp_path, full_doc())
    sizes = contents(client)["shop_a"]["sizes"]
    assert [s["productId"] for s in sizes] == ["p02"]
    assert contents(client, "p02")["shop_a"]["sizes"][0]["productId"] == "p01"
    # shop_b has no family: no siblings, and p01 never lists itself.
    assert contents(client)["shop_b"]["sizes"] == []


def test_a_sparse_offer_tells_not_published_from_not_captured(tmp_path: Path) -> None:
    content = contents(client_for(tmp_path, full_doc()))["shop_b"]
    assert states(content) == {
        "description": "not_published",
        "images": "not_published",
        "ingredients": "not_captured",
        "variants": "not_published",
    }
    assert content["description"]["text"] is None
    assert content["images"] == {"state": "not_published", "source": None, "items": []}


def test_a_gallery_with_no_url_on_an_allowed_host_reads_not_captured(tmp_path: Path) -> None:
    doc = full_doc()
    offer(doc, "p01", "shop_b")["content"] = {
        "captured": ["images"],
        "images": ["https://evil.example/p01-1.jpg", "https://cdn.other.example/p01-2.jpg"],
    }
    content = contents(client_for(tmp_path, doc))["shop_b"]
    # The page had a gallery the API can't serve: not withheld by the retailer, so never
    # not_published.
    assert content["images"] == {"state": "not_captured", "source": None, "items": []}


def test_a_v3_snapshot_from_before_content_still_serves_not_captured(tmp_path: Path) -> None:
    """main's own v3 at 66bc083, unchanged: it validates, and every field is not_captured."""
    target = tmp_path / DATASET_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(OLD_V3.read_bytes())
    assert "content" not in OLD_V3.read_text()
    client = make_client(tmp_path, image_hosts=HOSTS)[0]
    for content in contents(client).values():
        assert set(states(content).values()) == {"not_captured"}
        assert content["sizes"] == []
        assert content["images"]["source"] is None


def test_the_catalogue_gallery_fills_in_when_the_page_has_none(tmp_path: Path) -> None:
    doc = full_doc()
    shop_a = offer(doc, "p01", "shop_a")
    shop_a["sku"] = "child"
    shop_a["content"]["images"] = []
    write(tmp_path, DatasetV3.model_validate(doc))
    catalogue = catalogue_document()
    catalogue["scope"] = doc["meta"]["scope"]
    path = tmp_path / CATALOGUE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalogue))
    source = CatalogueSource(LocalStore(tmp_path), [CATALOGUE], clock=lambda: 0)
    source.load_all()
    source.checked = 0
    client = make_client(tmp_path, image_hosts=HOSTS, catalogues=source)[0]
    images = contents(client)["shop_a"]["images"]
    assert images == {
        "state": "observed",
        "source": "catalogue",
        "items": [{"url": "https://media.example/a.jpg"}],
    }
    # Without the sku in the catalogue, the page's state stands.
    shop_a["sku"] = "unknown"
    write(tmp_path, DatasetV3.model_validate(doc))
    client = make_client(tmp_path, image_hosts=HOSTS, catalogues=source)[0]
    assert contents(client)["shop_a"]["images"]["state"] == "not_published"
