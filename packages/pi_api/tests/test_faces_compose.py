"""Faces UAE served beside the combined Ulta/Sephora beauty file (API 1.15.0).

The owner-approved value is three ``source=path`` entries: the beauty file assigned to the two
retailers it holds, and the Faces-only export to ``faces_ae``. The earlier value (the beauty file
bare, Faces assigned) passes config validation but serves two AE/beauty views, so every data route
would refuse as ambiguous; that is pinned here. The golden half checks the Ulta/Sephora answers of
the composed view equal the whole-file view, so the only change is Faces itself.

``PI_FACES_BEAUTY`` / ``PI_FACES_FILE`` point the golden at real local files (the published beauty
file and the Faces export); unset, it runs on the fixture alone.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from api_fixture import Client, bearer, make_client, own_keys, served_dataset
from metrics_fixture import rebuild
from pi_api.config import Settings, dataset_entries
from pi_api.source import AmbiguousDatasetError
from pi_dataset import DatasetV3, dump_dataset, load_any
from sources_fixture import snapshot_doc

BEAUTY = "datasets/ae/beauty/latest.json"
FACES_PATH = "datasets/ae/faces_ae/latest.json"
FACES, ULTA, SEPHORA = "faces_ae", "ulta_ae", "sephora_me"
OLD = f"{BEAUTY},{FACES}={FACES_PATH}"
NEW = f"{SEPHORA}={BEAUTY},{ULTA}={BEAUTY},{FACES}={FACES_PATH}"
LOCAL = {"PI_API_LOCAL_DIR": "/srv/pi", "PI_API_FIREBASE_PROJECT": "pi-test-project"}
REGULAR = {"amount": "120.00", "minor": 12000, "currency": "AED"}

# Ulta/Sephora-only questions: these must be byte-for-byte the whole-file answer.
SCOPED = (
    f"/api/v1/compare?retailers={ULTA},{SEPHORA}",
    f"/api/v1/index?retailers={ULTA},{SEPHORA}",
    f"/api/v1/promotions?retailer={ULTA}",
    f"/api/v1/promotions?retailer={SEPHORA}",
    f"/api/v1/price-suggestions?subject={SEPHORA}&rival={ULTA}",
    f"/api/v1/price-suggestions?subject={ULTA}&rival={SEPHORA}",
    f"/api/v1/launches?retailer={ULTA}",
    f"/api/v1/launches?retailer={SEPHORA}",
    f"/api/v1/coverage?retailer={ULTA}",
    f"/api/v1/coverage?retailer={SEPHORA}",
)
# Market-wide questions: equal once Faces' own rows and caveats are taken out.
WIDE = ("/api/v1/promotions", "/api/v1/launches", "/api/v1/coverage", "/api/v1/meta")
# Market-wide totals Faces legitimately adds to (its items are counted, never shown as launches),
# and the per-source list only a composed view states (each source's own cutoff and dates).
FACES_TOTALS = {
    "/api/v1/promotions": {"$.cohort.n", "$.data.total"},
    "/api/v1/launches": {"$.caveats[0].params.count", "$.caveats[0].en", "$.caveats[0].ar"},
    "/api/v1/meta": {"$.data.categories", "$.data.sources"},
}


def beauty_doc() -> bytes:
    """The pi_metrics fixture as an AE/beauty file whose first two shops are Sephora and Ulta."""
    raw = dump_dataset(own_keys(rebuild(served_dataset(), scope="beauty")))
    # Renames keep the edge order a < b: sephora_me < ulta_ae < vshop_c < wshop_d.
    for old, new in (("shop_a", SEPHORA), ("shop_b", ULTA), ("shop_c", "vshop_c")):
        raw = raw.replace(old.encode(), new.encode())
    return raw.replace(b"shop_d", b"wshop_d")


def faces_file(dates: list[str]) -> DatasetV3:
    """A Faces-only export: partial, no stock, one stated was-price."""
    d = snapshot_doc({"faces-1": (FACES,), "faces-2": (FACES,)}, dates=dates, windows=False)
    # no window: beside the window-less beauty fixture a windowed shop would leave the beauty
    # shops withheld without their notObserved entries (ADR-0013 §8), and the view refused
    d["meta"]["retailers"][0]["status"] = "partial"
    d["products"][0]["offers"][FACES]["series"]["regular"] = [REGULAR] * len(dates)
    return DatasetV3.model_validate(d)


def install(root: Path, beauty: bytes, faces: bytes) -> list[str]:
    for path, body in ((BEAUTY, beauty), (FACES_PATH, faces)):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    return [r.id for r in load_any(beauty).meta.retailers]


def clients(root: Path, retailers: list[str]) -> tuple[Client, Client]:
    whole, _ = make_client(root, paths=(BEAUTY,))
    assigned = dict.fromkeys(retailers, BEAUTY) | {FACES: FACES_PATH}
    composed, _ = make_client(root, paths=(), assigned=assigned)
    return whole, composed


def answer(client: Client, route: str) -> Any:
    response = client.get(route, headers=bearer())
    assert response.status_code == 200, (route, response.text[:300])
    return response.json()


def generationless(value: Any) -> Any:
    """Drop the generation token: it hashes the files served, so it differs by design."""
    if isinstance(value, dict):
        return {k: generationless(v) for k, v in value.items() if k != "generation"}
    if isinstance(value, list):
        return [generationless(v) for v in value]
    return value


def is_faces(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    params = value.get("params")
    named = (value.get("retailer"), value.get("id"))
    return FACES in named or (isinstance(params, dict) and params.get("retailer") == FACES)


def without_faces(value: Any) -> Any:
    """Faces' own rows, retailer entries and caveats removed, recursively."""
    if isinstance(value, dict):
        return {k: without_faces(v) for k, v in value.items() if k != FACES}
    if isinstance(value, list):
        return [without_faces(v) for v in value if not is_faces(v)]
    return value


