"""publish_dataset --versioned (deploy plan v2) and --allow-beauty-versioned (owner P1 only).

A versioned publish writes one new create-only object and nothing the live revision reads;
beauty adds the Ulta retention guard (keys-only: exact; fresh: reconciled removals only).
"""

import copy
import gzip
import hashlib
import json
import sys
import types
from pathlib import Path
from typing import Any

import publish_dataset
import pytest
from test_publish_dataset import Blob
from test_publish_dataset import Bucket as _Bucket
from test_publish_source_guard import EXAMPLE, sephora_only

LIVE = (
    "sephora_me=datasets/ae/beauty/latest.json,ulta_ae=datasets/ae/beauty/latest.json,"
    "faces_ae=datasets/ae/faces_ae/latest.json"
)
LIVE_BEAUTY = "datasets/ae/beauty/latest.json"


class Bucket(_Bucket):
    """The fake bucket, with the generation read_live records for the live object."""

    def get_blob(self, name: str) -> Blob | None:
        blob = super().get_blob(name)
        if blob is not None:
            blob.generation = 7  # type: ignore[attr-defined]
        return blob


def drop_ulta_offer(doc: dict[str, Any], index: int = 0) -> None:
    """Product ``index`` stays, as Sephora-only: its ulta_ae offer and match edge go."""
    product = doc["products"][index]
    del product["offers"]["ulta_ae"]
    product["matches"] = []


def beauty_raw() -> str:
    """The ae-pilot example as the owner's combined file: north = sephora_me, south = ulta_ae."""
    raw = EXAMPLE.read_text(encoding="utf-8")
    return raw.replace("example_north_ae", "sephora_me").replace("example_south_ae", "ulta_ae")


def beauty_doc() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(beauty_raw())
    return doc


def run(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(sys, "argv", ["publish_dataset.py", *argv])
    return publish_dataset.main()


def fake_firebase(monkeypatch: pytest.MonkeyPatch, bucket: Bucket) -> list[str]:
    """firebase_admin whose storage is ``bucket``; returns the Firestore docs written."""
    written: list[str] = []
    storage = types.SimpleNamespace(bucket=lambda: bucket)
    doc = types.SimpleNamespace(set=lambda summary: written.append(summary["storagePath"]))
    collection = types.SimpleNamespace(document=lambda name: doc)
    firestore = types.SimpleNamespace(
        client=lambda: types.SimpleNamespace(collection=lambda name: collection)
    )
    admin = types.ModuleType("firebase_admin")
    admin.initialize_app = lambda **_: None  # type: ignore[attr-defined]
    admin.storage = storage  # type: ignore[attr-defined]
    admin.firestore = firestore  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "firebase_admin", admin)
    return written


def stored(bucket: Bucket, path: str, doc: dict[str, Any]) -> None:
    bucket.stored[path] = gzip.compress(json.dumps(doc).encode(), mtime=0)


# ------------------------------------------------------------------ paths and DATASETS
def test_a_versioned_path_is_new_per_body_and_never_latest() -> None:
    dataset, _ = publish_dataset.validate_v2(sephora_only(), allow_test=True)
    body, paths, _, _ = publish_dataset.package_v2(dataset)
    target = publish_dataset.versioned_path(paths, body)
    sha = hashlib.sha256(gzip.decompress(body)).hexdigest()
    assert target == f"datasets/ae/sephora_me/v/20260930T000000Z-{sha[:12]}.json"
    assert not publish_dataset.versioned_outside(target)
    assert publish_dataset.versioned_outside("datasets/ae/sephora_me/latest.json")
    assert publish_dataset.versioned_outside("datasets/ae/beauty/v/x.json")
    assert not publish_dataset.versioned_outside("datasets/ae/beauty/v/x.json", beauty=True)


