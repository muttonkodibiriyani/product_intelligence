"""load_dataset / dump_dataset / json_schema and the CLI."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from pi_dataset import DatasetError, dump_dataset, json_schema, load_dataset
from pi_dataset.cli import main
from pi_dataset.examples import ae_pilot, write_examples


def _text(**meta: Any) -> str:
    doc = ae_pilot().model_dump(mode="json")
    doc["meta"].update(meta)
    return json.dumps(doc, ensure_ascii=False)


def test_load_accepts_bytes_and_text() -> None:
    raw = dump_dataset(ae_pilot())
    assert load_dataset(raw, allow_test=True) == ae_pilot()
    assert load_dataset(raw.decode(), allow_test=True) == ae_pilot()


def test_test_data_is_refused_unless_allowed() -> None:
    with pytest.raises(DatasetError, match=r"meta\.test is true"):
        load_dataset(dump_dataset(ae_pilot()))
    assert load_dataset(_text(test=False)).meta.test is False


def _patched(path: tuple[str | int, ...], value: Any) -> str:
    doc = ae_pilot().model_dump(mode="json")
    target: Any = doc
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return json.dumps(doc, ensure_ascii=False)


_OFFER = ("products", 0, "offers", "example_north_ae")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ((*_OFFER, "series", "price", 0, "minor"), "12900"),
        ((*_OFFER, "rating", "count"), "12"),
        ((*_OFFER, "shadeCount"), False),
        ((*_OFFER, "early"), 0),
        ((*_OFFER, "early"), "false"),
        (("meta", "capabilities", "history"), "true"),
    ],
)
def test_load_does_not_coerce(path: tuple[str | int, ...], value: Any) -> None:
    with pytest.raises(DatasetError):
        load_dataset(_patched(path, value), allow_test=True)


@pytest.mark.parametrize("value", ["false", 0, None])
def test_test_flag_must_be_a_real_boolean(value: Any) -> None:
    # "false" must not load as meta.test = False and slip past allow_test.
    with pytest.raises(DatasetError):
        load_dataset(_patched(("meta", "test"), value))


@pytest.mark.parametrize("number", ["129.5", "1e3", "NaN", "Infinity"])
def test_json_floats_are_refused(number: str) -> None:
    text = _text(test=False).replace('"shadeCount": 0', f'"shadeCount": {number}', 1)
    with pytest.raises(DatasetError, match="JSON float"):
        load_dataset(text)


@pytest.mark.parametrize(
    "snippet",
    [
        '"x-algolia-api-key"',
        '"algoliaSearchKey": "abcdefghijklmnop"',
        '"api_key":',
        '"appId":',
    ],
)
def test_credential_like_content_is_refused(snippet: str) -> None:
    text = _text(test=False).replace('"matchStage"', f'{snippet} 1, "matchStage"', 1)
    with pytest.raises(DatasetError, match="forbidden credential-like content"):
        load_dataset(text)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("{", "not JSON"),
        ("[]", "unsupported schema None; this reader accepts pi.dataset/v2"),
        ('{"schema": "pi.dataset/v1"}', "unsupported schema pi.dataset/v1"),
    ],
)
def test_malformed_documents(raw: str, message: str) -> None:
    with pytest.raises(DatasetError, match=message):
        load_dataset(raw)


def test_every_validation_problem_is_listed_with_its_path() -> None:
    doc = json.loads(_text(test=False))
    doc["meta"]["scope"] = "BAD SCOPE"
    doc["products"][0]["brand"] = " "
    with pytest.raises(DatasetError) as info:
        load_dataset(json.dumps(doc))
    paths = [e.split(":")[0] for e in info.value.errors]
    assert "meta.scope" in paths
    assert "products.0.brand" in paths


def test_dump_is_canonical_utf8() -> None:
    raw = dump_dataset(ae_pilot())
    assert raw.endswith(b"}\n")
    assert "عينات".encode() in raw
    assert dump_dataset(load_dataset(raw, allow_test=True)) == raw


def _walk(node: Any) -> list[Any]:
    found = [node]
    if isinstance(node, dict):
        for value in node.values():
            found += _walk(value)
    elif isinstance(node, list):
        for value in node:
            found += _walk(value)
    return found


def test_schema_has_no_floats_and_is_2020_12() -> None:
    schema = json_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "pi.dataset/v2"
    types = [n.get("type") for n in _walk(schema) if isinstance(n, dict)]
    assert "number" not in types
    assert "integer" in types


def test_schema_uses_wire_names() -> None:
    schema = json_schema()
    assert "schema" in schema["properties"]
    assert "notObserved" in schema["properties"]
    assert "generatedAt" in schema["$defs"]["Meta"]["properties"]


# ------------------------------------------------------------------ CLI


def test_cli_validates_json_and_gzip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = tmp_path / "good.json.gz"
    good.write_bytes(gzip.compress(dump_dataset(ae_pilot())))
    assert main(["validate", "--allow-test", str(good)]) == 0
    assert "ok (AE/pilot, 3 products)" in capsys.readouterr().out


def test_cli_reports_every_problem(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = tmp_path / "good.json"
    good.write_bytes(dump_dataset(ae_pilot()))
    missing = tmp_path / "missing.json"
    assert main(["validate", str(good), str(missing)]) == 1
    err = capsys.readouterr().err
    assert f"{good}: INVALID" in err
    assert "meta.test is true" in err
    assert f"{missing}: INVALID" in err


def test_cli_schema_and_examples(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema"]) == 0
    assert json.loads(capsys.readouterr().out)["title"] == "pi.dataset/v2"
    assert main(["examples", str(tmp_path / "ex")]) == 0
    written = sorted(p.name for p in (tmp_path / "ex").iterdir())
    assert written == ["ae-pilot.json", "fr-two-retailers.json", "kw-three-retailers.json"]
    assert write_examples(tmp_path / "ex")[0].exists()
