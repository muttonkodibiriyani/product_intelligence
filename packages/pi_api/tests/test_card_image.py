"""``ProductCard.image`` (API 1.3.0): one thumbnail, served only from a retailer's image hosts.

The URL is hotlinked by the dashboard, so it must be https on a host listed for a retailer that
shows the product (``PI_API_IMAGE_HOSTS``); anything else is null, never a guess.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest

from api_fixture import Client, bearer, make_client, write
from pi_dataset import DatasetV3
from v3_fixture import doc, offer

API = "/api/v1"
A_IMG, B_IMG = "img.shop-a.example", "img.shop-b.example"
HOSTS = {"shop_a": frozenset({A_IMG}), "shop_b": frozenset({B_IMG})}
PRODUCT = f"https://{A_IMG}/p01.jpg"
OFFER_B = f"https://{B_IMG}/p01-b.jpg"


def image_doc(product: str | None = PRODUCT, offer_b: str | None = OFFER_B) -> dict[str, Any]:
    d = doc()
    d["meta"]["test"] = False
    next(p for p in d["products"] if p["id"] == "p01")["image"] = product
    offer(d, "p01", "shop_b")["image"] = offer_b
    return d


def client_for(tmp_path: Path, d: dict[str, Any], hosts: Any = HOSTS) -> Client:
    write(tmp_path, DatasetV3.model_validate(d))
    return make_client(tmp_path, image_hosts=hosts)[0]


def card(client: Client) -> Any:
    response = client.get(f"{API}/products?limit=100", headers=bearer())
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["data"]["items"] if item["id"] == "p01")


def test_the_product_image_on_a_showing_retailers_host_is_served(tmp_path: Path) -> None:
    client = client_for(tmp_path, image_doc())
    assert card(client)["image"] == PRODUCT
    detail = client.get(f"{API}/products/p01", headers=bearer()).json()["data"]
    assert detail["card"]["image"] == PRODUCT
    rows = client.get(f"{API}/export/products?format=csv", headers=bearer()).text.splitlines()[1:]
    table = list(csv.DictReader(rows))
    assert next(r for r in table if r["id"] == "p01")["image"] == PRODUCT


def test_an_offer_image_is_the_fallback(tmp_path: Path) -> None:
    elsewhere = image_doc(product="https://cdn.elsewhere.example/p01.jpg")
    assert card(client_for(tmp_path, elsewhere))["image"] == OFFER_B


@pytest.mark.parametrize(
    "url",
    [
        f"http://{A_IMG}/p01.jpg",  # not https
        f"https://user@{A_IMG}/p01.jpg",
        f"https://{A_IMG}:8443/p01.jpg",
        f"https://{A_IMG}.evil.example/p01.jpg",
    ],
)
def test_anything_off_the_image_hosts_is_null(tmp_path: Path, url: str) -> None:
    assert card(client_for(tmp_path, image_doc(product=url, offer_b=None)))["image"] is None


def test_no_image_hosts_means_no_images(tmp_path: Path) -> None:
    assert card(client_for(tmp_path, image_doc(), hosts=None))["image"] is None


def test_an_early_offer_neither_shows_nor_vouches_for_an_image(tmp_path: Path) -> None:
    d = image_doc(product=f"https://{B_IMG}/p01.jpg")  # only shop_b's host
    offer(d, "p01", "shop_b")["early"] = True
    assert card(client_for(tmp_path, d))["image"] is None
