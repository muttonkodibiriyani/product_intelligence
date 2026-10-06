import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pi_core.enums import MatchClass, ReviewState
from pi_match.incremental import (
    ALGO_VERSION,
    DecisionError,
    _assign,
    _cliques,
    dump,
    fingerprint,
    hard_conflicts,
    run,
)
from pi_match.listings import ListingError, listings, split_pair_id
from pi_match.match import prepare
from pi_match.matchfile import (
    Decision,
    Edge,
    ListingRef,
    MatchFile,
    ReviewReason,
    Verdict,
)
from pi_match.model import ProductRecord
from pi_match.run_cli import load_decisions, main

U, S, F = "ulta_ae", "sephora_me", "faces_ae"


def rec(retailer: str, token: str, name: str, **kw: object) -> ProductRecord:
    fields: dict[str, object] = {
        "source": retailer,
        "source_key": token,
        "brand": kw.pop("brand", "Dior"),
        "name": name,
        "category": "fragrance",
    }
    fields.update(kw)
    return ProductRecord.model_validate(fields)


BASE: dict[str, list[ProductRecord]] = {
    U: [
        rec(U, "u-1-100-ml", "Sauvage Eau de Parfum", size="100 ml"),
        rec(U, "u-2-50-ml", "Sauvage Eau de Toilette", size="50 ml"),
        rec(U, "u-3-30-ml", "Miss Dior Blooming Bouquet EDT", size="30 ml"),
    ],
    S: [
        rec(S, "s-P1-100-ml", "Sauvage - Eau de Parfum", size="100 ml"),
        rec(S, "s-P1-60-ml", "Sauvage - Eau de Parfum", size="60 ml"),
        rec(S, "s-P2-50-ml", "Sauvage - Eau de Parfum", size="50 ml"),
    ],
    F: [
        rec(F, "f-9-100-ml", "Sauvage EDP", size="100 ml"),
        rec(F, "f-8-30-ml", "Miss Dior Blooming Bouquet Eau de Toilette", size="30 ml"),
        rec(F, "f-7-30-ml", "Miss Dior Blooming Bouquet Mini", size="30 ml"),
    ],
}
KW: dict[str, Any] = {
    "scope": "ae",
    "vertical": "beauty",
    "algo_version": ALGO_VERSION,
    "generated_at": "2026-10-03T18:00:00Z",
}


def go(
    data: dict[str, list[ProductRecord]],
    previous: MatchFile | None = None,
    decisions: tuple[Decision, ...] = (),
    **kw: Any,
) -> MatchFile:
    return run(data, previous, decisions, **{**KW, **kw})


def edge_set(m: MatchFile) -> set[tuple[str, str, str, str]]:
    return {(e.a.token, e.b.token, e.match_class.value, e.review_state.value) for e in m.edges}


def dec(a: tuple[str, str], b: tuple[str, str], verdict: Verdict, **kw: Any) -> Decision:
    x, y = sorted((a, b))
    return Decision(
        a=ListingRef(retailer=x[0], token=x[1]),
        b=ListingRef(retailer=y[0], token=y[1]),
        verdict=verdict,
        **kw,
    )


def test_three_pairs_accuracy_first() -> None:
    m = go(BASE)
    assert edge_set(m) == {
        ("f-9-100-ml", "s-P1-100-ml", "exact", "proposed"),
        ("f-9-100-ml", "u-1-100-ml", "exact", "proposed"),
        ("s-P1-100-ml", "u-1-100-ml", "exact", "proposed"),
        ("f-8-30-ml", "u-3-30-ml", "exact", "proposed"),
        # same product, different size: family, never exact, and not one-to-one
        ("f-9-100-ml", "s-P1-60-ml", "family", "proposed"),
        ("s-P1-60-ml", "u-1-100-ml", "family", "proposed"),
        ("f-9-100-ml", "s-P2-50-ml", "family", "proposed"),
        ("s-P2-50-ml", "u-1-100-ml", "family", "proposed"),
        # the same line across a hard rule: related (substitute), never exact or family
        ("f-7-30-ml", "u-3-30-ml", "substitute", "proposed"),  # a mini vs the full size
        ("f-9-100-ml", "u-2-50-ml", "substitute", "proposed"),  # EDT vs EDP
        ("s-P1-100-ml", "u-2-50-ml", "substitute", "proposed"),
        ("s-P1-60-ml", "u-2-50-ml", "substitute", "proposed"),
        ("s-P2-50-ml", "u-2-50-ml", "substitute", "proposed"),
    }
    for e in m.edges:
        if "u-2-50-ml" in (e.a.token, e.b.token) or "f-7-30-ml" in (e.a.token, e.b.token):
            assert e.match_class is MatchClass.SUBSTITUTE
    assert all(e.decided_by is None for e in m.edges)


