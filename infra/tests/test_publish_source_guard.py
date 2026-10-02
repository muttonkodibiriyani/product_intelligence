"""publish_dataset: one source per file, per-source prefixes, and the live-source guard."""

import gzip
import json
from pathlib import Path
from typing import Any

import publish_dataset
import pytest

EXAMPLE = Path(__file__).parents[2] / "docs/contracts/examples/ae-pilot.json"


def _without(o: Any, retailer: str) -> Any:
    """Drop every trace of ``retailer`` (offers, meta entry, match edges) from an example."""
    if isinstance(o, dict):
        return {k: _without(v, retailer) for k, v in o.items() if k != retailer}
    if isinstance(o, list):
        return [
            _without(v, retailer)
            for v in o
            if v != retailer
            and not (isinstance(v, dict) and retailer in (v.get("id"), v.get("a"), v.get("b")))
        ]
    return o


def sephora_only() -> str:
    """The ae-pilot example reduced to its north retailer, renamed sephora_me: a valid v2 file."""
    doc = _without(json.loads(EXAMPLE.read_text(encoding="utf-8")), "example_south_ae")
    doc["products"] = [p for p in doc["products"] if p.get("offers")]
    return json.dumps(doc).replace("example_north_ae", "sephora_me")


def catalog(**counts: int) -> dict[str, Any]:
    """A minimal v2-shaped document: ``counts`` single-source products per source."""
    products = [
        {"id": f"{source}-{i}", "offers": {source: {"price": "1.00"}}}
        for source, n in counts.items()
        for i in range(n)
    ]
    return {"schema": "pi.dataset/v2", "meta": {}, "products": products}


# ------------------------------------------------------------------ which file, which path
def test_a_sephora_file_goes_under_its_own_source_prefix() -> None:
    dataset, errors = publish_dataset.validate_v2(sephora_only(), allow_test=True)
    assert errors == []
    body, paths, summary, meta_doc = publish_dataset.package_v2(dataset)
    assert paths == [
        "datasets/ae/sephora_me/20260930T000000Z.json",
        "datasets/ae/sephora_me/latest.json",
    ]
    assert publish_dataset.outside_prefixes(paths) == []
    assert meta_doc == "v2_ae_sephora_me"
    assert summary["source"] == "sephora_me"
    assert summary["storagePath"] == "datasets/ae/sephora_me/latest.json"
    assert publish_dataset.offer_counts(json.loads(gzip.decompress(body))) == {"sephora_me": 3}


def test_packaging_is_deterministic() -> None:
    one, _ = publish_dataset.validate_v2(sephora_only(), allow_test=True)
    two, _ = publish_dataset.validate_v2(sephora_only(), allow_test=True)
    assert publish_dataset.package_v2(one)[0] == publish_dataset.package_v2(two)[0]


def test_a_file_with_two_sources_is_refused() -> None:
    doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    allowed = ("example_north_ae", "example_south_ae")
    source, errors = publish_dataset.publishing_source(doc, allowed)
    assert source is None
    assert errors == [
        "one source per file: offers come from ['example_north_ae', 'example_south_ae']"
    ]
    dataset, _ = publish_dataset.validate_v2(json.dumps(doc), allow_test=True)
    with pytest.raises(ValueError, match="one source per file"):
        publish_dataset.package_v2(dataset, allowed)


def test_only_sources_pi_publishes_are_accepted() -> None:
    assert publish_dataset.PUBLISH_SOURCES == ("sephora_me",)
    assert publish_dataset.publishing_source(catalog(sephora_me=2)) == ("sephora_me", [])
    source, errors = publish_dataset.publishing_source(catalog(ulta_ae=2))
    assert source is None
    assert errors == ["ulta_ae is not a source PI publishes (sephora_me)"]
    assert publish_dataset.publishing_source(catalog())[0] is None


