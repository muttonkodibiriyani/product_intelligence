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
from datetime import date
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


def as_beauty(doc: dict[str, Any]) -> dict[str, Any]:
    """An example document as the owner's combined file (north = sephora_me, south = ulta_ae)."""
    text = json.dumps(doc).replace("example_north_ae", "sephora_me")
    renamed: dict[str, Any] = json.loads(text.replace("example_south_ae", "ulta_ae"))
    return renamed


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


FRESH_END = "2026-10-08T10:00:00Z"
#: The new body's ulta_ae window: run-1 (and its segment run-1b) on 2026-10-08 in Dubai.
WINDOW = (frozenset({"run-1", "run-1b"}), date(2026, 10, 8), date(2026, 10, 8), "Asia/Dubai")


def removals_csv(
    tmp_path: Path,
    *rows: tuple[str, str, str],
    at: str = "2026-10-08T10:00:00Z",
    run: str = "run-1",
) -> Path:
    """removal_evidence.csv as the capture lane writes it: (retailer, product_id, evidence_type),
    each row's evidence from run ``run`` at ``at``."""
    header = "retailer,product_id,sku,url,last_captured_at,evidence_type,evidence_time,run_id"
    lines = [header] + [
        f"{retailer},{pid},S1,https://x/{pid},2026-10-01T00:00:00Z,{evidence},{at},{run}"
        for retailer, pid, evidence in rows
    ]
    file = tmp_path / "removal_evidence.csv"
    file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return file


@pytest.mark.parametrize("evidence", publish_dataset.REMOVAL_EVIDENCE)
def test_removal_evidence_is_read_from_the_capture_lane_csv(tmp_path: Path, evidence: str) -> None:
    file = removals_csv(tmp_path, ("ulta_ae", "p1", evidence), ("faces_ae", "p2", "blocked"))
    assert publish_dataset.read_removals(file, WINDOW) == (frozenset({"p1"}), [])  # others: ignored


def test_removal_evidence_must_come_from_the_new_window_run(tmp_path: Path) -> None:
    """Coordinator 01a11cd6-a407: the row's run_id is the window's runId or one of its segments;
    old evidence does not reconcile a removal in this roll."""
    segment = removals_csv(tmp_path, ("ulta_ae", "p1", "pdp-404"), run="run-1b")
    assert publish_dataset.read_removals(segment, WINDOW) == (frozenset({"p1"}), [])
    old = removals_csv(tmp_path, ("ulta_ae", "p1", "pdp-404"), run="run-0")
    assert publish_dataset.read_removals(old, WINDOW) == (
        frozenset(),
        [
            "removal_evidence.csv:2: run 'run-0' is not in the ulta_ae window (run-1, run-1b): "
            "p1 stays retained"
        ],
    )


def test_removal_evidence_time_is_on_a_window_day_in_the_market_zone(tmp_path: Path) -> None:
    # 2026-10-07T20:00Z is already 10-08 in Dubai, as the window guard counts days; a minute
    # earlier is 10-07, and so is no evidence from this window.
    on = removals_csv(tmp_path, ("ulta_ae", "p1", "pdp-410"), at="2026-10-07T20:00:00Z")
    assert publish_dataset.read_removals(on, WINDOW) == (frozenset({"p1"}), [])
    for at in ("2026-10-07T19:59:00Z", "2026-10-08T20:00:00Z", "yesterday"):
        off = removals_csv(tmp_path, ("ulta_ae", "p1", "pdp-410"), at=at)
        ids, [error] = publish_dataset.read_removals(off, WINDOW)
        assert ids == frozenset()
        assert error == (
            f"removal_evidence.csv:2: evidence_time {at!r} is not on a window day "
            "(2026-10-08..2026-10-08): p1 stays retained"
        )


def test_a_repeated_removal_key_refuses_the_file(tmp_path: Path) -> None:
    file = removals_csv(tmp_path, ("ulta_ae", "p1", "pdp-404"), ("ulta_ae", "p1", "sitemap-absent"))
    assert publish_dataset.read_removals(file, WINDOW)[1] == [
        "removal_evidence.csv:3: duplicate key ('ulta_ae', 'p1', 'S1')"
    ]


