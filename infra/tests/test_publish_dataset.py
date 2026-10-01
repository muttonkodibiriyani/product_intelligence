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
    data: bytes = b""
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

    def download_as_bytes(self, *, raw_download: bool = False) -> bytes:
        assert raw_download  # the stored gzip body, not a transcoded one
        return self.data


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
        body = self.stored[name]
        return Blob(self, name, md5_hash=publish_dataset.blob_md5(body), data=body)


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


def export_of_same_cutoff(generated_at: str, price: float = 98.0) -> bytes:
    """Another export of DOC's cutoff: different content, the given generatedAt."""
    doc = copy.deepcopy(DOC)
    doc["meta"]["generatedAt"] = generated_at
    doc["products"][0]["offers"]["r1"]["series"]["price"] = [price]
    return publish_dataset.package(doc, "datasets/uae")[0]


REVISION = "datasets/uae/20260930T213228Z-g20260930T214000Z.json"  # DOC's generatedAt


@pytest.mark.parametrize(
    "published_at", ["2026-09-30T21:40:00Z", "2026-09-30T21:50:00Z"], ids=["equal", "older"]
)
def test_same_cutoff_not_generated_later_is_refused_and_latest_untouched(published_at: str) -> None:
    old = export_of_same_cutoff(published_at)  # this file (BODY) was generated 21:40
    bucket = Bucket(stored={SNAPSHOT: old, LATEST: old})
    assert publish_dataset.upload(bucket, PATHS, BODY) == 1
    assert bucket.uploads == []
    assert bucket.stored == {SNAPSHOT: old, LATEST: old}


def test_later_export_of_a_published_cutoff_gets_a_revision_copy_then_latest() -> None:
    old = export_of_same_cutoff("2026-09-30T21:35:00Z")
    bucket = Bucket(stored={SNAPSHOT: old, LATEST: old})
    assert publish_dataset.upload(bucket, PATHS, BODY) == 0
    assert bucket.uploads == [REVISION, LATEST]
    assert bucket.stored == {SNAPSHOT: old, REVISION: BODY, LATEST: BODY}  # original kept


def test_identical_revision_republish_leaves_it_and_refreshes_latest() -> None:
    old = export_of_same_cutoff("2026-09-30T21:35:00Z")
    bucket = Bucket(stored={SNAPSHOT: old, REVISION: BODY, LATEST: old})
    assert publish_dataset.upload(bucket, PATHS, BODY) == 0
    assert bucket.uploads == [LATEST]


def test_revision_existing_with_different_content_is_refused_and_latest_untouched() -> None:
    old = export_of_same_cutoff("2026-09-30T21:35:00Z")
    other = export_of_same_cutoff("2026-09-30T21:40:00Z", price=97.0)  # same revision key
    bucket = Bucket(stored={SNAPSHOT: old, REVISION: other, LATEST: old})
    assert publish_dataset.upload(bucket, PATHS, BODY) == 1
    assert bucket.uploads == []
    assert bucket.stored == {SNAPSHOT: old, REVISION: other, LATEST: old}


def test_revision_key_uses_whole_seconds_of_a_fractional_generated_at() -> None:
    gen = publish_dataset.generated_at(b'{"meta": {"generatedAt": "2026-10-01T06:47:18.016114Z"}}')
    path = publish_dataset.revision_path("datasets/ae/beauty/20261001T032000Z.json", gen)
    assert path == "datasets/ae/beauty/20261001T032000Z-g20261001T064718Z.json"


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


def _shared_listing(raw: str) -> str:
    """Two products carrying the same listing (url and sku): valid v2, but pi-api can't serve it."""
    doc = json.loads(raw)
    first = doc["products"][0]
    first["offers"][next(iter(first["offers"]))]["url"] = "https://shop.example/p/1"
    twin = copy.deepcopy(first)
    twin["id"] = f"{first['id']}-twin"
    doc["products"].append(twin)
    return json.dumps(doc)


def test_v2_that_pi_api_cannot_serve_is_held() -> None:
    raw = _shared_listing(EXAMPLE.read_text(encoding="utf-8"))
    dataset, errors = publish_dataset.validate_v2(raw, allow_test=True)
    assert dataset is None
    assert errors
    assert all(e.startswith("HOLD, pi-api cannot serve this file") for e in errors)
    assert any("is in several products" in e for e in errors)


def test_held_file_is_never_uploaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "held.json"
    path.write_text(_shared_listing(EXAMPLE.read_text(encoding="utf-8")), encoding="utf-8")
    argv = ["publish_dataset.py", str(path), "--project", "demo-pi", "--allow-test"]
    monkeypatch.setattr("sys.argv", argv)  # not --dry-run: it must stop before Firebase
    assert publish_dataset.main() == 1
    assert "INVALID: HOLD, pi-api cannot serve this file" in capsys.readouterr().err


def test_generated_at_is_normalised_to_utc_and_needs_a_timezone() -> None:
    gen = publish_dataset.generated_at(b'{"meta": {"generatedAt": "2026-10-01T10:47:18+04:00"}}')
    path = publish_dataset.revision_path("datasets/ae/beauty/20261001T032000Z.json", gen)
    assert path == "datasets/ae/beauty/20261001T032000Z-g20261001T064718Z.json"
    with pytest.raises(ValueError, match="no timezone"):
        publish_dataset.generated_at(b'{"meta": {"generatedAt": "2026-10-01T06:47:18"}}')
