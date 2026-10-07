"""publish_dataset v3: Offer.content reaches the API; v1/v2 publishing is unchanged.

Synthetic files only (the ae-pilot example upgraded to v3 with content added); no network.
"""

import gzip
import json
import sys
import types
from pathlib import Path
from typing import Any

import publish_dataset
import pytest
from test_publish_source_guard import catalog, sephora_only

from api_fixture import bearer, make_client
from pi_dataset import dump_dataset, load_dataset
from pi_dataset.profiles import committed_profile
from pi_dataset.upgrade import upgrade

GTIN = "4006381333931"
#: The upgrade gives a sole context its retailer's id (a v3 rule); ``by_source`` maps any id.
CONTEXT = "sephora_me"


def v3_doc() -> dict[str, Any]:
    """sephora_only() as v3, its first offer carrying content."""
    profile = committed_profile("beauty", 1)
    assert profile is not None
    dataset = upgrade(load_dataset(sephora_only(), allow_test=True), profile)
    doc: dict[str, Any] = json.loads(dataset.model_dump_json(by_alias=True))
    first = doc["products"][0]["offers"][CONTEXT]
    first["content"] = {
        "captured": ["description", "images", "gtin"],
        "description": "A synthetic lipstick.",
        "images": ["https://media.example/p-1.jpg"],
        "variants": [{"sku": "S1", "shade": None, "gtin": GTIN}],
    }
    return doc


def raw_of(doc: dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False)


def packaged(doc: dict[str, Any]) -> tuple[bytes, list[str], dict[str, Any], str]:
    dataset, errors = publish_dataset.validate_v3(raw_of(doc), allow_test=True)
    assert errors == []
    return publish_dataset.package_v2(dataset)


# ------------------------------------------------------------------ validate and package
def test_a_v3_sephora_file_goes_to_the_same_prefix_and_meta_doc_as_v2() -> None:
    body, paths, summary, meta_doc = packaged(v3_doc())
    assert paths == [
        "datasets/ae/sephora_me/20260930T000000Z.json",
        "datasets/ae/sephora_me/latest.json",
    ]
    assert publish_dataset.outside_prefixes(paths) == []
    assert meta_doc == "v2_ae_sephora_me"
    assert summary["schema"] == "pi.dataset/v3"
    assert summary["source"] == "sephora_me"
    uploaded = json.loads(gzip.decompress(body))
    assert uploaded["schema"] == "pi.dataset/v3"
    content = uploaded["products"][0]["offers"][CONTEXT]["content"]
    assert content["variants"][0]["gtin"] == GTIN
    assert publish_dataset.offer_counts(publish_dataset.by_source(uploaded)) == {"sephora_me": 3}


def test_a_v2_file_still_packages_byte_identically() -> None:
    dataset, errors = publish_dataset.validate_v2(sephora_only(), allow_test=True)
    assert errors == []
    body, _, summary, _ = publish_dataset.package_v2(dataset)
    assert gzip.decompress(body) == dump_dataset(dataset)
    assert summary["schema"] == "pi.dataset/v2"
    assert publish_dataset.by_source(json.loads(gzip.decompress(body))) == json.loads(
        gzip.decompress(body)
    )


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda d: d["products"][0].update(name=1.5), "JSON float"),
        (lambda d: d["products"][0].update(note="x-algolia-api-key"), "credential-like"),
        (lambda d: d["meta"].update(test=True), None),
    ],
)
def test_a_v3_file_gets_the_contracts_strict_load(change: Any, expected: str | None) -> None:
    doc = v3_doc()
    change(doc)
    raw = raw_of(doc)
    if expected is None:  # meta.test needs --allow-test, as for v2
        _, errors = publish_dataset.validate_v3(raw, allow_test=False)
        assert any("meta.test" in e for e in errors)
        return
    _, errors = publish_dataset.validate_v3(raw, allow_test=True)
    assert any(expected in e for e in errors), errors


def test_validate_v3_refuses_a_v2_file() -> None:
    _, errors = publish_dataset.validate_v3(sephora_only(), allow_test=True)
    assert errors == ["schema must be 'pi.dataset/v3'"]


def test_content_that_breaks_the_v3_model_is_refused() -> None:
    doc = v3_doc()
    doc["products"][0]["offers"][CONTEXT]["content"]["variants"][0]["gtin"] = "4006381333932"
    _, errors = publish_dataset.validate_v3(raw_of(doc), allow_test=True)
    assert any("check digit" in e for e in errors), errors