def test_with_no_ulta_window_no_removal_is_reconciled(tmp_path: Path) -> None:
    """Withheld ulta_ae (window null), or a v2 body: nothing in it is from this roll."""
    file = removals_csv(tmp_path, ("ulta_ae", "p1", "pdp-404"), ("faces_ae", "p2", "pdp-404"))
    assert publish_dataset.read_removals(file, None) == (
        frozenset(),
        [
            "removal_evidence.csv:2: the new body gives ulta_ae no crawl window, so no evidence "
            "is from this roll: p1 stays retained"
        ],
    )
    assert publish_dataset.removal_window(beauty_doc()) is None  # v2: no windows
    withheld = json.loads(
        gzip.decompress(windowed_body("2026-10-08T10:00:00Z", blocked="example_south_ae"))
    )
    assert publish_dataset.removal_window(as_beauty(withheld)) is None


def test_the_removal_window_is_read_from_the_new_body() -> None:
    doc = as_beauty(json.loads(gzip.decompress(windowed_body("2026-10-08T10:00:00Z"))))
    ulta = next(r for r in doc["meta"]["retailers"] if r["id"] == "ulta_ae")
    ulta["window"] |= {"start": "2026-10-06T21:00:00Z", "segments": ["run-x"]}
    assert publish_dataset.removal_window(doc) == (
        frozenset({"run-2026-10-08T10:00:00Z", "run-x"}),
        date(2026, 10, 7),
        date(2026, 10, 8),
        "Asia/Dubai",
    )


@pytest.mark.parametrize(
    "evidence",
    [
        "pdp-variant-absent",  # a variant of a KEPT offer: never excuses an absent offer
        "retained",
        "blocked",
        "rate_limited",
        "capture_in_progress",
        "planned_not_captured",
        "",
    ],
)
def test_anything_but_removal_evidence_refuses_the_file(tmp_path: Path, evidence: str) -> None:
    file = removals_csv(tmp_path, ("ulta_ae", "p0", "pdp-404"), ("ulta_ae", "p1", evidence))
    _, errors = publish_dataset.read_removals(file, WINDOW)
    assert len(errors) == 1
    assert errors[0].startswith("removal_evidence.csv:3: ")


def test_a_removals_file_without_the_columns_is_refused(tmp_path: Path) -> None:
    file = tmp_path / "ids.json"
    file.write_text('["p1"]', encoding="utf-8")
    assert publish_dataset.read_removals(file, WINDOW)[1][0].startswith("ids.json: missing columns")


def test_an_absent_offer_listed_with_pdp_variant_absent_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = beauty_doc()
    pid = doc["products"][0]["id"]
    drop_ulta_offer(doc)
    new = tmp_path / "new.json"
    new.write_text(json.dumps(doc), encoding="utf-8")
    live = tmp_path / "live.json"
    live.write_text(beauty_raw(), encoding="utf-8")
    argv = [str(new), "--project", "p", "--allow-test", "--dry-run", "--versioned"]
    argv += ["--live-datasets", LIVE, "--allow-beauty-versioned", "--live-file", str(live)]
    variant = removals_csv(tmp_path, ("ulta_ae", pid, "pdp-variant-absent"))
    assert run([*argv, "--reconciled-removals", str(variant)], monkeypatch) == 1
    assert "'pdp-variant-absent' is not removal evidence" in capsys.readouterr().err
    gone = removals_csv(tmp_path, ("ulta_ae", pid, "pdp-404"), run=f"run-{FRESH_END}")
    # A v2 body gives ulta_ae no window, so no evidence is from this roll: the offer holds.
    assert run([*argv, "--reconciled-removals", str(gone)], monkeypatch) == 1
    assert "the new body gives ulta_ae no crawl window" in capsys.readouterr().err
    # The same evidence beside a v3 body whose ulta_ae window is that run reconciles it.
    fresh = as_beauty(json.loads(gzip.decompress(windowed_body(FRESH_END))))
    drop_ulta_offer(fresh)
    new.write_text(json.dumps(fresh), encoding="utf-8")
    assert run([*argv, "--reconciled-removals", str(gone)], monkeypatch) == 0
    assert "retention ulta_ae: live 2 new 1 reconciled 1" in capsys.readouterr().out


