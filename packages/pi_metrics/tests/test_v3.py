"""ADR-0008 steps 3-4: contexts, identity, sizes, caveats, coverage and applicability."""

from __future__ import annotations

import gc
import weakref
from collections.abc import Callable
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from metrics_fixture import DATES, B, metrics_dataset, rebuild
from pi_dataset import DatasetV3, SizeV3
from pi_metrics import (
    EVERYTHING,
    Metric,
    assortment_gaps,
    availability,
    compare,
    coverage,
    launches,
    price_index,
    promotions,
    reviews_summary,
    view,
)
from pi_metrics.compare import LABEL_CAVEAT_CAP
from pi_metrics.model import CaveatCode, Excluded, Reason, Status
from pi_metrics.view import SizeMatch, same_size
from v3_fixture import APP, APP_PRODUCTS, WEB, load, offer, profile, size, split_shop_a
from v3_fixture import doc as base_doc


def menu(*, labels_comparable: bool = True, channel: str = "delivery") -> dict[str, Any]:
    d = profile(base_doc(), "food_menu", labels_comparable=labels_comparable)
    return split_shop_a(d, app_channel=channel)


def rows(ds: DatasetV3, base: str, other: str) -> dict[str, Excluded | None]:
    return {r.id: r.excluded_reason for r in compare(ds, base, other, EVERYTHING).data.rows}


def caveats(metric: Metric[Any], code: CaveatCode) -> list[dict[str, str]]:
    return [c.params for c in metric.caveats if c.code is code]


# ------------------------------------------------------------------ same-size rule

#: Full-width "MEDIUM": NFKC folds it to ASCII.
WIDE_MEDIUM = "\uff2d\uff25\uff24\uff29\uff35\uff2d"


def sz(value: str | None, unit: str | None, label: str | None, system: str | None = None) -> SizeV3:
    return SizeV3(value=value, unit=unit, label=label, system=system)


@pytest.mark.parametrize(
    ("a", "b", "comparable", "expected"),
    [
        (sz("50", "ml", None), sz("50.0", " ML ", None), False, SizeMatch.EQUAL),
        (sz("50", "ml", None), sz("75", "ml", None), False, SizeMatch.MISMATCH),
        (sz("50", "ml", None), sz("50", "g", None), False, SizeMatch.MISMATCH),
        (sz("50", "ml", "Small"), sz("50", "ml", " small "), False, SizeMatch.EQUAL),
        (sz("50", "ml", "Small"), sz("50", "ml", "Regular"), False, SizeMatch.LABELS_DIFFER),
        (sz("50", "ml", "Small"), sz("50", "ml", None), False, SizeMatch.EQUAL),
        (sz(None, None, "Medium"), sz(None, None, WIDE_MEDIUM), True, SizeMatch.EQUAL),
        (sz(None, None, "Medium"), sz(None, None, "Medium"), False, SizeMatch.UNKNOWN),
        (sz(None, None, "Medium"), sz(None, None, "Large"), True, SizeMatch.UNKNOWN),
        (sz(None, None, "M", "alpha"), sz(None, None, "M", "eu"), True, SizeMatch.UNKNOWN),
        (sz(None, None, "\u0648\u0633\u0637"), sz(None, None, "Medium"), True, SizeMatch.UNKNOWN),
        (sz(None, None, "M", "alpha"), sz(None, None, "m", "alpha"), True, SizeMatch.EQUAL),
        (sz(None, None, "Medium"), sz("50", "ml", "Medium"), True, SizeMatch.UNKNOWN),
        (None, sz("50", "ml", None), True, SizeMatch.UNKNOWN),
        (None, None, True, SizeMatch.UNKNOWN),
    ],
)
def test_same_size_rule_table(
    a: SizeV3 | None, b: SizeV3 | None, comparable: bool, expected: SizeMatch
) -> None:
    assert same_size(a, b, labels_comparable=comparable) is expected
    assert same_size(b, a, labels_comparable=comparable) is expected


_labels = st.sampled_from(["Small", "small", " SMALL", "Large", "\uff33mall", "M"])
_sizes = st.one_of(
    st.none(),
    st.builds(
        sz,
        value=st.sampled_from(["50", "50.0", "75"]),
        unit=st.sampled_from(["ml", "ML", "g"]),
        label=st.one_of(st.none(), _labels),
    ),
    st.builds(
        sz,
        value=st.none(),
        unit=st.none(),
        label=_labels,
        system=st.sampled_from([None, "alpha", "eu"]),
    ),
)