@pytest.mark.parametrize(
    "path",
    [
        "datasets/ae/beauty/latest.json",  # the combined file with the owner's Ulta rows
        "datasets/ae/beauty/20261001T032000Z.json",
        "datasets/uae/latest.json",
        "datasets/ae/ulta_ae/latest.json",
        "datasets/ae/sephora_me/../beauty/latest.json",
        "datasets/ae/sephora_me/nested/latest.json",
    ],
)
def test_writes_outside_the_sephora_prefix_are_refused(path: str) -> None:
    assert publish_dataset.outside_prefixes([path]) == [path]


def test_a_trailing_newline_does_not_pass_the_prefix_check() -> None:
    paths = ["datasets/ae/sephora_me/latest.json\n", "datasets/uae/latest.json\n"]
    assert publish_dataset.outside_prefixes(paths[:1]) == paths[:1]
    assert publish_dataset.outside_prefixes(paths[1:], v1=True) == paths[1:]


# ------------------------------------------------------------------ the live-source guard
def test_sephora_only_file_against_the_live_combined_file_is_held() -> None:
    live = catalog(sephora_me=9529, ulta_ae=7275)
    new = catalog(sephora_me=9529)
    assert publish_dataset.source_guard(live, new, "sephora_me") == [
        "HOLD, live source ulta_ae (7275 offers) is missing"
    ]


def test_first_publish_to_a_new_path_has_nothing_to_lose() -> None:
    assert publish_dataset.source_guard(None, catalog(sephora_me=1), "sephora_me") == []


def test_more_or_changed_offers_of_the_published_source_pass() -> None:
    live = catalog(sephora_me=2)
    new = catalog(sephora_me=3)
    new["products"][0]["offers"]["sephora_me"]["price"] = "2.00"
    assert publish_dataset.source_guard(live, new, "sephora_me") == []


def test_fewer_offers_are_held() -> None:
    held = publish_dataset.source_guard(
        catalog(sephora_me=9529), catalog(sephora_me=9000), "sephora_me"
    )
    assert held == ["HOLD, sephora_me drops from 9529 to 9000 offers"]


def test_another_sources_products_must_be_byte_identical() -> None:
    live = catalog(sephora_me=2, ulta_ae=2)
    new = catalog(sephora_me=2, ulta_ae=2)
    new["products"][-1]["offers"]["ulta_ae"]["price"] = "9.99"
    assert publish_dataset.source_guard(live, new, "sephora_me") == [
        "HOLD, ulta_ae is not sephora_me's to change: its products differ"
    ]
    new["products"].reverse()  # order alone is not a change
    live["products"][-1]["offers"]["ulta_ae"]["price"] = "9.99"
    assert publish_dataset.source_guard(live, new, "sephora_me") == []


def test_drop_source_is_the_only_override() -> None:
    live = catalog(sephora_me=9529, other_ae=7275)
    assert (
        publish_dataset.source_guard(live, catalog(sephora_me=9529), "sephora_me", ("other_ae",))
        == []
    )
    held = publish_dataset.source_guard(live, catalog(sephora_me=9000), "sephora_me", ("other_ae",))
    assert held == ["HOLD, sephora_me drops from 9529 to 9000 offers"]


def test_ulta_is_never_dropped_even_when_asked() -> None:
    live = catalog(sephora_me=9529, ulta_ae=7275)
    held = publish_dataset.source_guard(live, catalog(sephora_me=9529), "sephora_me", ("ulta_ae",))
    assert held == ["HOLD, live source ulta_ae (7275 offers) is missing"]
    new = publish_dataset.v1_by_source(v1_doc(3))
    assert publish_dataset.guard(v1_doc(3, ulta=True), new, "sephora_me", ("ulta_ae",)) == [
        "HOLD, live v1 carries ulta_ae data (3 offers): not PI's to replace"
    ]


class _Blob:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.generation = 42

    def download_as_bytes(self, *, raw_download: bool = False) -> bytes:
        assert raw_download
        return self.data


class _Bucket:
    def __init__(self, stored: dict[str, bytes]) -> None:
        self.stored = stored

    def get_blob(self, name: str) -> _Blob | None:
        return _Blob(self.stored[name]) if name in self.stored else None