def test_auto_accept_only_for_calibrated_categories() -> None:
    # run() refuses auto-acceptance until the gold-set gate (ADR-0012 §8) exists
    with pytest.raises(ValueError, match="gold-set gate"):
        go(BASE, auto_accept=["fragrance"])
    m = go(BASE)
    assert all(e.review_state is ReviewState.PROPOSED for e in m.edges)
    assert m.auto_accept == ()
    # the assignment rung itself: only exact edges of an accepted category, never family
    prepared = {(r.source, r.source_key): prepare(r) for v in BASE.values() for r in v}
    fps = {k: fingerprint(p) for k, p in prepared.items()}
    edges, _ = _assign(
        m.candidates, {}, prepared, fps, algo_version=ALGO_VERSION,
        auto_accept=frozenset({"fragrance"}),
    )  # fmt: skip
    exact = [e for e in edges if e.match_class is MatchClass.EXACT]
    assert {(e.review_state, e.decided_by) for e in exact} == {(ReviewState.APPROVED, "auto")}
    family = [e for e in edges if e.match_class is MatchClass.FAMILY]
    assert {e.review_state for e in family} == {ReviewState.PROPOSED}


def test_rerun_is_byte_identical_and_reuses_candidates() -> None:
    first = go(BASE)
    again = go(BASE, MatchFile.model_validate_json(dump(first)))
    assert dump(again) == dump(first)


def _mutate(
    data: dict[str, list[ProductRecord]], ops: list[tuple[int, int]]
) -> dict[str, list[ProductRecord]]:
    """Deterministic edits: drop, rename or add listings."""
    out = {r: list(v) for r, v in data.items()}
    names = ["Sauvage Elixir", "J'adore Eau de Parfum", "Sauvage - Eau de Parfum", "Fahrenheit"]
    for n, (op, i) in enumerate(ops):
        retailer = sorted(out)[i % 3]
        rows = out[retailer]
        if op == 0 and rows:
            rows.pop(i % len(rows))
        elif op == 1 and rows:
            r = rows[i % len(rows)]
            rows[i % len(rows)] = r.model_copy(update={"name": names[i % len(names)]})
        else:
            rows.append(
                rec(retailer, f"{retailer[0]}-new{n}-100-ml", names[i % len(names)], size="100 ml")
            )
    return out


@settings(max_examples=40, deadline=None)
@given(st.lists(st.tuples(st.integers(0, 2), st.integers(0, 50)), max_size=6))
def test_incremental_equals_full(ops: list[tuple[int, int]]) -> None:
    changed = _mutate(BASE, ops)
    incremental = go(changed, go(BASE))
    full = go(changed)
    assert dump(incremental) == dump(full)


def test_rejected_pair_never_returns() -> None:
    reject = dec((F, "f-9-100-ml"), (S, "s-P1-100-ml"), Verdict.REJECT)
    m = go(BASE, decisions=(reject,))
    pairs = {(e.a.token, e.b.token) for e in m.edges} | {(r.a.token, r.b.token) for r in m.review}
    assert ("f-9-100-ml", "s-P1-100-ml") not in pairs
    # survives a re-run, a renamed listing (new fingerprint) and a new algorithm version
    renamed = _mutate(BASE, [(1, 0)])
    later = go(renamed, m, algo_version="pi_match.incremental/2")
    assert later.decisions == m.decisions
    assert ("f-9-100-ml", "s-P1-100-ml") not in {(e.a.token, e.b.token) for e in later.edges}