# ------------------------------------------------------------------ one source per file
def with_context(doc: dict[str, Any], context: str, retailer: str) -> dict[str, Any]:
    """``doc`` with a second context at ``retailer`` offering its first product."""
    ctx = dict(doc["meta"]["contexts"][0]) | {"id": context, "retailer": retailer}
    doc["meta"]["contexts"].append(ctx)
    first = doc["products"][0]["offers"]
    first[context] = json.loads(json.dumps(first[CONTEXT])) | {"content": None}
    return doc


def test_two_sources_in_a_v3_file_are_refused_by_context_owner() -> None:
    doc = with_context(v3_doc(), "faces_online", "faces_ae")
    source, errors = publish_dataset.publishing_source(publish_dataset.by_source(doc))
    assert source is None
    assert errors == ["one source per file: offers come from ['faces_ae', 'sephora_me']"]


def test_two_contexts_of_one_source_are_one_source() -> None:
    doc = with_context(v3_doc(), "sephora_me_store", "sephora_me")
    grouped = publish_dataset.by_source(doc)
    assert publish_dataset.publishing_source(grouped) == ("sephora_me", [])
    # A product with two contexts of the source is one product of the source.
    assert publish_dataset.offer_counts(grouped) == {"sephora_me": 3}
    assert sorted(grouped["products"][0]["offers"]["sephora_me"]) == [
        "sephora_me",
        "sephora_me_store",
    ]


def test_a_ulta_v3_file_is_refused() -> None:
    doc = v3_doc()
    for c in doc["meta"]["contexts"]:
        c["retailer"] = "ulta_ae"
    source, errors = publish_dataset.publishing_source(publish_dataset.by_source(doc))
    assert source is None
    assert errors == [
        "ulta_ae is not a source PI publishes (sephora_me, faces_ae, ounass_ae, bloomingdales_ae)"
    ]


# ------------------------------------------------------------------ the live-source guard
def live_v2() -> dict[str, Any]:
    dataset, errors = publish_dataset.validate_v2(sephora_only(), allow_test=True)
    assert errors == []
    live: dict[str, Any] = json.loads(gzip.decompress(publish_dataset.package_v2(dataset)[0]))
    return live


def new_v3() -> dict[str, Any]:
    return publish_dataset.by_source(json.loads(gzip.decompress(packaged(v3_doc())[0])))


def test_a_v2_to_v3_switch_of_the_same_source_passes_the_guard() -> None:
    assert publish_dataset.guard(live_v2(), new_v3(), "sephora_me") == []


def test_a_v3_to_v3_republish_passes_and_a_loss_holds() -> None:
    live = json.loads(gzip.decompress(packaged(v3_doc())[0]))
    assert publish_dataset.guard(live, new_v3(), "sephora_me") == []
    smaller = new_v3()
    smaller["products"] = smaller["products"][:2]
    assert publish_dataset.guard(live, smaller, "sephora_me") == [
        "HOLD, sephora_me drops from 3 to 2 offers"
    ]


def test_another_sources_products_hold_across_a_schema_switch() -> None:
    """faces_ae data in the live v2 file: its v3 shape differs, so it is never PI's to change."""
    live = catalog(sephora_me=3, faces_ae=1)
    new = publish_dataset.by_source(with_context(v3_doc(), "faces_ae", "faces_ae"))
    assert publish_dataset.guard(live, new, "sephora_me") == [
        "HOLD, faces_ae is not sephora_me's to change: its products differ"
    ]


def test_a_live_v3_ulta_source_missing_from_the_new_file_holds_even_with_drop() -> None:
    live = with_context(v3_doc(), "ulta_ae", "ulta_ae")
    problems = publish_dataset.guard(live, new_v3(), "sephora_me", ("ulta_ae",))
    assert problems == ["HOLD, live source ulta_ae (1 offers) is missing"]