def test_a_beauty_publish_holds_a_lost_sephora_offer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review of #304 item 2: the beauty file's sephora_me offers get the source guard too."""
    doc = beauty_doc()
    del doc["products"][0]["offers"]["sephora_me"]
    doc["products"][0]["matches"] = []
    new = tmp_path / "new.json"
    new.write_text(json.dumps(doc), encoding="utf-8")
    bucket = Bucket()
    stored(bucket, LIVE_BEAUTY, beauty_doc())
    fake_firebase(monkeypatch, bucket)
    argv = [str(new), "--project", "p", "--allow-test", "--versioned", "--live-datasets", LIVE]
    assert run([*argv, "--allow-beauty-versioned"], monkeypatch) == 1
    assert bucket.uploads == []
    assert "HOLD, sephora_me drops from 3 to 2 offers" in capsys.readouterr().err
    # sephora_me served from its own body: the guard reads that body. With 2 offers live
    # there, the same new file passes.
    split = LIVE.replace("sephora_me=datasets/ae/beauty/latest.json", "sephora_me=s/v/1.json")
    smaller = json.loads(sephora_only())
    del smaller["products"][0]["offers"]["sephora_me"]
    stored(bucket, "s/v/1.json", smaller)
    assert run([*argv[:-1], split, "--allow-beauty-versioned"], monkeypatch) == 0
    assert "source guard: ok" in capsys.readouterr().out