def test_human_decisions_persist_and_lock() -> None:
    lock = dec((S, "s-P1-100-ml"), (U, "u-1-100-ml"), Verdict.LOCK)
    approve = dec(
        (F, "f-9-100-ml"), (S, "s-P1-60-ml"), Verdict.APPROVE, match_class=MatchClass.FAMILY
    )
    m = go(BASE, decisions=(lock, approve))
    later = go(BASE, m, algo_version="pi_match.incremental/9")
    for file in (m, later):
        by_pair = {(e.a.token, e.b.token): e for e in file.edges}
        locked = by_pair[("s-P1-100-ml", "u-1-100-ml")]
        assert (locked.review_state, locked.decided_by) == (ReviewState.LOCKED, "human")
        fam = by_pair[("f-9-100-ml", "s-P1-60-ml")]
        assert (fam.match_class, fam.review_state) == (MatchClass.FAMILY, ReviewState.APPROVED)
    # a human decision on a listing no longer present is kept
    gone = {r: [x for x in v if x.source_key != "u-1-100-ml"] for r, v in BASE.items()}
    kept = go(gone, m)
    assert {(d.pair(), d.verdict) for d in kept.decisions} >= {(lock.pair(), lock.verdict)}
    assert (lock.a.token, lock.b.token) not in {(e.a.token, e.b.token) for e in kept.edges}


def test_approval_goes_back_to_review_when_a_listing_changes() -> None:
    """Reviewer probe: an approved EDP edge must not survive the Ulta side becoming EDT."""
    lock = dec((S, "s-P1-100-ml"), (U, "u-1-100-ml"), Verdict.LOCK)
    m = go(BASE, decisions=(lock,))
    stamped = m.decisions[0]
    assert stamped.fingerprint_a is not None
    assert stamped.fingerprint_b is not None
    assert ("s-P1-100-ml", "u-1-100-ml", "exact", "locked") in edge_set(m)
    changed = {
        **BASE,
        U: [rec(U, "u-1-100-ml", "Sauvage Eau de Toilette", size="100 ml"), *BASE[U][1:]],
    }
    for algo in (ALGO_VERSION, "pi_match.incremental/9"):
        later = go(changed, m, algo_version=algo)
        assert ("s-P1-100-ml", "u-1-100-ml") not in {(e.a.token, e.b.token) for e in later.edges}
        queued = {(r.a.token, r.b.token): r for r in later.review}
        assert queued[("s-P1-100-ml", "u-1-100-ml")].reason is ReviewReason.DECISION_STALE
        assert later.decisions == m.decisions  # the decision itself is history: kept, not edited
    # changing it back restores the edge; a fresh human decision is stamped anew
    assert ("s-P1-100-ml", "u-1-100-ml", "exact", "locked") in edge_set(go(BASE, later))
    edt = go(
        changed, later, decisions=(dec((S, "s-P1-100-ml"), (U, "u-1-100-ml"), Verdict.REJECT),)
    )
    assert all(r.reason is not ReviewReason.DECISION_STALE for r in edt.review)


def test_persisted_approval_that_breaks_a_rule_is_not_an_edge() -> None:
    """A stored decision is re-checked against the hard rules on every run."""
    m = go(BASE)
    fp = {(r, t): f for r, toks in m.listings.items() for t, f in toks.items()}

    def stored(a: tuple[str, str], b: tuple[str, str], cls: MatchClass) -> Decision:
        x, y = sorted((a, b))
        return dec(x, y, Verdict.APPROVE, match_class=cls,
                   fingerprint_a=fp[x], fingerprint_b=fp[y])  # fmt: skip

    bad = (
        stored((S, "s-P2-50-ml"), (U, "u-2-50-ml"), MatchClass.EXACT),  # EDP vs EDT
        stored((F, "f-9-100-ml"), (U, "u-2-50-ml"), MatchClass.FAMILY),  # family needs EDP==EDP
    )
    later = go(BASE, m.model_copy(update={"decisions": bad}))
    pairs = {(e.a.token, e.b.token) for e in later.edges}
    queued = {(r.a.token, r.b.token): r.reason for r in later.review}
    for d in bad:
        assert (d.a.token, d.b.token) not in pairs
        assert queued[(d.a.token, d.b.token)] is ReviewReason.DECISION_BREAKS_RULE