# ------------------------------------------------------------------ main() end to end
def run(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(sys, "argv", ["publish_dataset.py", *argv])
    return publish_dataset.main()


def test_dry_run_of_a_v3_file_against_a_live_v2_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    new, live = tmp_path / "new.json", tmp_path / "live.json"
    new.write_text(raw_of(v3_doc()), encoding="utf-8")
    live.write_text(json.dumps(live_v2()), encoding="utf-8")
    argv = [str(new), "--project", "p", "--dry-run", "--allow-test", "--live-file", str(live)]
    assert run(argv, monkeypatch) == 0
    out = capsys.readouterr().out
    assert '"schema": "pi.dataset/v3"' in out
    assert "source guard: ok" in out


def test_main_refuses_a_two_source_v3_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    new = tmp_path / "new.json"
    new.write_text(raw_of(with_context(v3_doc(), "faces_ae", "faces_ae")), encoding="utf-8")
    assert run([str(new), "--project", "p", "--dry-run", "--allow-test"], monkeypatch) == 1
    assert "one source per file" in capsys.readouterr().err


# ------------------------------------------------------------------ what the API serves
def test_the_published_v3_body_serves_its_content_composed_with_a_v2_part(
    tmp_path: Path,
) -> None:
    doc = v3_doc()
    doc["meta"]["test"] = False  # make_client's source refuses test data; this stays in tmp_path
    body, paths, _, _ = packaged(doc)
    faces = json.loads(sephora_only().replace("sephora_me", "faces_ae").replace("p-000", "f-"))
    faces["meta"]["test"] = False
    sephora_path, faces_path = paths[-1], "datasets/ae/faces_ae/latest.json"
    (tmp_path / sephora_path).parent.mkdir(parents=True)
    (tmp_path / sephora_path).write_bytes(body)  # exactly the uploaded (gzipped) bytes
    (tmp_path / faces_path).parent.mkdir(parents=True)
    (tmp_path / faces_path).write_text(json.dumps(faces), encoding="utf-8")
    client, _ = make_client(
        tmp_path,
        paths=(),
        assigned={"sephora_me": sephora_path, "faces_ae": faces_path},
        image_hosts={"sephora_me": frozenset({"media.example"})},
    )
    product_id = doc["products"][0]["id"]
    response = client.get(f"/api/v1/products/{product_id}", headers=bearer())
    assert response.status_code == 200, response.text
    offers = {o["context"]: o["content"] for o in response.json()["data"]["offers"]}
    content = offers[CONTEXT]
    assert content["description"] == {"state": "observed", "text": "A synthetic lipstick."}
    assert content["images"]["items"] == [{"url": "https://media.example/p-1.jpg"}]
    assert content["variants"]["items"][0]["gtin"] == {"state": "observed", "barcode": GTIN}
    other = client.get("/api/v1/products/f-1", headers=bearer())
    assert other.status_code == 200, other.text


# ------------------------------------------------------------------ two contexts of one source
def two_contexts() -> dict[str, Any]:
    """v3_doc() with every product offered in two sephora_me contexts, neither of them using
    the bare retailer id (a v3 rule once a retailer has two): valid v3."""
    doc = v3_doc()
    (ctx,) = doc["meta"]["contexts"]
    doc["meta"]["contexts"] = [ctx | {"id": "sephora_me_en"}, ctx | {"id": "sephora_me_ar"}]
    for product in doc["products"]:
        offer = product["offers"].pop(CONTEXT)
        product["offers"] = {
            "sephora_me_en": offer,
            "sephora_me_ar": json.loads(json.dumps(offer)) | {"content": None},
        }
    return doc


def test_a_two_context_v3_file_packages_under_its_one_source() -> None:
    _, paths, summary, meta_doc = packaged(two_contexts())
    assert paths == [
        "datasets/ae/sephora_me/20260930T000000Z.json",
        "datasets/ae/sephora_me/latest.json",
    ]
    assert summary["source"] == "sephora_me"
    assert meta_doc == "v2_ae_sephora_me"


def test_a_live_two_context_v3_file_is_judged_by_source() -> None:
    """The live side is grouped by source too: its context ids are not sources."""
    live = json.loads(gzip.decompress(packaged(two_contexts())[0]))
    new = publish_dataset.by_source(live)
    assert publish_dataset.guard(live, new, "sephora_me") == []
    smaller = publish_dataset.by_source(json.loads(json.dumps(live)))
    smaller["products"] = smaller["products"][:2]
    assert publish_dataset.guard(live, smaller, "sephora_me") == [
        "HOLD, sephora_me drops from 3 to 2 offers"
    ]


def test_a_live_v3_with_another_retailers_context_holds_by_source_name() -> None:
    live = with_context(v3_doc(), "faces_online", "faces_ae")
    assert publish_dataset.guard(live, new_v3(), "sephora_me") == [
        "HOLD, live source faces_ae (1 offers) is missing"
    ]


# ------------------------------------------------------------------ pi-api must serve it
def test_a_v3_file_pi_api_cannot_serve_is_held_and_nothing_is_uploaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """2026-10-01 rule: a file the contract accepts but pi-api can't load is never uploaded."""
    refusal = "HOLD, pi-api cannot serve this file (1): synthetic refusal"
    monkeypatch.setattr(publish_dataset, "serve_check", lambda raw, *, allow_test: [refusal])
    initialized: list[object] = []
    firebase = types.ModuleType("firebase_admin")
    firebase.initialize_app = lambda **kwargs: initialized.append(kwargs)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "firebase_admin", firebase)
    new = tmp_path / "new.json"
    new.write_text(raw_of(v3_doc()), encoding="utf-8")
    assert run([str(new), "--project", "p", "--allow-test"], monkeypatch) == 1  # not a dry run
    assert f"INVALID: {refusal}" in capsys.readouterr().err
    assert initialized == []