def test_a_beauty_publish_refuses_without_a_sephora_body_to_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review 5461045335 item 2: the sephora_me guard is never skipped. (a) The live value
    points sephora_me at a body that is not there; (b) the live value has no sephora_me."""
    new = tmp_path / "new.json"
    new.write_text(beauty_raw(), encoding="utf-8")
    bucket = Bucket()
    stored(bucket, LIVE_BEAUTY, beauty_doc())
    fake_firebase(monkeypatch, bucket)
    argv = [str(new), "--project", "p", "--allow-test", "--versioned", "--allow-beauty-versioned"]
    missing = LIVE.replace("sephora_me=datasets/ae/beauty/latest.json", "sephora_me=s/v/none.json")
    assert run([*argv, "--live-datasets", missing], monkeypatch) == 1
    assert "refusing: no live sephora_me body at s/v/none.json" in capsys.readouterr().err
    absent = LIVE.replace("sephora_me=datasets/ae/beauty/latest.json,", "")
    assert run([*argv, "--live-datasets", absent], monkeypatch) == 1
    assert "refusing: the live PI_API_DATASETS serves no sephora_me" in capsys.readouterr().err
    assert bucket.uploads == []
    # The same file with sephora_me served passes, so the refusals are the guard's.
    assert run([*argv, "--live-datasets", LIVE], monkeypatch) == 0


def test_retention_fresh_allows_only_reconciled_removals() -> None:
    live = beauty_doc()
    fresh = copy.deepcopy(live)
    pid = fresh["products"][0]["id"]
    drop_ulta_offer(fresh)
    assert publish_dataset.retention_problems(live, fresh, frozenset({pid})) == []
    other = frozenset({live["products"][1]["id"]})
    assert publish_dataset.retention_problems(live, fresh, other)


# ------------------------------------------------------------------ check-served: the windows
def windowed_body(end: str | None, *, blocked: str | None = None) -> bytes:
    """The ae-pilot example as v3 with each retailer's own keys and a window ending at ``end``;
    ``blocked``: that retailer has no window and is disclosed not observed (withheld)."""
    from pi_dataset import committed_profile, dump_dataset, upgrade  # noqa: PLC0415
    from pi_dataset.examples import ae_pilot  # noqa: PLC0415

    profile = committed_profile("beauty", 1)
    assert profile is not None
    d: dict[str, Any] = json.loads(dump_dataset(upgrade(ae_pilot(), profile)))
    meta = d["meta"]
    meta["cutoff"] = meta["generatedAt"] = "2026-10-08T19:59:00Z"  # 10-08 in Dubai
    for r in meta["retailers"]:
        r["fields"], r["capabilities"] = dict(meta["fields"]), dict(meta["capabilities"])
        if end is not None and r["id"] != blocked:
            r["window"] = {"start": end, "end": end, "runId": f"run-{end}"}
            for offer in (p["offers"].get(r["id"]) for p in d["products"]):
                if offer is not None and not offer["early"]:  # #302 rule (c); recon stays
                    offer["evidence"] |= {"capturedAt": end, "runId": f"run-{end}"}
        if r["id"] == blocked:
            r["since"] = "2026-10-01"  # its last capture: the entry runs from the day after
    if blocked is not None:
        why = {"en": "Blocked (p0-20261008-ulta-probe).", "ar": "محجوب."}
        d["notObserved"] = [
            {"retailer": blocked, "context": None, "categories": None, "why": why}
            | {"start": "2026-10-02", "end": "2026-10-08"}
        ]
    return gzip.compress(json.dumps(d).encode(), mtime=0)


def check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **bodies: bytes) -> int:
    for name, body in bodies.items():
        (tmp_path / "d" / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "d" / name).write_bytes(body)
    value = ",".join(f"s{i}=d/{name}" for i, name in enumerate(bodies))
    argv = ["--project", "p", "--allow-test", "--check-served", value]
    return run([*argv, "--served-root", str(tmp_path)], monkeypatch)


def test_check_served_passes_seven_dubai_days_and_holds_eight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fresh = windowed_body("2026-10-08T10:00:00Z")
    seven = windowed_body("2026-09-30T20:00:00Z")  # 10-01 in Dubai
    assert check(tmp_path, monkeypatch, a=fresh, b=seven) == 0
    assert "window guard: 2 bodies, ok" in capsys.readouterr().out
    eight = windowed_body("2026-09-30T19:59:00Z")  # 09-30 in Dubai
    assert check(tmp_path, monkeypatch, a=fresh, b=eight) == 1
    captured = capsys.readouterr()
    assert "HOLD, window gap 8 days in Asia/Dubai, more than 7" in captured.err
    assert "window guard: 2 bodies, HOLD" in captured.out


def test_check_served_holds_no_window_and_a_missing_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fresh = windowed_body("2026-10-08T10:00:00Z")
    assert check(tmp_path, monkeypatch, a=fresh, b=windowed_body(None)) == 1
    err = capsys.readouterr().err
    assert "d/b: example_north_ae: withheld (no window) with offers but no whole-retailer" in err
    assert "it has no crawl window (ADR-0013)" in err
    argv = ["--project", "p", "--allow-test", "--check-served", "s=d/a,t=d/none"]
    assert run([*argv, "--served-root", str(tmp_path)], monkeypatch) == 1
    assert "HOLD, d/none: not found" in capsys.readouterr().err
    # One body serving two sources is read once.
    argv = ["--project", "p", "--allow-test", "--check-served", "s=d/a,t=d/a"]
    assert run([*argv, "--served-root", str(tmp_path)], monkeypatch) == 0
    assert "window guard: 1 bodies, ok" in capsys.readouterr().out


def test_check_served_lists_a_withheld_retailer_and_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Coordinator 01a11cc0-86a1: ulta_ae withheld as blocked is not a refusal; it is printed."""
    fresh = windowed_body("2026-10-08T10:00:00Z", blocked="example_south_ae")
    assert check(tmp_path, monkeypatch, a=fresh) == 0
    out = capsys.readouterr().out
    assert "d/a: example_south_ae withheld, not observed until 2026-10-08: Blocked" in out
    assert "window guard: 1 bodies, ok" in out


def test_check_served_holds_a_set_with_no_window_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review 5461198455: a pre-ADR-0013 body whose every retailer is disclosed not observed
    (here until 09-02) has nothing fresh to withhold beside, so it is refused."""
    d = json.loads(gzip.decompress(windowed_body(None, blocked="example_south_ae")))
    entry = d["notObserved"][0] | {"start": "2026-09-01", "end": "2026-09-02"}
    d["notObserved"] = [entry, entry | {"retailer": "example_north_ae"}]
    old = gzip.compress(json.dumps(d).encode(), mtime=0)
    assert check(tmp_path, monkeypatch, a=old) == 1
    captured = capsys.readouterr()
    assert "HOLD, no retailer in the served set has a crawl window" in captured.err
    assert "withheld" not in captured.out