def test_decisions_cannot_break_hard_rules_or_name_unknown_listings() -> None:
    edp_edt = dec((S, "s-P2-50-ml"), (U, "u-2-50-ml"), Verdict.APPROVE)
    with pytest.raises(DecisionError, match="concentration_differs"):
        go(BASE, decisions=(edp_edt,))
    sizes = dec((S, "s-P1-60-ml"), (U, "u-1-100-ml"), Verdict.LOCK)
    with pytest.raises(DecisionError, match="size_differs"):
        go(BASE, decisions=(sizes,))
    with pytest.raises(DecisionError, match="not in this run"):
        go(BASE, decisions=(dec((S, "s-nope"), (U, "u-1-100-ml"), Verdict.REJECT),))
    # family approval of a size difference is allowed; a rejection of anything is allowed
    go(BASE, decisions=(dec((S, "s-P1-60-ml"), (U, "u-1-100-ml"), Verdict.APPROVE,
                            match_class=MatchClass.FAMILY), edp_edt.model_copy(
                                update={"verdict": Verdict.REJECT})))  # fmt: skip


def test_hard_conflicts() -> None:
    a = prepare(rec(U, "u", "Rouge 999 Lipstick", shade="999 Red", gtin="0012345678905"))
    b = prepare(rec(S, "s", "Rouge 999 Lipstick Mini", shade="080 Red", gtin="4006381333931"))
    # b's name says 999 but its shade 080: the name's number is not b's shade, so it counts
    assert hard_conflicts(a, b) == (
        "gtin_differs",
        "kind_differs",
        "number_differs",
        "shade_differs",
    )
    c = prepare(rec(U, "u", "Rouge", shade="Red", brand="Chanel"))
    d = prepare(rec(S, "s", "Rouge", shade="Pink"))
    assert hard_conflicts(c, d) == ("brand_differs", "shade_differs")
    assert fingerprint(c) != fingerprint(d)


def test_one_to_one_conflict_goes_to_review() -> None:
    data = {
        U: [rec(U, "u-1-100-ml", "Sauvage Eau de Parfum", size="100 ml")],
        S: [
            rec(S, "s-A-100-ml", "Sauvage Eau de Parfum", size="100 ml"),
            rec(S, "s-B-100-ml", "Sauvage - Eau de Parfum Spray", size="100 ml"),
        ],
    }
    m = go(data)
    assert [(e.a.token, e.b.token) for e in m.edges] == [("s-A-100-ml", "u-1-100-ml")]
    assert [(r.a.token, r.reason) for r in m.review] == [("s-B-100-ml", ReviewReason.ONE_TO_ONE)]


def _edge(a: tuple[str, str], b: tuple[str, str], conf: str, human: bool = False) -> Edge:
    x, y = sorted((a, b))
    return Edge(
        a=ListingRef(retailer=x[0], token=x[1]),
        b=ListingRef(retailer=y[0], token=y[1]),
        match_class=MatchClass.EXACT,
        review_state=ReviewState.APPROVED if human else ReviewState.PROPOSED,
        decided_by="human" if human else None,
        confidence=Decimal(conf),
        method="t",
        reasons=(),
    )


def test_no_transitive_group_without_its_own_edge() -> None:
    u, s, f = (U, "u1"), (S, "s1"), (F, "f1")
    us, sf = _edge(u, s, "0.99"), _edge(s, f, "0.95")
    kept, dropped = _cliques([us, sf])
    assert (kept, dropped) == ([us], [sf])  # u-s + s-f must not group u with f
    uf = _edge(u, f, "0.90")
    kept, dropped = _cliques([us, sf, uf])
    assert (set(kept), dropped) == ({us, sf, uf}, [])  # a real clique groups all three
    human = _edge(s, f, "0.5", human=True)
    kept, dropped = _cliques([us, human])
    # the human edge outranks the machine one; u-s would group u with f, so it is dropped
    assert (kept, dropped) == ([human], [us])


