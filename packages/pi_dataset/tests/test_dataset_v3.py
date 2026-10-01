"""``pi.dataset/v3`` (ADR-0008): models, cross-field rules, ``upgrade`` and ``load_any``."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from pi_dataset import (
    AttributeDef,
    DatasetError,
    DatasetV3,
    ItemKeyKind,
    ProfileDeclaration,
    SizeV3,
    UpgradeError,
    committed_profile,
    committed_profiles,
    dump_dataset,
    load_any,
    load_dataset,
    schema_text,
    upgrade,
)
from pi_dataset.cli import main
from pi_dataset.examples import ae_pilot, render_examples

N, S = "example_north_ae", "example_south_ae"


def _beauty() -> ProfileDeclaration:
    profile = committed_profile("beauty", 1)
    assert profile is not None
    return profile


BEAUTY = _beauty()
#: ``pi.dataset/v2`` is frozen (ADR-0008 §0): its schema changes only with a new contract id.
V2_SCHEMA_SHA256 = "7b2a5d4d486180d456ef8265620f01c976add747083ebcc2bb042095e7b78db4"


def _v3_doc() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(dump_dataset(upgrade(ae_pilot(), BEAUTY)))
    return raw


def _load(doc: dict[str, Any]) -> DatasetV3:
    return DatasetV3.model_validate_json(json.dumps(doc), strict=True)


def _errors(doc: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as info:
        _load(doc)
    return str(info.value)


def _attr(key: str, type_: str, level: str = "offer", **extra: Any) -> dict[str, Any]:
    return {
        "key": key,
        "level": level,
        "type": type_,
        "values": None,
        "label": {"en": key},
        "facet": False,
        "block": None,
        "capability": True,
    } | extra


def _menu(doc: dict[str, Any], *, comparable: bool = True, system: bool = False) -> None:
    """Switch to an uncommitted, non-beauty profile, so contexts and label sizes are allowed."""
    meta = doc["meta"]
    meta["vertical"] = "test_menu"
    meta["profile"] = {
        "name": "test_menu",
        "version": 1,
        "sizeLabelsComparable": comparable,
        "sizeSystemRequired": system,
    }
    meta["attributeSet"] = [
        _attr("finish", "text", "product"),
        _attr("fees", "object", block="fees"),
        _attr("price_band", "money"),
        _attr("spicy", "bool"),
        _attr("kcal", "decimal", block="nutrition"),
        _attr("tags", "text_list"),
        _attr("daypart", "enum", values=[{"id": "breakfast", "label": {"en": "Breakfast"}}]),
        _attr("halal", "bool", capability=False),
    ]


def _key(offer: dict[str, Any], key: str) -> dict[str, Any]:
    offer = copy.deepcopy(offer)
    offer["evidence"] |= {"itemKey": key, "itemKeyKind": "menu_item_id"}
    return offer


def _two_north_contexts(doc: dict[str, Any]) -> None:
    """North sells by delivery and pickup; every north offer is keyed, p-0001 in both contexts."""
    _menu(doc)
    meta = doc["meta"]
    north = next(c for c in meta["contexts"] if c["id"] == N)
    meta["contexts"] = [c for c in meta["contexts"] if c["id"] != N] + [
        north | {"id": "north_delivery", "channel": "delivery"},
        north | {"id": "north_pickup", "channel": "pickup"},
    ]
    for i, product in enumerate(doc["products"]):
        offer = _key(product["offers"].pop(N), f"m{i}")
        product["offers"]["north_delivery"] = offer
        if i == 0:
            product["offers"]["north_pickup"] = copy.deepcopy(offer)


# ---------------------------------------------------------------- upgrade and loading


@pytest.mark.parametrize("name", sorted(render_examples()))
def test_upgrade_round_trips_every_v2_example(name: str) -> None:
    v2 = load_dataset(render_examples()[name], allow_test=True)
    v3 = upgrade(v2, BEAUTY)
    assert load_any(dump_dataset(v3), allow_test=True) == v3
    assert upgrade(v2, BEAUTY) == v3  # deterministic
    assert v3.meta.profile == BEAUTY.info()
    assert v3.meta.attribute_set == BEAUTY.attribute_set
    assert [(c.id, c.retailer, c.channel, c.location) for c in v3.meta.contexts] == [
        (r.id, r.id, "online", None) for r in v2.meta.retailers
    ]
    for old, new in zip(v2.products, v3.products, strict=True):
        assert list(old.offers) == list(new.offers)  # every v2 key is a context id
        assert old.attributes == new.attributes
        for o, n in zip(old.offers.values(), new.offers.values(), strict=True):
            assert o.series == n.series
            assert n.attributes == {}
            kind = None if o.sku is None else ItemKeyKind.SKU
            assert (n.evidence.item_key, n.evidence.item_key_kind) == (o.sku, kind)
            assert (o.size is None) == (n.size is None)
            if o.size is not None and n.size is not None:
                assert (n.size.value, n.size.unit, n.size.label) == (
                    o.size.value,
                    o.size.unit,
                    None,
                )


def test_upgrade_fails_loudly_rather_than_drop_data() -> None:
    v2 = ae_pilot()
    other = BEAUTY.model_copy(update={"name": "food_menu"})
    with pytest.raises(UpgradeError, match="is not profile food_menu@1"):
        upgrade(v2, other)
    product = v2.products[0].model_copy(update={"attributes": {"undeclared_key": "x"}})
    with pytest.raises(UpgradeError, match=r"p-0001\.attributes\.undeclared_key: not declared"):
        upgrade(v2.model_copy(update={"products": (product, *v2.products[1:])}), BEAUTY)
    wrong = v2.products[0].model_copy(update={"attributes": {"finish": ["matte"]}})
    with pytest.raises(UpgradeError, match="not of type text"):
        upgrade(v2.model_copy(update={"products": (wrong, *v2.products[1:])}), BEAUTY)


def _share_url(skus: tuple[str | None, str | None]) -> Any:
    """Products 0 and 1 list one page at ``N``, like size variants of one Sephora page."""
    doc = json.loads(dump_dataset(ae_pilot()))
    for product, sku in zip(doc["products"], skus, strict=False):
        product["offers"][N] |= {"url": "https://north.example/p/serum", "sku": sku}
    return load_dataset(json.dumps(doc), allow_test=True)


def test_upgrade_keys_size_variants_that_share_a_page_by_sku() -> None:
    """Regression: the live beauty file has 1002 such urls; an unkeyed upgrade refused them."""
    v3 = upgrade(_share_url(("SKU-50ML", "SKU-100ML")), BEAUTY)
    evidence = [p.offers[N].evidence for p in v3.products[:2]]
    assert [(e.item_key, e.item_key_kind) for e in evidence] == [
        ("SKU-50ML", ItemKeyKind.SKU),
        ("SKU-100ML", ItemKeyKind.SKU),
    ]
    assert load_any(dump_dataset(v3), allow_test=True) == v3


@pytest.mark.parametrize("skus", [("SKU-SAME", "SKU-SAME"), (None, None)])
def test_upgrade_still_refuses_one_item_in_two_products(
    skus: tuple[str | None, str | None],
) -> None:
    with pytest.raises(UpgradeError):
        upgrade(_share_url(skus), BEAUTY)


def test_readers_check_the_schema_id_first() -> None:
    v3 = dump_dataset(upgrade(ae_pilot(), BEAUTY))
    with pytest.raises(
        DatasetError,
        match=r"^invalid pi.dataset document: unsupported schema pi.dataset/v3; "
        r"this reader accepts pi.dataset/v2$",
    ):
        load_dataset(v3, allow_test=True)
    assert isinstance(load_any(v3, allow_test=True), DatasetV3)
    assert load_any(dump_dataset(ae_pilot()), allow_test=True) == ae_pilot()
    with pytest.raises(DatasetError, match=r"accepts pi\.dataset/v2, pi\.dataset/v3$") as info:
        load_any('{"schema": "pi.dataset/v9", "meta": 1, "extra": 2}')
    assert len(info.value.errors) == 1  # one error, not a pile of field errors
    with pytest.raises(DatasetError, match="unsupported schema None"):
        load_any("[]")
    with pytest.raises(DatasetError, match="synthetic data is refused"):
        load_any(v3)


def test_v2_is_frozen() -> None:
    digest = hashlib.sha256(schema_text().encode()).hexdigest()
    assert digest == V2_SCHEMA_SHA256, "pi.dataset/v2 is frozen (ADR-0008 §0): change v3 instead"


def test_cli_schema_and_validate_v3(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema", "--v3"]) == 0
    assert '"title": "pi.dataset/v3"' in capsys.readouterr().out
    path = tmp_path / "v3.json"
    path.write_bytes(dump_dataset(upgrade(ae_pilot(), BEAUTY)))
    assert main(["validate", "--allow-test", str(path)]) == 1  # the v2 reader refuses v3
    assert "unsupported schema pi.dataset/v3" in capsys.readouterr().err
    assert main(["validate", "--allow-test", "--v3", str(path)]) == 0
    assert ": ok (" in capsys.readouterr().out


# ---------------------------------------------------------------- sizes


@pytest.mark.parametrize(
    ("size", "message"),
    [
        ({"value": None, "unit": None, "label": None, "system": None}, "a value or a label"),
        ({"value": "5", "unit": None, "label": None, "system": None}, "set together"),
        ({"value": None, "unit": "ml", "label": "M", "system": None}, "set together"),
        ({"value": "0", "unit": "ml", "label": None, "system": None}, "must be positive"),
        ({"value": None, "unit": None, "label": None, "system": "eu"}, "a value or a label"),
        ({"value": "5", "unit": "ml", "label": None, "system": "eu"}, "system needs a label"),
    ],
)
def test_bad_sizes(size: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        SizeV3.model_validate(size)


def test_label_sizes_follow_the_profile() -> None:
    label = {"value": None, "unit": None, "label": "Medium", "system": None}
    doc = _v3_doc()
    doc["products"][0]["offers"][N]["size"] = label
    assert "needs a measured size" in _errors(doc)  # beauty stays measured
    _menu(doc, comparable=False)
    assert "needs a measured size" in _errors(doc)
    _menu(doc)
    assert _load(doc).products[0].offers[N].size == SizeV3.model_validate(label)
    _menu(doc, system=True)
    assert "needs a system for every label" in _errors(doc)
    doc["products"][0]["offers"][N]["size"] = label | {"system": "alpha"}
    _load(doc)
    count = {"value": "9", "unit": "pcs", "label": "9 pcs", "system": None}
    doc = _v3_doc()
    doc["products"][0]["offers"][N]["size"] = count  # a count is a measure: fine for beauty
    _load(doc)


# ---------------------------------------------------------------- contexts


def test_multi_context_retailer_is_valid() -> None:
    doc = _v3_doc()
    _two_north_contexts(doc)
    ds = _load(doc)
    assert set(ds.products[0].offers) == {"north_delivery", "north_pickup", S}
    assert ds.context("north_pickup").channel == "pickup"
    assert ds.products[0].matches[0].a == N  # edges stay retailer-keyed


def test_context_id_rule() -> None:
    doc = _v3_doc()
    doc["meta"]["contexts"][0]["id"] = "north_online"
    for product in doc["products"]:
        product["offers"]["north_online"] = product["offers"].pop(N)
    assert "a sole context has its retailer's id" in _errors(doc)

    doc = _v3_doc()
    _two_north_contexts(doc)
    doc["meta"]["contexts"][1]["id"] = N
    doc["products"][0]["offers"][N] = doc["products"][0]["offers"].pop("north_delivery")
    errors = _errors(doc)
    assert "has 2 contexts, so none may use the bare retailer id" in errors

    doc = _v3_doc()
    _two_north_contexts(doc)
    doc["meta"]["contexts"][1]["id"] = S
    assert "id is another retailer's id" in _errors(doc)

    doc = _v3_doc()
    doc["meta"]["contexts"].append(doc["meta"]["contexts"][0] | {"retailer": "nobody"})
    errors = _errors(doc)
    assert "unknown retailer nobody" in errors
    assert f"duplicate id {N}" in errors

    doc = _v3_doc()
    doc["meta"]["contexts"] = doc["meta"]["contexts"][:1]
    assert f"retailer {S} has no context" in _errors(doc)


def test_beauty_contexts_are_online_without_location() -> None:
    doc = _v3_doc()
    doc["meta"]["contexts"][0]["channel"] = "delivery"
    assert "a beauty context is online with no location" in _errors(doc)
    doc = _v3_doc()
    doc["meta"]["contexts"][0]["location"] = {
        "id": "marina",
        "label": {"en": "Marina"},
        "city": "Dubai",
        "area": None,
    }
    assert "a beauty context is online with no location" in _errors(doc)


def test_offers_and_edges_reference_contexts_and_retailers() -> None:
    doc = _v3_doc()
    doc["products"][0]["offers"]["ghost"] = doc["products"][0]["offers"][N]
    assert "offers.ghost: unknown context" in _errors(doc)
    doc = _v3_doc()
    del doc["products"][0]["offers"][S]
    assert "names retailers without an offer" in _errors(doc)
    doc = _v3_doc()
    doc["products"][0]["matches"].append(doc["products"][0]["matches"][0])
    assert "duplicate match edge" in _errors(doc)
    doc = _v3_doc()
    doc["products"][0]["offers"][N]["series"]["price"].append(None)
    assert "length 4 != 3 dates" in _errors(doc)
    doc = _v3_doc()
    doc["products"][1]["id"] = doc["products"][0]["id"]
    assert "duplicate id p-0001" in _errors(doc)


def test_not_observed_context_belongs_to_its_retailer() -> None:
    doc = _v3_doc()
    window = {
        "retailer": S,
        "start": doc["meta"]["dates"][0],
        "end": doc["meta"]["dates"][0],
        "categories": None,
        "why": {"en": "not crawled"},
        "context": S,
    }
    doc["notObserved"] = [window]
    _load(doc)
    doc["notObserved"] = [window | {"context": N}]
    assert f"context {N} is not one of {S}'s" in _errors(doc)
    doc["notObserved"] = [window | {"retailer": "nobody", "context": None}]
    assert "unknown retailer nobody" in _errors(doc)


# ---------------------------------------------------------------- identity rules (a)-(c)


def test_unkeyed_offer_must_be_its_retailers_only_offer() -> None:
    doc = _v3_doc()
    _two_north_contexts(doc)
    doc["products"][0]["offers"]["north_pickup"]["evidence"] |= {
        "itemKey": None,
        "itemKeyKind": None,
    }
    assert "unkeyed offer next to another of its offers (c)" in _errors(doc)


def test_one_retailers_offers_share_one_item_key() -> None:
    doc = _v3_doc()
    _two_north_contexts(doc)
    doc["products"][0]["offers"]["north_pickup"]["evidence"]["itemKey"] = "other"
    assert "carry different itemKeys" in _errors(doc)


def test_a_keyed_item_is_in_one_product() -> None:
    doc = _v3_doc()
    _two_north_contexts(doc)
    doc["products"][1]["offers"]["north_delivery"]["evidence"]["itemKey"] = "m0"
    assert "itemKey m0 is in several products ['p-0001', 'p-0002'] (a)" in _errors(doc)


def test_an_unkeyed_url_is_in_one_product() -> None:
    doc = _v3_doc()
    for product in doc["products"]:  # the upgrade keys every example offer by its sku
        product["offers"][N]["evidence"] |= {"itemKey": None, "itemKeyKind": None}
    doc["products"][0]["offers"][N]["url"] = "https://north.example/p/1#reviews"
    doc["products"][2]["offers"][N]["url"] = "https://north.example/p/1"
    assert "url https://north.example/p/1 is in several products" in _errors(doc)
    doc["products"][2]["offers"][N]["url"] = "https://north.example/p/2"
    _load(doc)


def test_multi_context_retailer_offers_need_item_key_or_url() -> None:
    doc = _v3_doc()
    _two_north_contexts(doc)
    offer = doc["products"][2]["offers"]["north_delivery"]
    offer["evidence"] |= {"itemKey": None, "itemKeyKind": None}
    assert "needs an itemKey or a url" in _errors(doc)
    offer["url"] = "https://north.example/p/3"
    _load(doc)


def test_item_key_and_kind_go_together() -> None:
    doc = _v3_doc()
    evidence = doc["products"][0]["offers"][N]["evidence"]
    evidence["itemKeyKind"] = None
    assert "itemKey and itemKeyKind are set together" in _errors(doc)
    evidence |= {"itemKey": None, "itemKeyKind": "sku"}
    assert "itemKey and itemKeyKind are set together" in _errors(doc)


# ---------------------------------------------------------------- declared attributes


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("fees", {"delivery": {"amount": "7.00", "minor": 700, "currency": "AED"}, "note": "x"}),
        ("fees", {"tiers": [{"amount": "1.50", "minor": 150, "currency": "AED"}]}),
        ("price_band", {"amount": "10.00", "minor": 1000, "currency": "AED"}),
        ("spicy", False),
        ("kcal", "540.5"),
        ("tags", ["vegan", "new"]),
        ("daypart", "breakfast"),
    ],
)
def test_good_offer_attributes(key: str, value: Any) -> None:
    doc = _v3_doc()
    _menu(doc)
    doc["products"][0]["offers"][N]["attributes"] = {key: value}
    assert _load(doc).products[0].offers[N].attributes == {key: value}


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("unknown", "x", "unknown: not a declared offer attribute"),
        ("finish", "matte", "finish: not a declared offer attribute"),  # product-level key
        ("halal", True, "declared as not collected"),
        ("daypart", "dinner", "'dinner' is not one of ['breakfast']"),
        ("kcal", "1e3", "not of type decimal"),
        ("kcal", 540, "not of type decimal"),
        ("spicy", "yes", "not of type bool"),
        ("tags", ["ok", " "], "not of type text_list"),
        ("price_band", {"amount": "10.00"}, "not of type money"),
        ("price_band", {"amount": "10.000", "minor": 10000, "currency": "KWD"}, "in KWD"),
        ("price_band", {"amount": "10.0", "minor": 1000, "currency": "AED"}, "bad money"),
        (
            "fees",
            {"service": {"amount": "1.000", "minor": 1000, "currency": "KWD"}},
            "fees.service: money in KWD",
        ),
        (
            "fees",
            {"tiers": [{"x": {"amount": "1.00", "minor": 100, "currency": "USD"}}]},
            "fees.tiers.0.x: money in USD",
        ),
        ("fees", ["not", "an", "object"], "not of type object"),
        # An enum value that isn't a string is an error, not an unhashable TypeError (#75 M1).
        ("daypart", ["breakfast"], "['breakfast'] is not one of ['breakfast']"),
        ("daypart", {"id": "breakfast"}, "is not one of ['breakfast']"),
        # Any object with a currency is money and is checked strictly (#75 M2).
        (
            "fees",
            {"delivery": {"amount": "7.00", "minor": 700, "currency": "USD", "note": "x"}},
            "fees.delivery: bad money",
        ),
        ("fees", {"delivery": {"amount": "7.00", "currency": "USD"}}, "fees.delivery: bad money"),
        ("fees", {"delivery": {"currency": "AED"}}, "fees.delivery: bad money"),
        # ... and so is any object with a minor: a lost currency is an error, not data (#75 nit).
        ("fees", {"delivery": {"amount": "7.00", "minor": 700}}, "fees.delivery: bad money"),
        ("fees", {"tiers": [{"minor": 700}]}, "fees.tiers.0: bad money"),
        ("price_band", {"amount": "10.00", "minor": 1000}, "price_band: bad money"),
        (
            "price_band",
            {"amount": "10.00", "minor": 1000, "currency": "AED", "note": "x"},
            "price_band: bad money",
        ),
    ],
)
def test_bad_offer_attributes(key: str, value: Any, message: str) -> None:
    doc = _v3_doc()
    _menu(doc)
    doc["products"][0]["offers"][N]["attributes"] = {key: value}
    assert message in _errors(doc)


def test_product_attributes_are_declared_product_keys() -> None:
    doc = _v3_doc()
    doc["products"][0]["attributes"] = {"shadeFamilies": ["Nude"], "finish": "satin"}
    _load(doc)
    doc["products"][0]["attributes"] = {"fees": {}}
    assert "fees: not a declared product attribute" in _errors(doc)
    _menu(doc)
    doc["products"][0]["attributes"] = {"finish": ""}
    assert "not of type text" in _errors(doc)


def test_text_attribute_values_are_checked() -> None:
    doc = _v3_doc()
    _menu(doc)
    doc["meta"]["attributeSet"].append(_attr("note", "money", "product"))
    doc["products"][0]["attributes"] = {
        "note": {"amount": "1.000", "minor": 1000, "currency": "KWD"}
    }
    assert "money in KWD, expected ['AED']" in _errors(doc)  # product money: market currency


# ---------------------------------------------------------------- the profile


def test_meta_profile_matches_the_committed_declaration() -> None:
    doc = _v3_doc()
    doc["meta"]["vertical"] = "other"
    assert "meta.vertical other != meta.profile.name beauty" in _errors(doc)
    doc = _v3_doc()
    doc["meta"]["profile"]["sizeLabelsComparable"] = True
    assert "size flags differ from the committed beauty@1" in _errors(doc)
    doc = _v3_doc()
    doc["meta"]["attributeSet"].append(_attr("extra", "text", "product"))
    assert "differs from the committed beauty@1 (undeclared keys ['extra'])" in _errors(doc)
    doc = _v3_doc()
    doc["meta"]["profile"]["version"] = 99
    assert "beauty@99 is not a committed profile" in _errors(doc)
    doc = _v3_doc()
    _menu(doc)
    doc["meta"]["attributeSet"].append(doc["meta"]["attributeSet"][0])
    assert "duplicate key finish" in _errors(doc)


def test_committed_profiles() -> None:
    assert committed_profiles() == ("beauty@1",)
    assert BEAUTY.ref == "beauty@1"
    assert (BEAUTY.size_labels_comparable, BEAUTY.size_system_required) == (False, False)
    assert {a.key for a in BEAUTY.attribute_set} == {"finish", "concentration", "shadeFamilies"}
    assert committed_profile("beauty", 2) is None


def test_attribute_declarations() -> None:
    with pytest.raises(ValidationError, match="values are required exactly for type enum"):
        AttributeDef.model_validate(_attr("daypart", "enum"))
    with pytest.raises(ValidationError, match="values are required exactly for type enum"):
        AttributeDef.model_validate(
            _attr("daypart", "text", values=[{"id": "a", "label": {"en": "A"}}])
        )
    with pytest.raises(ValidationError, match="duplicate enum value ids"):
        AttributeDef.model_validate(
            _attr("dd", "enum", values=[{"id": "a", "label": {"en": "A"}}] * 2)
        )
    with pytest.raises(ValidationError, match="duplicate attribute keys"):
        ProfileDeclaration.model_validate(
            BEAUTY.model_dump() | {"attributeSet": [_attr("kk", "text")] * 2}
        )


@pytest.mark.parametrize("value", [["breakfast"], {"id": "breakfast"}])
def test_load_any_reports_a_non_string_enum_as_a_dataset_error(value: Any) -> None:
    doc = _v3_doc()
    _menu(doc)
    doc["products"][0]["offers"][N]["attributes"] = {"daypart": value}
    with pytest.raises(DatasetError, match="is not one of"):
        load_any(json.dumps(doc), allow_test=True)