def test_read_live_handles_stored_gzip_plain_and_missing() -> None:
    doc = catalog(ulta_ae=1)
    bucket = _Bucket({"g": gzip.compress(json.dumps(doc).encode()), "p": json.dumps(doc).encode()})
    assert publish_dataset.read_live(bucket, "g") == (doc, 42)
    assert publish_dataset.read_live(bucket, "p") == (doc, 42)
    assert publish_dataset.read_live(bucket, "missing") == (None, 0)


# ------------------------------------------------------------------ the command
def run(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr("sys.argv", ["publish_dataset.py", *argv, "--project", "demo-pi"])
    return publish_dataset.main()


def test_dry_run_against_the_live_combined_file_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    new = tmp_path / "sephora.json"
    new.write_text(sephora_only(), encoding="utf-8")
    live = json.loads(sephora_only())
    live["products"] += catalog(ulta_ae=1)["products"]
    live_file = tmp_path / "live.json"
    live_file.write_text(json.dumps(live), encoding="utf-8")
    args = (str(new), "--allow-test", "--dry-run", "--live-file", str(live_file))
    assert run(monkeypatch, *args) == 1
    out = capsys.readouterr()
    assert "HOLD, live source ulta_ae (1 offers) is missing" in out.err
    assert "source guard: HOLD" in out.out
    with pytest.raises(SystemExit) as refused:
        run(monkeypatch, *args, "--drop-source", "ulta_ae")
    assert refused.value.code == 2
    assert "refusing: --drop-source ulta_ae: never dropped (owner hard rule)" in (
        capsys.readouterr().err
    )


def test_drop_source_ulta_is_refused_before_anything_is_read(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # not --dry-run and no such file: the refusal comes first, before the file or Firebase
    argv = ("missing.json", "--drop-source", "other_ae", "--drop-source", "ulta_ae")
    with pytest.raises(SystemExit) as refused:
        run(monkeypatch, *argv)
    assert refused.value.code == 2
    assert "refusing: --drop-source ulta_ae" in capsys.readouterr().err


def test_v1_dry_run_publishes_sephora_to_datasets_uae_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "v1.json"
    path.write_text(json.dumps(v1_doc(3)), encoding="utf-8")
    live = tmp_path / "live.json"
    live.write_text(json.dumps(v1_doc(3)), encoding="utf-8")
    assert run(monkeypatch, str(path), "--dry-run", "--live-file", str(live)) == 0
    out = capsys.readouterr().out
    assert '"storagePath": "datasets/uae/latest.json"' in out
    assert "source guard: ok" in out
    live.write_text(json.dumps(v1_doc(4)), encoding="utf-8")
    assert run(monkeypatch, str(path), "--dry-run", "--live-file", str(live)) == 1
    assert "HOLD, sephora_me drops from 4 to 3 offers" in capsys.readouterr().err


def test_v1_with_ulta_data_never_reaches_firebase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "v1.json"
    path.write_text(json.dumps(v1_doc(2, ulta=True)), encoding="utf-8")
    assert run(monkeypatch, str(path)) == 1  # not --dry-run: it must stop before Firebase
    assert "v1 publishes sephora_me data only" in capsys.readouterr().err


def test_a_ulta_file_never_reaches_firebase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "ulta.json"
    path.write_text(sephora_only().replace("sephora_me", "ulta_ae"), encoding="utf-8")
    assert run(monkeypatch, str(path), "--allow-test") == 1
    assert "ulta_ae is not a source PI publishes" in capsys.readouterr().err


# ------------------------------------------------------------------ v1 (the legacy root dashboard)
def v1_doc(n: int, *, ulta: bool = False) -> dict[str, Any]:
    """The live datasets/uae shape: ids s/u map to sources; a blocked Ulta has null offers."""
    offer = {"sku": "1", "series": {"price": [99]}}
    return {
        "schema": "pi.dataset/v1",
        "meta": {
            "kind": "snapshot",
            "cutoff": "2026-10-01T03:20:00Z",
            "generatedAt": "2026-10-01T04:05:13Z",
            "market": "AE",
            "currency": "AED",
            "dates": ["2026-10-01"],
            "retailers": [
                {"id": "u", "key": "ulta_ae", "name": "Ulta UAE", "status": "blocked"},
                {"id": "s", "key": "sephora_me", "name": "Sephora UAE", "status": "partial"},
            ],
        },
        "products": [
            {"id": f"p{i}", "offers": {"u": offer if ulta else None, "s": offer}} for i in range(n)
        ],
    }


def test_v1_offers_are_counted_by_source_and_null_placeholders_carry_no_data() -> None:
    assert publish_dataset.offer_counts(publish_dataset.v1_by_source(v1_doc(3))) == {
        "sephora_me": 3
    }
    assert publish_dataset.v1_source_errors(v1_doc(3)) == []
    assert publish_dataset.v1_source_errors(v1_doc(3, ulta=True)) == [
        "v1 publishes sephora_me data only: offers come from ['sephora_me', 'ulta_ae']"
    ]


def test_v1_writes_only_under_datasets_uae() -> None:
    _, paths, _ = publish_dataset.package(v1_doc(1), publish_dataset.V1_PREFIX)
    assert paths == ["datasets/uae/20261001T032000Z.json", "datasets/uae/latest.json"]
    assert publish_dataset.outside_prefixes(paths, v1=True) == []
    refused = [
        "datasets/ae/beauty/latest.json",
        "datasets/ae/sephora_me/latest.json",
        "datasets/uae/nested/latest.json",
        "datasets/uae/../ae/beauty/latest.json",
    ]
    assert publish_dataset.outside_prefixes(refused, v1=True) == refused
    assert publish_dataset.outside_prefixes(paths) == paths  # and v2 never writes there


def test_a_live_v1_with_another_sources_data_is_never_replaced() -> None:
    new = publish_dataset.v1_by_source(v1_doc(3))
    assert publish_dataset.guard(v1_doc(3), new, "sephora_me") == []
    assert publish_dataset.guard(v1_doc(3, ulta=True), new, "sephora_me") == [
        "HOLD, live v1 carries ulta_ae data (3 offers): not PI's to replace"
    ]
    assert publish_dataset.guard(v1_doc(4), new, "sephora_me") == [
        "HOLD, sephora_me drops from 4 to 3 offers"
    ]


# ------------------------------------------------------------------ latest.json precondition
class _PreconditionFailedError(Exception):
    code = publish_dataset.PRECONDITION_FAILED


class _GenBlob:
    def __init__(self, bucket: "_GenBucket", name: str) -> None:
        self.bucket, self.name = bucket, name

    def upload_from_string(
        self, body: bytes, *, content_type: str, if_generation_match: int | None = None
    ) -> None:
        current = self.bucket.generations.get(self.name, 0)
        if if_generation_match is not None and if_generation_match != current:
            raise _PreconditionFailedError(self.name)
        self.bucket.generations[self.name] = current + 1
        self.bucket.uploads.append(self.name)


class _GenBucket:
    name = "b"

    def __init__(self, generations: dict[str, int]) -> None:
        self.generations = generations
        self.uploads: list[str] = []

    def blob(self, name: str) -> _GenBlob:
        return _GenBlob(self, name)


@pytest.mark.parametrize(("read", "uploaded"), [(7, True), (6, False), (0, False)])
def test_latest_is_replaced_only_if_still_the_generation_the_guard_read(
    read: int, uploaded: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    bucket = _GenBucket({"datasets/uae/latest.json": 7})
    code = publish_dataset.upload(
        bucket, ["datasets/uae/latest.json"], b"x", latest_generation=read
    )
    assert (code == 0) is uploaded
    assert bucket.uploads == (["datasets/uae/latest.json"] if uploaded else [])
    if not uploaded:
        assert "changed since the source guard read it" in capsys.readouterr().err


def test_a_first_publish_requires_that_latest_still_does_not_exist() -> None:
    bucket = _GenBucket({})
    assert publish_dataset.upload(bucket, ["x/latest.json"], b"x", latest_generation=0) == 0
    assert publish_dataset.upload(bucket, ["x/latest.json"], b"x", latest_generation=0) == 1
