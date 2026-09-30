from __future__ import annotations

from datetime import date

import pytest

from pi_dataset import Dataset
from pi_metrics import EVERYTHING, ProductFilter, price_index
from pi_metrics.fixtures import DATES, A, B, D, metrics_dataset, with_capabilities, with_dates
from pi_metrics.model import Reason, Status
from pi_metrics.view import UnknownInput


@pytest.fixture(scope="module")
def ds() -> Dataset:
    return metrics_dataset()


def test_the_basket_is_fixed_on_the_first_date(ds: Dataset) -> None:
    result = price_index(ds, A, B, EVERYTHING)
    assert result.status is Status.OK
    assert result.cohort is not None
    assert result.cohort.n == 7  # p01-p06 and p11
    points = [p.model_dump(mode="json") for p in result.data.points]
    assert [(p["index"], p["n"]) for p in points] == [("98.0", 7), ("98.0", 7), ("103.3", 6)]
    assert result.data.trend_available
    assert result.as_of == DATES[-1]


def test_a_window_narrows_the_dates_and_moves_the_basket(ds: Dataset) -> None:
    result = price_index(ds, A, B, EVERYTHING, start=DATES[-1], end=DATES[-1])
    assert [p.n for p in result.data.points] == [6]
    assert not result.data.trend_available


def test_a_thin_point_is_null_not_interpolated(ds: Dataset) -> None:
    result = price_index(ds, A, B, ProductFilter(ids=("p01", "p02", "p03", "p04", "p11")))
    assert [p.index is None for p in result.data.points] == [False, False, True]
    assert result.data.points[-1].reason is Reason.COHORT_TOO_SMALL
    assert result.status is Status.OK


def test_a_small_basket_is_not_enough_data(ds: Dataset) -> None:
    result = price_index(ds, A, D, EVERYTHING)
    assert result.status is Status.NOT_ENOUGH_DATA
    assert result.reason is Reason.COHORT_TOO_SMALL
    assert all(p.index is None for p in result.data.points)


def test_history_off_allows_only_one_date(ds: Dataset) -> None:
    off = with_capabilities(ds, history=False)
    assert price_index(off, A, B, EVERYTHING).reason is Reason.CAPABILITY_OFF
    one = price_index(off, A, B, EVERYTHING, start=DATES[-1])
    assert one.status is Status.OK
    single = with_capabilities(with_dates(ds, 1), history=False)
    assert price_index(single, A, B, EVERYTHING).status is Status.OK


@pytest.mark.parametrize(
    ("base", "other", "start", "end"),
    [
        (A, A, None, None),
        (A, "nope", None, None),
        (A, B, DATES[-1], DATES[0]),
        (A, B, DATES[-1].replace(year=2030), None),
    ],
)
def test_bad_windows_are_request_errors(
    ds: Dataset, base: str, other: str, start: date | None, end: date | None
) -> None:
    with pytest.raises(UnknownInput):
        price_index(ds, base, other, EVERYTHING, start=start, end=end)