@given(a=_sizes, b=_sizes, comparable=st.booleans())
def test_same_size_is_symmetric_and_reflexive(
    a: SizeV3 | None, b: SizeV3 | None, comparable: bool
) -> None:
    assert same_size(a, b, labels_comparable=comparable) is same_size(
        b, a, labels_comparable=comparable
    )
    if a is not None and (a.value is not None or comparable):
        assert same_size(a, a, labels_comparable=comparable) is SizeMatch.EQUAL


# ------------------------------------------------------------------ identity and contexts


def test_one_retailers_contexts_pair_on_the_stable_key_without_an_edge() -> None:
    ds = load(menu())
    got = rows(ds, WEB, APP)
    assert {pid for pid, why in got.items() if why is None} == {
        "p01", "p02", "p03", "p04", "p05", "p06", "p10", "p12",
    }  # fmt: skip
    assert got["p07"] is Excluded.NOT_OFFERED  # at WEB only


def test_a_context_pairs_across_retailers_through_the_retailer_edge() -> None:
    ds = load(menu())
    got = rows(ds, APP, B)
    assert {pid for pid, why in got.items() if why is None} == {f"p0{n}" for n in range(1, 7)}
    assert got["p10"] is Excluded.SIZE_MISMATCH
    assert rows(ds, WEB, B) == rows(load(profile(base_doc(), "food_menu")), "shop_a", B)


def _rekey(ds: DatasetV3, product_id: str, context_id: str, key: str | None) -> DatasetV3:
    """Breaks rule (b) or (c) past the validator, as a corrupt document would."""
    products = []
    for p in ds.products:
        if p.id == product_id:
            o = p.offers[context_id]
            evidence = o.evidence.model_copy(
                update={"item_key": key, "item_key_kind": None if key is None else "sku"}
            )
            offers = {**p.offers, context_id: o.model_copy(update={"evidence": evidence})}
            p = p.model_copy(update={"offers": offers})  # noqa: PLW2901 -- a rebuilt copy
        products.append(p)
    return ds.model_copy(update={"products": tuple(products)})


@pytest.mark.parametrize("key", ["a-other", None], ids=["two-keys", "unkeyed"])
def test_unclear_identity_fails_safe_to_no_match(key: str | None) -> None:
    ds = _rekey(load(menu()), "p01", APP, key)
    assert rows(ds, WEB, APP)["p01"] is Excluded.NO_MATCH
    assert rows(ds, APP, B)["p01"] is Excluded.NO_MATCH
    assert rows(ds, B, WEB)["p01"] is Excluded.NO_MATCH  # every pair involving shop_a
    assert rows(ds, WEB, APP)["p02"] is None


def test_unknown_context_is_a_request_error() -> None:
    with pytest.raises(view.UnknownInput, match="unknown retailer or context"):
        compare(load(menu()), "shop_a", B, EVERYTHING)


# ------------------------------------------------------------------ caveats


def test_different_channels_carry_channel_differs() -> None:
    ds = load(menu())
    expected = [{"base": "delivery", "other": "online"}]
    assert caveats(compare(ds, APP, B, EVERYTHING), CaveatCode.CHANNEL_DIFFERS) == expected
    assert caveats(price_index(ds, APP, B, EVERYTHING), CaveatCode.CHANNEL_DIFFERS) == expected
    assert caveats(compare(ds, WEB, B, EVERYTHING), CaveatCode.CHANNEL_DIFFERS) == []


def test_equal_measures_with_different_labels_count_with_a_caveat() -> None:
    d = menu()
    for pid in ("p01", "p02"):
        offer(d, pid, APP)["size"] = size("50.0", "ML", "Regular")
        offer(d, pid, WEB)["size"] = size("50", "ml", "Small")
    offer(d, "p03", APP)["size"] = size("50", "ml", "Tall")
    offer(d, "p03", WEB)["size"] = size("50", "ml", "Grande")
    offer(d, "p04", APP)["size"] = size("50", "ml", "SMALL")
    offer(d, "p04", WEB)["size"] = size("50", "ml", "small")
    ds = load(d)
    assert all(rows(ds, WEB, APP)[p] is None for p in ("p01", "p02", "p03", "p04"))
    assert caveats(compare(ds, WEB, APP, EVERYTHING), CaveatCode.SIZE_LABELS_DIFFER) == [
        {"base": "Small", "other": "Regular", "count": "2"},
        {"base": "Grande", "other": "Tall", "count": "1"},
    ]
    index = price_index(ds, APP, WEB, EVERYTHING)
    assert caveats(index, CaveatCode.SIZE_LABELS_DIFFER)[0] == {
        "base": "Regular", "other": "Small", "count": "2",
    }  # fmt: skip