def test_repoint_moves_only_the_published_sources() -> None:
    new, errors = publish_dataset.repoint(LIVE, ["faces_ae"], "datasets/ae/faces_ae/v/a.json")
    assert errors == []
    assert new == LIVE.replace("faces_ae/latest.json", "faces_ae/v/a.json")
    added, _ = publish_dataset.repoint(LIVE, ["bloomingdales_ae"], "d/v/b.json")
    assert added == f"{LIVE},bloomingdales_ae=d/v/b.json"
    beauty, _ = publish_dataset.repoint(LIVE, ["sephora_me", "ulta_ae"], "d/beauty/v/c.json")
    assert beauty.split(",")[:2] == ["sephora_me=d/beauty/v/c.json", "ulta_ae=d/beauty/v/c.json"]


def test_repoint_refuses_a_live_path_and_bare_entries() -> None:
    _, errors = publish_dataset.repoint(LIVE, ["faces_ae"], LIVE_BEAUTY)
    assert any("already in the live PI_API_DATASETS" in e for e in errors)
    _, errors = publish_dataset.repoint(LIVE_BEAUTY, ["faces_ae"], "d/v/a.json")
    assert any("bare entries" in e for e in errors)


def test_the_refused_body_is_refused_raw_and_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert "b98194beba185c2f4cfaf211cb055a8ef0b58372bc827e3910011b6dcc673382" in (
        publish_dataset.REFUSED_BODIES
    )
    new = tmp_path / "new.json"
    new.write_text(sephora_only(), encoding="utf-8")
    dataset, _ = publish_dataset.validate_v2(sephora_only(), allow_test=True)
    canonical = gzip.decompress(publish_dataset.package_v2(dataset)[0])
    argv = [str(new), "--project", "p", "--dry-run", "--allow-test"]
    for body in (new.read_bytes(), canonical):
        refused = {hashlib.sha256(body).hexdigest(): "test refusal"}
        monkeypatch.setattr(publish_dataset, "REFUSED_BODIES", refused)
        assert run(argv, monkeypatch) == 1
        assert "refusing: test refusal" in capsys.readouterr().err


# ------------------------------------------------------------------ main --versioned
def test_versioned_needs_the_live_datasets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    new = tmp_path / "new.json"
    new.write_text(sephora_only(), encoding="utf-8")
    with pytest.raises(SystemExit):
        run([str(new), "--project", "p", "--allow-test", "--versioned"], monkeypatch)


def test_a_versioned_publish_writes_one_new_object_and_nothing_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    new = tmp_path / "new.json"
    new.write_text(sephora_only().replace("sephora_me", "faces_ae"), encoding="utf-8")
    bucket = Bucket()
    written = fake_firebase(monkeypatch, bucket)
    argv = [str(new), "--project", "p", "--allow-test", "--versioned", "--live-datasets", LIVE]
    assert run(argv, monkeypatch) == 0
    [target] = bucket.uploads
    assert target.startswith("datasets/ae/faces_ae/v/")
    assert written == []  # no Firestore mirror: the live demo meta is untouched
    out = capsys.readouterr().out
    assert f"uploaded gs://b/{target}" in out
    assert out.strip().endswith(LIVE.replace("datasets/ae/faces_ae/latest.json", target))
    # The same body again: create-only, unchanged; nothing else is written.
    assert run(argv, monkeypatch) == 0
    assert bucket.uploads == [target]


def test_the_default_mode_is_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    new = tmp_path / "new.json"
    new.write_text(sephora_only().replace("sephora_me", "faces_ae"), encoding="utf-8")
    bucket = Bucket()
    written = fake_firebase(monkeypatch, bucket)
    assert run([str(new), "--project", "p", "--allow-test"], monkeypatch) == 0
    assert bucket.uploads == [
        "datasets/ae/faces_ae/20260930T000000Z.json",
        "datasets/ae/faces_ae/latest.json",
    ]
    assert written == ["datasets/ae/faces_ae/latest.json"]


