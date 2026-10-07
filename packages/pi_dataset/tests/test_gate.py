"""The memory rule pi_api loads under (pi-api-deploy.md §6): today's limits are its outputs."""

from __future__ import annotations

import pytest

from pi_dataset import V3_MAX_BYTES
from pi_dataset.gate import (
    OTHERS_MAX_BYTES,
    fits,
    largest_allowed,
    peak_mib,
    refusal,
)

SHA = "a" * 64
FACES = 1_400_000
BEAUTY = 17_050_000


def test_the_exporter_gate_is_the_rule_at_3gi_beside_30_mb_of_others() -> None:
    assert largest_allowed(OTHERS_MAX_BYTES, 3072) == V3_MAX_BYTES == 51_000_000


@pytest.mark.parametrize(
    ("memory_mib", "others", "largest"),
    [(1024, 1_401_000, 21_000_000), (2048, OTHERS_MAX_BYTES, 27_000_000), (3072, 0, 70_000_000)],
)
def test_the_largest_file_allowed_follows_the_memory(
    memory_mib: int, others: int, largest: int
) -> None:
    parts = [others // 3] * 3  # several files, each smaller than the largest
    assert largest_allowed(sum(parts), memory_mib) == largest
    assert fits([largest, *parts], memory_mib)
    assert not fits([largest + 1_000_000, *parts], memory_mib)


def test_todays_set_is_predicted_at_635_mib_and_fits_1gi() -> None:
    assert round(peak_mib([FACES, BEAUTY])) == 635
    assert refusal({"b": (BEAUTY, SHA), "f": (FACES, SHA)}, {}, 1024) is None


def test_beauty_at_25_mb_breaks_1gi() -> None:
    assert refusal({"b": (25_000_000, SHA), "f": (FACES, SHA)}, {}, 1024) is not None
    assert refusal({"b": (25_000_000, SHA), "f": (FACES, SHA)}, {}, 2048) is None


def test_17_mb_beside_10_mb_of_others_is_refused_at_1gi() -> None:
    # 70.4 + 31.48 * 17 + 20 * 10 = 805.6 MiB > 768
    why = refusal({"b": (17_000_000, SHA), "o": (10_000_000, "b" * 64)}, {}, 1024)
    assert why is not None
    assert why.startswith("806 MiB is over 75% of 1024 MiB")
    assert "b (17000000 bytes" in why


def test_an_admitted_largest_body_passes_while_the_others_are_within_its_record() -> None:
    files = {"o": (72_700_000, SHA), "f": (FACES, "b" * 64)}
    assert refusal(files, {}, 3072) is not None
    assert refusal(files, {SHA: FACES}, 3072) is None
    grown = {**files, "f": (FACES + 1, "c" * 64)}
    why = refusal(grown, {SHA: FACES}, 3072)
    assert why is not None
    assert "exceed o's admitted 1400000" in why


def test_the_rule_counts_only_the_largest_at_the_refresh_rate() -> None:
    assert peak_mib([]) == pytest.approx(70.4)
    assert peak_mib([1_000_000, 2_000_000]) == pytest.approx(70.4 + 2 * 31.48 + 20)