def differences(a: Any, b: Any, path: str = "$") -> Iterator[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            yield from differences(a.get(key), b.get(key), f"{path}.{key}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for n, (x, y) in enumerate(zip(a, b, strict=True)):
            yield from differences(x, y, f"{path}[{n}]")
    elif a != b:
        yield path


def faces_items(body: Any) -> list[Mapping[str, Any]]:
    return [i for i in body["data"]["items"] if i.get("retailer") == FACES]


# ---------------------------------------------------------------- condition 1: the env value


def test_the_withdrawn_value_passes_config_but_every_route_is_ambiguous(tmp_path: Path) -> None:
    paths, assigned = dataset_entries(OLD)
    assert (paths, assigned) == ((BEAUTY,), {FACES: FACES_PATH})
    Settings.from_env({**LOCAL, "PI_API_DATASETS": OLD})  # only refuses a path served both ways
    retailers = install(tmp_path, beauty_doc(), dump_dataset(faces_file(["2026-09-30"])))
    assert retailers[:2] == [SEPHORA, ULTA]
    client, source = make_client(tmp_path, paths=paths, assigned=assigned)
    with pytest.raises(AmbiguousDatasetError):
        source.select("AE", "beauty")
    with pytest.raises(AmbiguousDatasetError):
        source.select(None, None)
    response = client.get(f"/api/v1/compare?retailers={ULTA},{SEPHORA}", headers=bearer())
    assert response.status_code != 200


def test_the_approved_value_composes_one_ae_beauty_view_with_faces(tmp_path: Path) -> None:
    paths, assigned = dataset_entries(NEW)
    assert paths == ()
    assert assigned == {SEPHORA: BEAUTY, ULTA: BEAUTY, FACES: FACES_PATH}
    Settings.from_env({**LOCAL, "PI_API_DATASETS": NEW})
    install(tmp_path, beauty_doc(), dump_dataset(faces_file(["2026-09-29", "2026-09-30"])))
    client, source = make_client(tmp_path, paths=paths, assigned=assigned)
    (view,) = source.datasets()
    dataset = source.select("AE", "beauty").dataset
    assert source.select(None, None).dataset is dataset
    assert [r.id for r in dataset.meta.retailers] == [FACES, SEPHORA, ULTA]
    assert set(view.path.split(",")) == {f"{s}={p}" for s, p in assigned.items()}
    faces_only = [p for p in dataset.products if set(p.offers) == {FACES}]
    assert [p.id for p in faces_only] == ["faces-1", "faces-2"]
    assert all(not p.matches for p in faces_only)  # no cross-file pairs (later ADR)
    coverage = answer(client, f"/api/v1/coverage?retailer={FACES}")["data"]["retailers"]
    assert [(r["id"], r["status"], r["productCount"]) for r in coverage] == [(FACES, "partial", 2)]


# ---------------------------------------------------------------- condition 2: golden u-s answers


def golden(beauty: bytes, faces: bytes, root: Path) -> dict[str, list[str]]:
    """Every u-s route under the composed view vs the whole beauty file; differing JSON paths."""
    whole, composed = clients(root, install(root, beauty, faces))
    found: dict[str, list[str]] = {}
    for route in SCOPED:
        a, b = (generationless(answer(c, route)) for c in (whole, composed))
        found[route] = list(differences(a, b))
    for route in WIDE:
        a, b = (without_faces(generationless(answer(c, route))) for c in (whole, composed))
        added = FACES_TOTALS.get(route, set())
        found[route] = [p for p in differences(a, b) if not any(p.startswith(x) for x in added)]
    return {route: paths for route, paths in found.items() if paths}


def test_ulta_sephora_answers_are_unchanged_when_faces_shares_the_cutoff(tmp_path: Path) -> None:
    beauty = beauty_doc()
    dates = [str(d) for d in load_any(beauty).meta.dates]
    assert golden(beauty, dump_dataset(faces_file(dates[-2:])), tmp_path) == {}


def test_faces_promotions_are_listed_and_its_share_withheld_ulta_was_price_still_served(
    tmp_path: Path,
) -> None:
    beauty = beauty_doc()
    dates = [str(d) for d in load_any(beauty).meta.dates]
    whole, composed = clients(tmp_path, install(tmp_path, beauty, dump_dataset(faces_file(dates))))
    body = answer(composed, "/api/v1/promotions")
    assert [(i["id"], i["regular"]) for i in faces_items(body)] == [("faces-1", REGULAR)]
    shares = {r["retailer"]: r for r in body["data"]["retailers"]}
    assert (shares[FACES]["share"], shares[FACES]["reason"]) == (None, "retailer_partial")
    stated = {(c["code"], c["params"].get("retailer")) for c in body["caveats"]}
    assert ("was_price_stated", ULTA) in stated
    assert (
        answer(whole, f"/api/v1/promotions?retailer={ULTA}")["data"]
        == (answer(composed, f"/api/v1/promotions?retailer={ULTA}")["data"])
    )


def test_faces_items_are_never_launches(tmp_path: Path) -> None:
    beauty = beauty_doc()
    dates = [str(d) for d in load_any(beauty).meta.dates]
    _, composed = clients(tmp_path, install(tmp_path, beauty, dump_dataset(faces_file(dates[1:]))))
    assert answer(composed, f"/api/v1/launches?retailer={FACES}")["data"]["items"] == []


def test_a_faces_file_dated_after_the_beauty_file_moves_the_cutoff_and_ages_ulta_sephora(
    tmp_path: Path,
) -> None:
    """The carry-forward case the PR lists: Faces exported a day after the beauty file.

    The composed cutoff becomes the Faces day, so Ulta/Sephora answer from their last day with
    staleness caveats rather than unchanged. The publish order (beauty untouched, Faces exported
    from the same pi_db day) keeps the two cutoffs equal; this pins what happens if they drift.
    """
    beauty = beauty_doc()
    last = str(load_any(beauty).meta.dates[-1])
    faces = dump_dataset(faces_file([last, "2026-10-01"]))
    whole, composed = clients(tmp_path, install(tmp_path, beauty, faces))
    route = f"/api/v1/compare?retailers={ULTA},{SEPHORA}"
    before, after = answer(whole, route), answer(composed, route)
    assert before["meta"]["cutoff"] == f"{last}T00:00:00Z"
    assert after["meta"]["cutoff"] == "2026-10-01T00:00:00Z"
    stale = [c for c in after["caveats"] if c["code"] == "stale_source"]
    assert [(c["params"]["retailer"], c["params"]["asOf"]) for c in stale] == [
        (SEPHORA, last),
        (ULTA, last),
    ]
    # The imported-data caveats (Ulta's import date, stated was-prices, parents) carry over as is.
    assert [c for c in after["caveats"] if c["code"] != "stale_source"] == before["caveats"]
    assert before["data"] == after["data"]
    index = answer(composed, f"/api/v1/index?retailers={ULTA},{SEPHORA}")["data"]["points"]
    assert (
        index[:-1] == answer(whole, f"/api/v1/index?retailers={ULTA},{SEPHORA}")["data"]["points"]
    )
    assert index[-1] == {"date": "2026-10-01", "index": None, "n": 0, "reason": "cohort_too_small"}
    rows = answer(composed, f"/api/v1/price-suggestions?subject={SEPHORA}&rival={ULTA}")
    assert {r["subject"]["ageDays"] for r in rows["data"]["rows"]} == {1}


@pytest.mark.parametrize(
    "route",
    [
        f"/api/v1/category-compare?retailers={ULTA},{SEPHORA}",
        f"/api/v1/insights?retailers={ULTA},{SEPHORA}",
    ],
)
def test_latest_category_and_insight_reads_take_a_stale_source_at_its_own_last_date(
    tmp_path: Path, route: str
) -> None:
    """The live Overview card (2026-10-06): an Ulta import a day older than Faces read n=0 on
    the Faces day. Like /compare, these read each stale source at its own last date (ADR-0010
    §6), so the answer is the beauty file's own, with ``stale_source`` caveats first."""
    beauty = beauty_doc()
    last = str(load_any(beauty).meta.dates[-1])
    faces = dump_dataset(faces_file([last, "2026-10-01"]))
    whole, composed = clients(tmp_path, install(tmp_path, beauty, faces))
    before, after = answer(whole, route), answer(composed, route)
    assert before["status"] == "ok"
    assert after["status"] == "ok"
    # Faces adds only its own ladder and stockout rows to /insights.
    assert without_faces(after["data"]) == before["data"]
    stale = [c for c in after["caveats"] if c["code"] == "stale_source"]
    assert after["caveats"][: len(stale)] == stale
    assert [(c["params"]["retailer"], c["params"]["asOf"]) for c in stale] == [
        (SEPHORA, last),
        (ULTA, last),
    ]
    # An explicit date reads the view itself: neither shop was collected on the Faces day.
    if "insights" in route:
        dated = answer(composed, f"{route}&date=2026-10-01")
        assert dated["data"]["pricing"]["n"] == 0
        assert not [c for c in dated["caveats"] if c["code"] == "stale_source"]


# ---------------------------------------------------------------- the same check on real files


def test_real_files_golden(tmp_path: Path) -> None:
    beauty_path, faces_path = os.environ.get("PI_FACES_BEAUTY"), os.environ.get("PI_FACES_FILE")
    if not (beauty_path and faces_path):
        pytest.skip("set PI_FACES_BEAUTY and PI_FACES_FILE to run the golden on real exports")
    shutil.copyfile(beauty_path, tmp_path / "beauty.json")  # never opened for writing in place
    beauty = (tmp_path / "beauty.json").read_bytes()
    found = golden(beauty, Path(faces_path).read_bytes(), tmp_path / "root")
    print(json.dumps(found, indent=2))
    assert found == {}