@pytest.mark.parametrize(("label", "expected"), [(" medium", None), ("Large", "size_unknown")])
def test_label_only_sizes_compare_on_the_folded_label(label: str, expected: str | None) -> None:
    d = menu()
    offer(d, "p01", WEB)["size"] = size(None, None, "Medium")
    offer(d, "p01", APP)["size"] = size(None, None, label)
    assert rows(load(d), WEB, APP)["p01"] == expected


def labelled(distinct: int) -> DatasetV3:
    """Every APP product counted on equal measures; ``p01`` and ``p02`` share label pair 0."""
    d = menu()
    for n, pid in enumerate(APP_PRODUCTS):
        pair = max(0, min(n - 1, distinct - 1))
        offer(d, pid, WEB)["size"] = size("50", "ml", f"w{pair}")
        offer(d, pid, APP)["size"] = size("50", "ml", f"a{pair}")
    return load(d)


def test_label_caveats_up_to_the_cap_are_all_listed_with_no_total() -> None:
    ds = labelled(LABEL_CAVEAT_CAP)
    assert all(rows(ds, WEB, APP)[p] is None for p in APP_PRODUCTS)
    metric = compare(ds, WEB, APP, EVERYTHING)
    assert [c.code for c in metric.caveats if c.code is not CaveatCode.SIZE_LABELS_DIFFER] == [
        CaveatCode.CHANNEL_DIFFERS
    ]
    assert len(caveats(metric, CaveatCode.SIZE_LABELS_DIFFER)) == LABEL_CAVEAT_CAP


@pytest.mark.parametrize("metric", [compare, price_index])
def test_past_the_cap_the_total_leads_and_only_the_most_frequent_pairs_follow(
    metric: Callable[..., Metric[Any]],
) -> None:
    ds = labelled(7)
    got = [(c.code, c.params) for c in metric(ds, WEB, APP, EVERYTHING).caveats]
    labels = [(code, params) for code, params in got if code.startswith("size_labels_differ")]
    channel = (CaveatCode.CHANNEL_DIFFERS, {"base": "online", "other": "delivery"})
    total = (CaveatCode.SIZE_LABELS_DIFFER_TOTAL, {"count": "8", "pairs": "7"})
    assert got[-(LABEL_CAVEAT_CAP + 2) :] == [total, channel, *labels[1:]]
    assert labels[1:] == [
        (CaveatCode.SIZE_LABELS_DIFFER, {"base": f"w{i}", "other": f"a{i}", "count": c})
        for i, c in [(0, "2"), (1, "1"), (2, "1"), (3, "1"), (4, "1")]
    ]


# ------------------------------------------------------------------ notObserved per context


def test_a_not_observed_window_names_one_context_or_the_whole_retailer() -> None:
    d = menu()
    window = {"retailer": "shop_a", "start": str(DATES[0]), "end": str(DATES[-1])}
    d["notObserved"] = [{**window, "categories": None, "why": {"en": "x"}, "context": APP}]
    ds = load(d)
    p01 = view.product_v3(ds, "p01")
    assert view.not_observed(ds, APP, p01, 2)
    assert not view.not_observed(ds, WEB, p01, 2)
    assert view.complete_run(ds, WEB, p01, 2)
    assert not view.complete_run(ds, APP, p01, 2)
    d["notObserved"][0]["context"] = None
    ds = load(d)
    assert view.not_observed(ds, APP, p01, 2)
    assert view.not_observed(ds, WEB, p01, 2)


# ------------------------------------------------------------------ applicability


METRICS: dict[str, Callable[[DatasetV3], Metric[Any]]] = {
    "compare": lambda ds: compare(ds, "shop_a", B, EVERYTHING),
    "index": lambda ds: price_index(ds, "shop_a", B, EVERYTHING),
    "assortment": lambda ds: assortment_gaps(ds, "shop_a", B, EVERYTHING),
    "promotions": lambda ds: promotions(ds, (), EVERYTHING),
    "availability": lambda ds: availability(ds, (), EVERYTHING),
    "launches": lambda ds: launches(ds, (), EVERYTHING),
    "reviews": lambda ds: reviews_summary(ds, (), EVERYTHING),
}