# ------------------------------------------------------------------ beauty (owner P1 only)
def test_the_beauty_file_needs_the_flag_and_the_flag_needs_versioned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    new = tmp_path / "new.json"
    new.write_text(beauty_raw(), encoding="utf-8")
    base = [str(new), "--project", "p", "--allow-test", "--dry-run"]
    assert run([*base, "--versioned", "--live-datasets", LIVE], monkeypatch) == 1
    assert "one source per file" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        run([*base, "--allow-beauty-versioned"], monkeypatch)


def test_the_beauty_flag_accepts_exactly_sephora_and_ulta() -> None:
    assert publish_dataset.beauty_errors(publish_dataset.by_source(beauty_doc())) == []
    faces = json.loads(beauty_raw().replace("sephora_me", "faces_ae"))
    assert publish_dataset.beauty_errors(publish_dataset.by_source(faces))
    assert publish_dataset.beauty_errors(publish_dataset.by_source(json.loads(sephora_only())))


def test_a_beauty_publish_writes_only_a_new_beauty_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    new = tmp_path / "new.json"
    new.write_text(beauty_raw(), encoding="utf-8")
    bucket = Bucket()
    stored(bucket, LIVE_BEAUTY, beauty_doc())
    before = dict(bucket.stored)
    written = fake_firebase(monkeypatch, bucket)
    argv = [str(new), "--project", "p", "--allow-test", "--versioned", "--live-datasets", LIVE]
    assert run([*argv, "--allow-beauty-versioned"], monkeypatch) == 0
    [target] = bucket.uploads
    assert target.startswith("datasets/ae/beauty/v/")
    assert {k: v for k, v in bucket.stored.items() if k != target} == before
    assert written == []
    out = capsys.readouterr().out
    assert "retention ulta_ae: live 2 new 2 reconciled 0" in out
    assert out.strip().endswith(
        f"sephora_me={target},ulta_ae={target},faces_ae=datasets/ae/faces_ae/latest.json"
    )


def test_a_beauty_publish_with_a_dropped_ulta_offer_uploads_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = beauty_doc()
    drop_ulta_offer(doc)
    new = tmp_path / "new.json"
    new.write_text(json.dumps(doc), encoding="utf-8")
    bucket = Bucket()
    stored(bucket, LIVE_BEAUTY, beauty_doc())
    fake_firebase(monkeypatch, bucket)
    argv = [str(new), "--project", "p", "--allow-test", "--versioned", "--live-datasets", LIVE]
    assert run([*argv, "--allow-beauty-versioned"], monkeypatch) == 1
    assert bucket.uploads == []
    assert "1 live ulta_ae offers missing" in capsys.readouterr().err


# ------------------------------------------------------------------ the retention guard
def test_retention_keys_only_is_exact() -> None:
    live = beauty_doc()
    assert publish_dataset.retention_problems(live, copy.deepcopy(live)) == []
    assert publish_dataset.retention_problems(None, live)  # nothing to check against: HOLD
    kept = copy.deepcopy(live)
    drop_ulta_offer(kept)
    problems = publish_dataset.retention_problems(live, kept)
    assert any("1 live ulta_ae offers missing" in p for p in problems)
    assert any("(sku, url) missing" in p for p in problems)
    remint = copy.deepcopy(live)
    remint["products"][0]["id"] += "-new"  # same offer under a re-minted product id
    assert any("offers missing" in p for p in publish_dataset.retention_problems(live, remint))
    resku = copy.deepcopy(live)
    resku["products"][0]["offers"]["ulta_ae"]["sku"] = "OTHER"
    assert publish_dataset.retention_problems(live, resku) == [
        "HOLD, 1 live ulta_ae (sku, url) missing: "
        f"{[(live['products'][0]['offers']['ulta_ae']['sku'], None)]}"
    ]


def test_retention_fresh_allows_only_reconciled_removals() -> None:
    live = beauty_doc()
    fresh = copy.deepcopy(live)
    pid = fresh["products"][0]["id"]
    drop_ulta_offer(fresh)
    assert publish_dataset.retention_problems(live, fresh, frozenset({pid})) == []
    other = frozenset({live["products"][1]["id"]})
    assert publish_dataset.retention_problems(live, fresh, other)
