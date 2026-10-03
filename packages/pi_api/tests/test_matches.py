"""A ``pi.matches/v1`` file applied to the composed view (ADR-0012 §6, ``pi_api.matches``)."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from api_fixture import bearer, make_client
from pi_api.config import Settings
from pi_api.matches import STAGE, MatchFileError, apply
from pi_core.enums import MatchClass, ReviewState
from pi_dataset import DatasetV3, dump_dataset, load_any
from pi_match.matchfile import Decision, Edge, ListingRef, MatchFile, Verdict
from test_faces_compose import (
    BEAUTY,
    FACES,
    FACES_PATH,
    SEPHORA,
    ULTA,
    answer,
    beauty_doc,
    differences,
    faces_file,
    generationless,
    install,
)

MATCHES = "datasets/ae/matches/latest.json"
Listing = tuple[str, str]


def ref(listing: Listing) -> ListingRef:
    return ListingRef(retailer=listing[0], token=listing[1])


def edge(
    x: Listing,
    y: Listing,
    cls: MatchClass = MatchClass.EXACT,
    state: ReviewState = ReviewState.PROPOSED,
    confidence: str = "0.95",
) -> Edge:
    a, b = sorted((x, y))
    return Edge(
        a=ref(a),
        b=ref(b),
        match_class=cls,
        review_state=state,
        decided_by=None if state is ReviewState.PROPOSED else "human",
        confidence=Decimal(confidence),
        method="pi_match.incremental/2",
        reasons=(),
    )


def decision(
    x: Listing, y: Listing, verdict: Verdict, cls: MatchClass = MatchClass.EXACT
) -> Decision:
    a, b = sorted((x, y))
    return Decision(a=ref(a), b=ref(b), verdict=verdict, match_class=cls)


def match_file(
    edges: tuple[Edge, ...] = (), decisions: tuple[Decision, ...] = (), scope: str = "beauty"
) -> MatchFile:
    return MatchFile(
        schema_id="pi.matches/v1",
        scope=scope,
        vertical="beauty",
        algo_version="pi_match.incremental/2",
        generated_at="2026-10-03T18:00:00Z",
        listings={},
        unkeyed={},
        candidates=(),
        decisions=decisions,
        edges=edges,
        review=(),
    )


def write(root: Path, file: MatchFile) -> None:
    target = root / MATCHES
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(file.model_dump_json(by_alias=True))


ROUTES = (
    f"/api/v1/compare?retailers={ULTA},{SEPHORA}",
    f"/api/v1/compare?retailers={FACES},{SEPHORA}",
    f"/api/v1/compare?retailers={FACES},{ULTA}",
    f"/api/v1/index?retailers={ULTA},{SEPHORA}",
    f"/api/v1/coverage?retailer={ULTA}",
    f"/api/v1/coverage?retailer={FACES}",
    "/api/v1/coverage",
    f"/api/v1/price-suggestions?subject={SEPHORA}&rival={ULTA}",
    f"/api/v1/price-suggestions?subject={FACES}&rival={SEPHORA}",
)
#: What a proposed merge may change: which products are grouped, never a counted number.
GROUPING = re.compile(
    r"^\$\.(reason|detail|data\.(rows|total|reasons)|data\.sides\.[a-z_]+\.onlyHere)(\b|\[)"
)
ASSIGNED = {SEPHORA: BEAUTY, ULTA: BEAUTY, FACES: FACES_PATH}
#: Fixture products renamed to exporter tokens, so their listings are keyed.
TOKENS = {
    "p12": "s-12-50-ml",
    "p14": "u-14-50-ml",
    "faces-1": "f-1-50-ml",
    "faces-2": "f-2-50-ml",
    "p01": "m-s-01-50-ml-u-01-50-ml",  # in file: exact, approved
    "p07": "m-s-07-50-ml-u-07-50-ml",  # in file: exact, proposed
}
S12, U14, F1, F2 = (
    (SEPHORA, "s-12-50-ml"),
    (ULTA, "u-14-50-ml"),
    (FACES, "f-1-50-ml"),
    (FACES, "f-2-50-ml"),
)
S01, U01 = (SEPHORA, "s-01-50-ml"), (ULTA, "u-01-50-ml")
S07, U07 = (SEPHORA, "s-07-50-ml"), (ULTA, "u-07-50-ml")


def setup(root: Path) -> None:
    dates = [str(d) for d in load_any(beauty_doc()).meta.dates]
    install(root, beauty_doc(), dump_dataset(faces_file(dates[-2:])))


def view(root: Path) -> DatasetV3:
    """The composed three-retailer fixture view, with ``TOKENS`` ids."""
    setup(root)
    _, source = make_client(root, paths=(), assigned=ASSIGNED)
    (loaded,) = source.datasets()
    products = tuple(
        p.model_copy(update={"id": TOKENS.get(p.id, p.id)}) for p in loaded.dataset.products
    )
    return loaded.dataset.model_copy(update={"products": products})


def by_id(ds: DatasetV3) -> dict[str, Any]:
    return {p.id: p for p in ds.products}


def test_three_listings_with_an_edge_each_way_become_one_product(tmp_path: Path) -> None:
    ds = view(tmp_path)
    got = apply(ds, match_file((edge(S12, U14), edge(F2, S12), edge(F2, U14, confidence="0.9"))))
    # faces_ae < sephora_me < ulta_ae: the Faces member gives the id and fields
    assert dict(got.aliases) == {"s-12-50-ml": "f-2-50-ml", "u-14-50-ml": "f-2-50-ml"}
    assert dict(got.counts) == {"merged": 2}
    assert len(got.dataset.products) == len(ds.products) - 2
    merged = by_id(got.dataset)["f-2-50-ml"]
    old = by_id(ds)
    assert merged.offers == {**old["f-2-50-ml"].offers, **old["s-12-50-ml"].offers,
                             **old["u-14-50-ml"].offers}  # fmt: skip
    assert merged.name == old["f-2-50-ml"].name
    assert [(m.a, m.b) for m in merged.matches] == [
        (FACES, SEPHORA), (FACES, ULTA), (SEPHORA, ULTA)
    ]  # fmt: skip
    assert {(m.stage, m.review_state, m.decided_by) for m in merged.matches} == {
        (STAGE, ReviewState.PROPOSED, None)
    }
    assert [m.confidence for m in merged.matches] == ["0.95", "0.9", "0.95"]
    # the rest of the view is as it was
    assert {k: v for k, v in by_id(got.dataset).items() if k != "f-2-50-ml"} == {
        k: v for k, v in old.items() if k not in {"f-2-50-ml", "s-12-50-ml", "u-14-50-ml"}
    }


def test_nothing_is_transitive_an_edge_that_breaks_the_clique_is_skipped(tmp_path: Path) -> None:
    # s12-u14 (approved) goes first; f2-s12 would put f2 with u14, which have no edge
    approved = edge(S12, U14, state=ReviewState.APPROVED, confidence="0.5")
    got = apply(view(tmp_path), match_file((edge(F2, S12, confidence="0.99"), approved)))
    assert dict(got.counts) == {"edge_not_clique": 1, "merged": 1}
    assert dict(got.aliases) == {"u-14-50-ml": "s-12-50-ml"}
    (m,) = by_id(got.dataset)["s-12-50-ml"].matches
    assert (m.review_state, m.decided_by) == (ReviewState.APPROVED, "human")


def test_a_product_has_one_listing_per_retailer(tmp_path: Path) -> None:
    # the higher confidence wins; the other Faces listing is a conflict, not a second offer
    got = apply(view(tmp_path), match_file((edge(F1, S12, confidence="0.9"), edge(F2, S12))))
    assert dict(got.counts) == {"edge_conflict": 1, "merged": 1}
    assert dict(got.aliases) == {"s-12-50-ml": "f-2-50-ml"}


@pytest.mark.parametrize("cls", [MatchClass.FAMILY, MatchClass.SUBSTITUTE])
def test_family_and_substitute_edges_never_merge(tmp_path: Path, cls: MatchClass) -> None:
    ds = view(tmp_path)
    got = apply(ds, match_file((edge(S12, U14, cls, ReviewState.APPROVED),)))
    assert got.dataset == ds
    assert (dict(got.aliases), got.split, dict(got.counts)) == ({}, (), {})


def test_an_edge_outside_the_view_is_counted(tmp_path: Path) -> None:
    ds = view(tmp_path)
    got = apply(ds, match_file((edge(S12, (ULTA, "u-99-50-ml")),)))
    assert dict(got.counts) == {"absent": 1}
    assert got.dataset == ds


@pytest.mark.parametrize(
    "file",
    [
        match_file(decisions=(decision(S01, U01, Verdict.REJECT),)),
        match_file((edge(S01, U01, MatchClass.FAMILY),)),
        match_file(decisions=(decision(S01, U01, Verdict.APPROVE, MatchClass.SUBSTITUTE),)),
    ],
    ids=["rejected", "family_edge", "substitute_decision"],
)
def test_the_file_splits_an_in_file_pair_it_keeps_apart(tmp_path: Path, file: MatchFile) -> None:
    ds = view(tmp_path)
    got = apply(ds, file)
    assert got.split == ("m-s-01-50-ml-u-01-50-ml",)
    products = by_id(got.dataset)
    assert "m-s-01-50-ml-u-01-50-ml" not in products
    old = by_id(ds)["m-s-01-50-ml-u-01-50-ml"]
    retailer_of = {c.id: c.retailer for c in ds.meta.contexts}
    for token, retailer in (("s-01-50-ml", SEPHORA), ("u-01-50-ml", ULTA)):
        half = products[token]
        assert half.matches == ()
        assert half.offers == {c: o for c, o in old.offers.items() if retailer_of[c] == retailer}


def test_an_in_file_pair_takes_the_files_state(tmp_path: Path) -> None:
    ds = view(tmp_path)
    got = apply(ds, match_file((edge(S07, U07, state=ReviewState.APPROVED),)))
    (m,) = by_id(got.dataset)["m-s-07-50-ml-u-07-50-ml"].matches
    assert (m.review_state, m.stage) == (ReviewState.APPROVED, STAGE)
    assert (dict(got.aliases), got.split, dict(got.counts)) == ({}, (), {})


def test_an_in_file_exact_pair_is_evidence_for_the_clique(tmp_path: Path) -> None:
    # p01 groups s01 and u01 in the file; edges to both join a third listing
    got = apply(view(tmp_path), match_file((edge(F1, S01), edge(F1, U01))))
    assert dict(got.counts) == {"merged": 1}
    assert dict(got.aliases) == {"m-s-01-50-ml-u-01-50-ml": "f-1-50-ml"}
    assert len(by_id(got.dataset)["f-1-50-ml"].matches) == 3


def test_a_match_file_of_another_view_is_refused(tmp_path: Path) -> None:
    with pytest.raises(MatchFileError, match="not for view"):
        apply(view(tmp_path), match_file(scope="sa"))


def write_raw(root: Path, body: bytes) -> None:
    target = root / MATCHES
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)


def test_the_view_applies_the_file_and_old_ids_resolve(tmp_path: Path) -> None:
    setup(tmp_path)
    s, u, f = (SEPHORA, "p12"), (ULTA, "p14"), (FACES, "faces-2")
    write(tmp_path, match_file((edge(s, u), edge(f, s), edge(f, u))))
    client, source = make_client(tmp_path, paths=(), assigned=ASSIGNED, matches=MATCHES)
    (loaded,) = source.datasets()
    assert dict(loaded.aliases) == {"p12": "faces-2", "p14": "faces-2"}
    response = client.get("/api/v1/products/p14", headers=bearer())
    assert response.status_code == 200, response.text
    assert response.json()["resolvedFrom"] == {"requestedId": "p14", "currentIds": ["faces-2"]}
    # a new generation of the file is a new view generation
    before = loaded.generation
    write(tmp_path, match_file((edge(s, u),)))
    source.load_all()
    (loaded,) = source.datasets()
    assert loaded.generation != before
    assert dict(loaded.aliases) == {"p14": "p12"}


def test_a_bad_match_file_is_not_applied(tmp_path: Path) -> None:
    setup(tmp_path)
    write_raw(tmp_path, b"{not json")
    _, plain = make_client(tmp_path, paths=(), assigned=ASSIGNED)
    _, source = make_client(tmp_path, paths=(), assigned=ASSIGNED, matches=MATCHES)
    (a,), (b,) = plain.datasets(), source.datasets()
    assert (a.dataset, dict(b.aliases)) == (b.dataset, {})
    # the last good file stays applied when a later one is bad
    write(tmp_path, match_file((edge((SEPHORA, "p12"), (ULTA, "p14")),)))
    source.load_all()
    write_raw(tmp_path, b"\x1f\x8b broken")
    source.load_all()
    (b,) = source.datasets()
    assert dict(b.aliases) == {"p14": "p12"}


def test_a_match_file_of_another_scope_is_not_applied(tmp_path: Path) -> None:
    setup(tmp_path)
    write(tmp_path, match_file((edge((SEPHORA, "p12"), (ULTA, "p14")),), scope="sa"))
    _, plain = make_client(tmp_path, paths=(), assigned=ASSIGNED)
    _, source = make_client(tmp_path, paths=(), assigned=ASSIGNED, matches=MATCHES)
    (a,), (b,) = plain.datasets(), source.datasets()
    assert a.dataset == b.dataset


def test_a_match_file_of_another_vertical_keeps_the_previous_view(tmp_path: Path) -> None:
    setup(tmp_path)
    write(tmp_path, match_file((edge((SEPHORA, "p12"), (ULTA, "p14")),)))
    _, source = make_client(tmp_path, paths=(), assigned=ASSIGNED, matches=MATCHES)
    (before,) = source.datasets()
    wrong = match_file().model_copy(update={"vertical": "fashion"})
    write(tmp_path, wrong)
    source.load_all()
    (after,) = source.datasets()
    assert after is before


def test_proposed_merges_change_grouping_never_a_counted_number(tmp_path: Path) -> None:
    """Golden: three listings joined on proposed edges. Every route answers as without the file,
    except for which products are grouped (ADR-0012 §6: counted metrics need approved edges)."""
    setup(tmp_path)
    s, u, f = (SEPHORA, "p12"), (ULTA, "p14"), (FACES, "faces-2")
    write(tmp_path, match_file((edge(s, u), edge(f, s), edge(f, u))))
    plain, _ = make_client(tmp_path, paths=(), assigned=ASSIGNED)
    merged, _ = make_client(tmp_path, paths=(), assigned=ASSIGNED, matches=MATCHES)
    changed: set[str] = set()
    for route in ROUTES:
        a, b = (generationless(answer(c, route)) for c in (plain, merged))
        diff = list(differences(a, b))
        assert [d for d in diff if not GROUPING.match(d)] == [], route
        changed.update(diff)
    assert changed  # the merge is visible
    a, b = (answer(c, ROUTES[0])["data"]["sides"] for c in (plain, merged))
    for side in a:
        assert a[side]["counted"] == b[side]["counted"]


def env(**extra: str) -> dict[str, str]:
    return {
        "PI_API_FIREBASE_PROJECT": "p",
        "PI_API_DATASETS": f"{SEPHORA}={BEAUTY},{ULTA}={BEAUTY}",
        "PI_API_LOCAL_DIR": "data",
        **extra,
    }


def test_settings_take_the_match_file() -> None:
    assert Settings.from_env(env(PI_API_MATCHES=f" {MATCHES} ")).matches == MATCHES
    assert Settings.from_env(env(PI_API_MATCHES="")).matches is None


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"PI_API_MATCHES": "datasets/../secret.json"}, "not a plain .json object path"),
        ({"PI_API_MATCHES": "matches.txt"}, "not a plain .json object path"),
        ({"PI_API_MATCHES": MATCHES, "PI_API_DATASETS": BEAUTY}, "per-source views"),
    ],
)
def test_settings_refuse_a_bad_match_file(extra: dict[str, str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Settings.from_env(env(**extra))
