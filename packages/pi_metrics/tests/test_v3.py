"""The v3 rules of ADR-0008 step 3: contexts, identity, the same-size rule and applicability."""

from __future__ import annotations

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
from pi_metrics.model import CaveatCode, Excluded, Reason, Status
from pi_metrics.view import SizeMatch, same_size
from v3_fixture import APP, WEB, load, offer, profile, size, split_shop_a
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
        (sz(None, None, "Medium"), sz(None, None, "Large"), True, SizeMatch.MISMATCH),
        (sz(None, None, "M", "alpha"), sz(None, None, "M", "eu"), True, SizeMatch.MISMATCH),
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


@pytest.mark.parametrize(("label", "expected"), [(" medium", None), ("Large", "size_mismatch")])
def test_label_only_sizes_compare_on_the_folded_label(label: str, expected: str | None) -> None:
    d = menu()
    offer(d, "p01", WEB)["size"] = size(None, None, "Medium")
    offer(d, "p01", APP)["size"] = size(None, None, label)
    assert rows(load(d), WEB, APP)["p01"] == expected


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