def test_not_clique_edges_are_queued_for_review() -> None:
    data = {
        U: [rec(U, "u-1-100-ml", "Sauvage Eau de Parfum", size="100 ml")],
        S: [rec(S, "s-1-100-ml", "Sauvage Eau de Parfum", size="100 ml")],
        F: [rec(F, "f-1-100-ml", "Sauvage Eau de Parfum", size="100 ml")],
    }
    m = go(data, decisions=(dec((F, "f-1-100-ml"), (U, "u-1-100-ml"), Verdict.REJECT),))
    reasons = {(r.a.token, r.b.token): r.reason for r in m.review}
    exact = {(e.a.token, e.b.token) for e in m.edges}
    # f-s and s-u both score exact, but f-u is rejected: grouping all three would make f = u
    assert exact == {("f-1-100-ml", "s-1-100-ml")}
    assert reasons[("s-1-100-ml", "u-1-100-ml")] is ReviewReason.NOT_CLIQUE


def test_run_validation() -> None:
    with pytest.raises(ValueError, match="given as"):
        go({U: [rec(S, "s-1", "X")]})
    with pytest.raises(ValueError, match="given twice"):
        go({U: [rec(U, "u-1", "X"), rec(U, "u-1", "Y")]})
    with pytest.raises(ValueError, match="previous file is"):
        go(BASE, go(BASE), scope="sa")
    agg = rec(U, "u-agg", "Sauvage", aggregate=True)
    assert "u-agg" not in go({U: [agg], S: []}).listings.get(U, {})
    with pytest.raises(ValueError, match="two retailers"):
        dec((U, "u-1"), (U, "u-2"), Verdict.REJECT)
    with pytest.raises(ValueError, match="never an edge"):
        _edge((U, "u"), (S, "s"), "1").model_copy(update={"review_state": ReviewState.REJECTED}).model_validate(  # noqa: E501
            {**_edge((U, "u"), (S, "s"), "1").model_dump(), "review_state": "rejected",
             "decided_by": "human"})  # fmt: skip


# ------------------------------------------------------------------ listings from dataset files


def offer(**kw: Any) -> dict[str, Any]:
    return {"sku": "123", "url": None, "size": {"value": "100", "unit": "ml"}, "early": False, **kw}


def product(pid: str, offers: dict[str, Any], name: str = "Sauvage EDP") -> dict[str, Any]:
    return {"id": pid, "brand": "Dior", "name": name, "category": ["fragrance"], "offers": offers}


V2: dict[str, Any] = {
    "meta": {"scope": "beauty", "vertical": "beauty", "retailers": [{"id": U}, {"id": S}]},
    "products": [
        product("u-1-100-ml", {U: offer(image="https://img.example/u1.jpg"), S: None}),
        product("s-P1-100-ml", {S: offer(size=None)}),
        product("m-u-2-50-ml-s-P2-50-ml", {U: offer(), S: offer()}),
        product("p-0123456789abcdef01234567", {U: offer(), S: offer()}),
        product("u-early", {U: offer(early=True)}),
    ],
}


def test_listings_v2_tokens_pairs_and_unkeyed() -> None:
    ulta, ulta_unkeyed = listings(V2, U)
    assert [r.source_key for r in ulta] == ["u-1-100-ml", "u-2-50-ml"]
    assert ulta_unkeyed == 1  # the hashed pair id cannot be split
    sephora, _ = listings(V2, S)
    assert [(r.source_key, r.size) for r in sephora] == [
        ("s-P1-100-ml", None),
        ("s-P2-50-ml", "100 ml"),
    ]
    assert all(r.gtin is None for r in ulta)  # a sku is never read as a GTIN
    assert [r.image_url for r in ulta] == ["https://img.example/u1.jpg", None]
    with pytest.raises(ListingError, match="no retailer"):
        listings(V2, F)
    dup = {
        **V2,
        "products": [
            product("u-1", {U: offer()}),
            product("s-9", {S: offer()}),
            product("m-u-1-s-2", {U: offer(), S: offer()}),
        ],
    }
    with pytest.raises(ListingError, match="twice"):
        listings(dup, U)


