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
    live = catalog(sephora_me=9529, ulta_ae=7275)
    assert (
        publish_dataset.source_guard(live, catalog(sephora_me=9529), "sephora_me", ("ulta_ae",))
        == []
    )
    held = publish_dataset.source_guard(live, catalog(sephora_me=9000), "sephora_me", ("ulta_ae",))
    assert held == ["HOLD, sephora_me drops from 9529 to 9000 offers"]


class _Blob:
    def __init__(self, data: bytes) -> None:
        self.data = data

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
    assert publish_dataset.read_live(bucket, "g") == doc
    assert publish_dataset.read_live(bucket, "p") == doc
    assert publish_dataset.read_live(bucket, "missing") is None


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
    assert run(monkeypatch, *args, "--drop-source", "ulta_ae") == 0
    assert "owner approval required" in capsys.readouterr().err


def test_v1_is_no_longer_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "v1.json"
    v1 = {
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
    path.write_text(json.dumps(v1), encoding="utf-8")
    assert run(monkeypatch, str(path)) == 1  # not --dry-run: it must stop before Firebase
    assert "v1 is no longer published" in capsys.readouterr().err


def test_a_ulta_file_never_reaches_firebase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "ulta.json"
    path.write_text(sephora_only().replace("sephora_me", "ulta_ae"), encoding="utf-8")
    assert run(monkeypatch, str(path), "--allow-test") == 1
    assert "ulta_ae is not a source PI publishes" in capsys.readouterr().err
