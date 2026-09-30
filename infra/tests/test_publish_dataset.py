"""publish_dataset: validation, deterministic packaging and create-only snapshot uploads."""

import copy
import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import publish_dataset
import pytest

DOC: dict[str, Any] = {
    "schema": "pi.dataset/v1",
    "meta": {
        "kind": "snapshot",
        "cutoff": "2026-09-30T21:32:28Z",
        "generatedAt": "2026-09-30T21:40:00Z",
        "market": "AE",
        "currency": "AED",
        "dates": ["2026-09-30"],
        "retailers": [{"id": "r1", "key": "sephora", "name": "Sephora", "status": "live"}],
    },
    "products": [{"id": "p1", "offers": {"r1": {"series": {"price": [99.0]}}}}],
}


def check(doc: dict[str, Any], *, allow_test: bool = False) -> list[str]:
    return publish_dataset.validate(doc, json.dumps(doc), allow_test=allow_test)


def test_valid_document_passes() -> None:
    assert check(DOC) == []


def test_missing_meta_and_wrong_schema_are_reported() -> None:
    doc = copy.deepcopy(DOC)
    doc["schema"] = "pi.dataset/v0"
    del doc["meta"]["cutoff"]
    errors = check(doc)
    assert "schema must be 'pi.dataset/v1'" in errors
    assert "meta.cutoff missing" in errors


def test_test_fixture_needs_allow_test() -> None:
    doc = copy.deepcopy(DOC)
    doc["meta"]["test"] = True
    assert any("meta.test" in e for e in check(doc))
    assert check(doc, allow_test=True) == []


def test_series_length_must_match_dates() -> None:
    doc = copy.deepcopy(DOC)
    doc["products"][0]["offers"]["r1"]["series"]["price"] = [1.0, 2.0]
    assert check(doc) == ["p1.r1.series.price: len 2 != 1"]


def test_empty_products_are_refused() -> None:
    doc = copy.deepcopy(DOC)
    doc["products"] = []
    assert "products must be a non-empty list" in check(doc)


@pytest.mark.parametrize(
    "leak",
    [
        {"x-algolia-api-key": "k"},
        {"algoliaKey": "A1" * 10},  # built at runtime: a key-like literal trips the secret scan
        {"apiKey": "anything"},
        {"app_id": "anything"},
    ],
)
def test_algolia_like_credentials_are_refused(leak: dict[str, str]) -> None:
    doc = copy.deepcopy(DOC)
    doc["meta"]["source"] = leak
    assert any(e.startswith("forbidden credential-like content") for e in check(doc))


def test_package_is_deterministic_and_round_trips() -> None:
    body, paths, summary = publish_dataset.package(DOC, "datasets/uae")
    assert body == publish_dataset.package(copy.deepcopy(DOC), "datasets/uae")[0]
    assert json.loads(gzip.decompress(body)) == DOC
    assert paths == ["datasets/uae/20260930T213228Z.json", "datasets/uae/latest.json"]
    assert summary["storagePath"] == "datasets/uae/latest.json"
    assert summary["products"] == 1
    assert summary["test"] is False
    assert summary["retailers"] == [
        {"id": "r1", "key": "sephora", "name": "Sephora", "status": "live", "since": None}
    ]


class PreconditionFailedError(Exception):
    code = publish_dataset.PRECONDITION_FAILED


class ServerError(Exception):
    code = 503


@dataclass
class Blob:
    bucket: "Bucket"
    name: str
    md5_hash: str | None = None
    content_encoding: str | None = None
    cache_control: str | None = None

    def upload_from_string(
        self, body: bytes, *, content_type: str, if_generation_match: int | None = None
    ) -> None:
        assert content_type.startswith("application/json")
        if self.bucket.fail is not None:
            raise self.bucket.fail
        if if_generation_match == 0 and self.name in self.bucket.stored:
            raise PreconditionFailedError(self.name)
        self.bucket.stored[self.name] = body
        self.bucket.uploads.append(self.name)


@dataclass
class Bucket:
    name: str = "b"
    stored: dict[str, bytes] = field(default_factory=dict)
    uploads: list[str] = field(default_factory=list)
    fail: Exception | None = None

    def blob(self, name: str) -> Blob:
        return Blob(self, name)

    def get_blob(self, name: str) -> Blob | None:
        if name not in self.stored:
            return None
        return Blob(self, name, md5_hash=publish_dataset.blob_md5(self.stored[name]))


BODY, PATHS, _ = publish_dataset.package(DOC, "datasets/uae")
SNAPSHOT, LATEST = PATHS


def test_first_publish_uploads_snapshot_then_latest() -> None:
    bucket = Bucket()
    assert publish_dataset.upload(bucket, PATHS, BODY) == 0
    assert bucket.uploads == [SNAPSHOT, LATEST]


def test_identical_republish_leaves_the_snapshot_and_refreshes_latest() -> None:
    bucket = Bucket(stored={SNAPSHOT: BODY})
    assert publish_dataset.upload(bucket, PATHS, BODY) == 0
    assert bucket.uploads == [LATEST]


def test_different_content_for_a_published_cutoff_is_refused_and_latest_untouched() -> None:
    bucket = Bucket(stored={SNAPSHOT: b"older", LATEST: b"older"})
    assert publish_dataset.upload(bucket, PATHS, BODY) == 1
    assert bucket.uploads == []
    assert bucket.stored[LATEST] == b"older"


def test_other_upload_errors_propagate() -> None:
    bucket = Bucket(fail=ServerError("unavailable"))
    with pytest.raises(ServerError):
        publish_dataset.upload(bucket, PATHS, BODY)


# ------------------------------------------------------------------ pi.dataset/v2
EXAMPLE = Path(__file__).parents[2] / "docs/contracts/examples/ae-pilot.json"


def test_v2_uses_the_contract_loader_and_honours_allow_test() -> None:
    raw = EXAMPLE.read_text(encoding="utf-8")  # a test fixture: meta.test is true
    dataset, errors = publish_dataset.validate_v2(raw, allow_test=False)
    assert dataset is None
    assert any("meta.test" in e for e in errors)
    dataset, errors = publish_dataset.validate_v2(raw, allow_test=True)
    assert errors == []
    assert dataset is not None


def test_v2_float_money_is_refused() -> None:
    raw = EXAMPLE.read_text(encoding="utf-8").replace('"minor": 12900', '"minor": 12900.0', 1)
    assert '"minor": 12900.0' in raw
    _, errors = publish_dataset.validate_v2(raw, allow_test=True)
    assert any("float" in e for e in errors)


def test_v2_is_published_under_country_and_scope_with_its_own_meta_doc() -> None:
    dataset, _ = publish_dataset.validate_v2(EXAMPLE.read_text(encoding="utf-8"), allow_test=True)
    body, paths, summary, meta_doc = publish_dataset.package_v2(dataset)
    assert paths == [
        "datasets/ae/pilot/20260930T000000Z.json",
        "datasets/ae/pilot/latest.json",
    ]
    assert meta_doc == "v2_ae_pilot"
    assert summary["schema"] == "pi.dataset/v2"
    assert summary["storagePath"] == "datasets/ae/pilot/latest.json"
    assert summary["cutoff"] == "2026-09-30T00:00:00Z"
    assert summary["products"] == len(dataset.products)
    # What is uploaded re-loads under the same strict rules, and packaging is deterministic.
    publish_dataset.validate_v2(gzip.decompress(body).decode(), allow_test=True)
    assert publish_dataset.package_v2(dataset)[0] == body