def test_listings_never_guess_a_retailer() -> None:
    three = {"meta": {"retailers": [{"id": U}, {"id": S}, {"id": F}]}}
    # a split must name exactly the retailers offering the product
    wrong = [
        product("u-1", {U: offer()}),
        product("s-1", {S: offer()}),
        product("f-1", {F: offer()}),
        product("m-u-2-s-3", {U: offer(), F: offer()}),
    ]
    assert listings({**three, "products": wrong}, U) == (
        listings({**three, "products": wrong[:1]}, U)[0],
        1,
    )
    # a slot letter two retailers share says nothing about which one a token belongs to
    shared = [
        product("u-1", {U: offer()}),
        product("u-9", {S: offer()}),
        product("m-u-2-u-3", {U: offer(), S: offer()}),
    ]
    assert [r.source_key for r in listings({**three, "products": shared}, U)[0]] == ["u-1"]
    assert listings({**three, "products": shared}, U)[1] == 1


def test_listings_v3_contexts() -> None:
    v3 = {
        "meta": {"contexts": [{"id": "ctx-f", "retailer": F}]},
        "products": [
            product(
                "f-1-100-ml", {"ctx-f": offer(content={"images": ["https://img.example/f.jpg"]})}
            ),
            product("f-2-100-ml", {"ctx-f": offer(content={"images": []})}),
        ],
    }
    got = listings(v3, F)[0]
    assert [(r.source_key, r.image_url) for r in got] == [
        ("f-1-100-ml", "https://img.example/f.jpg"),
        ("f-2-100-ml", None),
    ]


def test_split_pair_id() -> None:
    slots = {U: "u", S: "s"}
    assert split_pair_id("m-u-1-50-ml-s-P-50-ml", slots) == {U: "u-1-50-ml", S: "s-P-50-ml"}
    assert split_pair_id("u-1", slots) is None
    assert split_pair_id("m-u-1-u-2", slots) is None  # one retailer twice
    assert split_pair_id("m-u-s-1-s-2", slots) == {U: "u-s-1", S: "s-2"}  # one split fits
    assert split_pair_id("m-u-1-s-2-s-3", slots) is None  # "u-1|s-2-s-3" or "u-1-s-2|s-3"


# ------------------------------------------------------------------------------------- CLI


def test_cli_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    beauty = tmp_path / "beauty.json"
    beauty.write_text(json.dumps(V2))
    faces = tmp_path / "faces.json"
    meta = {"scope": "beauty", "vertical": "beauty", "retailers": [{"id": F}]}
    faces.write_text(json.dumps({"meta": meta, "products": [product("f-9-100-ml", {F: offer()})]}))
    out = tmp_path / "m.json"
    argv = [f"--source={U}={beauty}", f"--source={S}={beauty}", f"--source={F}={faces}",
            "--generated-at=2026-10-03T18:00:00Z", f"--out={out}"]  # fmt: skip
    assert main(argv) == 0
    assert MatchFile.model_validate_json(out.read_text()).scope == "beauty"  # from the sources
    stats = json.loads(capsys.readouterr().out)
    assert stats["listings"] == {F: 1, S: 2, U: 2}
    assert stats["unkeyed"] == {F: 0, S: 1, U: 1}
    first = out.read_text()
    decisions = tmp_path / "d.jsonl"
    decisions.write_text(
        dec((F, "f-9-100-ml"), (S, "s-P1-100-ml"), Verdict.REJECT).model_dump_json(by_alias=True)
        + "\n\n"
    )
    assert main([*argv[:-1], f"--previous={out}", f"--decisions={decisions}", f"--out={out}"]) == 0
    assert out.read_text() != first
    assert len(load_decisions(decisions)) == 1
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"verdict": "maybe"}\n')
    with pytest.raises(SystemExit, match=r"bad\.jsonl:1"):
        load_decisions(bad)
    with pytest.raises(SystemExit):
        main(
            [f"--source={U}={beauty}", f"--source={U}={beauty}", "--generated-at=x", f"--out={out}"]
        )
    faces.write_text(json.dumps({"meta": {**meta, "scope": "sa"}, "products": []}))
    with pytest.raises(SystemExit):  # a match file is for one view
        main(argv)