@pytest.mark.parametrize("name", sorted(METRICS))
def test_a_metric_off_its_profiles_is_not_applicable(name: str) -> None:
    metric = METRICS[name](load(profile(base_doc(), "test_menu")))
    assert (metric.status, metric.reason) == (Status.NOT_ENOUGH_DATA, Reason.NOT_APPLICABLE)


@pytest.mark.parametrize("name", sorted(METRICS))
@pytest.mark.parametrize("vertical", ["food_menu", "apparel"])
def test_a_metric_on_its_profiles_is_unchanged(name: str, vertical: str) -> None:
    beauty = METRICS[name](load(base_doc()))
    other = METRICS[name](load(profile(base_doc(), vertical)))
    assert other == beauty


def test_coverage_applies_to_every_profile() -> None:
    ds = load(profile(base_doc(), "test_menu"))
    assert coverage(ds, ()) == coverage(load(base_doc()), ())


# ------------------------------------------------------------------ coverage per context


def contexts_of(ds: DatasetV3, shop: str) -> dict[str, list[bool]]:
    row = next(r for r in coverage(ds, ()).data.retailers if r.id == shop)
    return {c.id: [d.observed for d in c.dates] for c in row.contexts}


def test_a_sole_context_is_the_retailer_and_mirrors_its_freshness() -> None:
    ds = load(base_doc())
    for row in coverage(ds, ()).data.retailers:
        (ctx,) = row.contexts
        assert (ctx.id, ctx.status, ctx.product_count) == (row.id, row.status, row.product_count)
        assert ctx.freshness == (row.freshness if row.status.value != "blocked" else None)
        assert [d.date for d in ctx.dates] == list(DATES)


def test_coverage_lists_each_context_and_the_dates_it_was_observed() -> None:
    d = menu()
    day = {"retailer": "shop_a", "start": str(DATES[1]), "end": str(DATES[1]), "why": {"en": "x"}}
    d["notObserved"] = [
        {**day, "categories": None, "context": APP},
        # A window over some categories leaves the context observed that day.
        {**day, "categories": ["skincare"], "context": WEB},
    ]
    ds = load(d)
    assert contexts_of(ds, "shop_a") == {WEB: [True, True, True], APP: [True, False, True]}
    row = next(r for r in coverage(ds, ()).data.retailers if r.id == "shop_a")
    web, app = row.contexts
    assert (web.channel, app.channel) == ("online", "delivery")
    assert app.product_count < web.product_count == row.product_count


def test_a_blocked_retailers_contexts_are_never_observed() -> None:
    d = base_doc()
    assert any(contexts_of(load(d), B)[B])
    next(r for r in d["meta"]["retailers"] if r["id"] == B)["status"] = "blocked"
    assert contexts_of(load(d), B) == {B: [False] * len(DATES)}


# ------------------------------------------------------------------ the upgrade cache


def test_a_v2_document_is_upgraded_once_and_read_by_identity() -> None:
    v2 = metrics_dataset()
    v3 = view.as_v3(v2)
    assert view.as_v3(v2) is v3
    assert view.as_v3(v3) is v3
    assert view.as_v3(metrics_dataset()) is not v3  # equal value, different document


def test_the_oldest_upgrade_is_evicted_beyond_the_limit() -> None:
    first = metrics_dataset()
    kept = view.as_v3(first)
    others = [metrics_dataset() for _ in range(view._Upgraded.LIMIT)]
    for ds in others:
        view.as_v3(ds)
    assert view.as_v3(others[-1]) is view.as_v3(others[-1])
    assert view.as_v3(first) is not kept
    assert view.as_v3(first) == kept


def test_a_v2_vertical_without_a_committed_profile_is_not_read() -> None:
    with pytest.raises(ValueError, match="no committed profile food_menu@1"):
        view.as_v3(rebuild(metrics_dataset(), vertical="food_menu"))


def test_a_dropped_generation_and_its_upgrade_are_freed() -> None:
    first = metrics_dataset()
    upgraded = weakref.ref(view.as_v3(first))
    source = weakref.ref(first)
    view.as_v3(metrics_dataset())  # the next generation
    del first
    gc.collect()
    assert source() is None
    assert upgraded() is None
