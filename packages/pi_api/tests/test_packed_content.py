"""Offer content packed in memory (``pi_api.content``, tm8 01a11763-dc85): every endpoint answers
byte for byte as with the content resident, product detail reads it back, a refresh swaps it, and
a packed content without its body fails loudly instead of reading "not published"."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import HttpUrl

from api_fixture import DATASET_PATH, bearer, make_client, write
from pi_api.catalog import family_index
from pi_api.content import PackedContent, PackedContentError, packed, unpacked
from pi_dataset import ContentField, DatasetV3, OfferContent
from test_export import PAIR
from test_product_content import HOSTS, full_doc, offer

API = "/api/v1"
ADMIN = {"role": "admin"}
#: Every route that reads offers, with content (detail) and without (cards, lists, exports).
PATHS: tuple[tuple[str, dict[str, str]], ...] = (
    ("products/p01", {}),
    ("products/p02", {}),
    ("admin/products/p01", ADMIN),
    ("products", {}),
    ("products?q=lipstick", {}),
    ("products?q=p01", {}),
    (f"compare?{PAIR}", {}),
    (f"insights?{PAIR}", {}),
    ("summary", {}),
    ("export/products", {}),
    ("export/products?format=jsonl", {}),
    (f"export/compare?{PAIR}", {}),
)
ASSIGNED = {"shop_a": DATASET_PATH, "shop_b": DATASET_PATH}


def answers(root: Path, *, pack: bool, assigned: dict[str, str] | None) -> list[tuple[int, bytes]]:
    paths = () if assigned else (DATASET_PATH,)
    client, _ = make_client(
        root, image_hosts=HOSTS, pack_content=pack, assigned=assigned, paths=paths
    )
    out = []
    for path, role in PATHS:
        response = client.get(f"{API}/{path}", headers=bearer(**role))
        out.append((response.status_code, response.content))
    return out


@pytest.mark.parametrize("assigned", [None, ASSIGNED], ids=["whole", "per-source"])
def test_every_endpoint_answers_byte_for_byte_as_with_content_resident(
    tmp_path: Path, assigned: dict[str, str] | None
) -> None:
    write(tmp_path, DatasetV3.model_validate(full_doc()))
    on = answers(tmp_path, pack=True, assigned=assigned)
    off = answers(tmp_path, pack=False, assigned=assigned)
    assert [status for status, _ in on] == [200] * len(PATHS), on
    for (path, _), a, b in zip(PATHS, on, off, strict=True):
        assert a == b, path
    detail = on[0][1].decode()
    assert "A matte lipstick." in detail  # the fixture's content really is served
    assert "Ruby" in detail


def test_the_served_offers_hold_only_captured_and_family(tmp_path: Path) -> None:
    write(tmp_path, DatasetV3.model_validate(full_doc()))
    _, source = make_client(tmp_path, image_hosts=HOSTS)
    (served,) = source.datasets()
    content = next(p for p in served.dataset.products if p.id == "p01").offers["shop_a"].content
    assert isinstance(content, PackedContent)
    assert (content.description, content.ingredients, content.images, content.variants) == (
        None,
        None,
        (),
        (),
    )
    assert content.family == "fam-1"
    assert ContentField.DESCRIPTION in content.captured
    full = unpacked(content)
    assert full is not None
    assert full.description == "A matte lipstick."


def test_the_family_index_is_the_same_packed(tmp_path: Path) -> None:
    dataset = DatasetV3.model_validate(full_doc())

    def keys(ds: DatasetV3) -> dict[tuple[str, str], tuple[str, ...]]:
        return {k: tuple(pid for pid, _ in v) for k, v in family_index(ds).items()}

    assert keys(packed(dataset)) == keys(dataset) != {}


def test_a_refresh_swaps_the_packed_content(tmp_path: Path) -> None:
    write(tmp_path, DatasetV3.model_validate(full_doc()))
    client, source = make_client(tmp_path, image_hosts=HOSTS)
    doc = full_doc()
    offer(doc, "p01", "shop_a")["content"]["description"] = "A satin lipstick."
    write(tmp_path, DatasetV3.model_validate(doc))
    target = tmp_path / DATASET_PATH
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    source.load_all()
    body: dict[str, Any] = client.get(f"{API}/products/p01", headers=bearer()).json()
    content = {o["context"]: o["content"] for o in body["data"]["offers"]}["shop_a"]
    assert content["description"]["text"] == "A satin lipstick."


def test_packed_content_without_its_body_fails_instead_of_reading_empty() -> None:
    content = PackedContent(captured=(ContentField.DESCRIPTION,))
    with pytest.raises(PackedContentError):
        content.unpacked()


def test_content_with_nothing_heavy_is_not_packed() -> None:
    dataset = DatasetV3.model_validate(full_doc())
    p02 = next(p for p in packed(dataset).products if p.id == "p02").offers["shop_a"].content
    assert p02 is not None
    assert not isinstance(p02, PackedContent)


text = st.one_of(st.none(), st.text(min_size=1, max_size=40).filter(lambda s: s.strip() != ""))


@given(description=text, ingredients=text, family=text)
def test_packing_reads_back_the_same_content(
    description: str | None, ingredients: str | None, family: str | None
) -> None:
    texts = ((ContentField.DESCRIPTION, description), (ContentField.INGREDIENTS, ingredients))
    captured = (*(f for f, value in texts if value is not None), ContentField.IMAGES)
    try:
        content = OfferContent(
            captured=captured,
            description=description,
            ingredients=ingredients,
            images=(HttpUrl("https://media.example/a.jpg"),),
            family=family,
        )
    except ValueError:  # a text the contract refuses (e.g. not normalised) is not packed
        return
    assert PackedContent.of(content).unpacked() == content
    assert unpacked(content) is content
