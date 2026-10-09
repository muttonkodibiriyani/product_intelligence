"""The body-only ADR-0013 re-export: offers unchanged, each retailer's own fields and capabilities,
never better than the file states."""

from __future__ import annotations

# ruff: noqa: S101
import gzip
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from pi_dataset import Dataset, DatasetV3, FieldStatus, dump_dataset, load_any
from pi_dataset.compose import CompositionError, resolved_retailers
from pi_metrics.view import as_v3
from scripts.demo_export.export import ListingRow, UltaContext
from scripts.demo_export.reexport import capped, main, reexport
from scripts.demo_export.test_export import row
from scripts.demo_export.test_v2 import NOTE, NOW
from scripts.demo_export.v2 import build_dataset_v2

SEPHORA, ULTA = "sephora_me", "ulta_ae"
OK, PARTIAL = FieldStatus.OK, FieldStatus.PARTIAL
NOT_COLLECTED, NOT_PUBLISHED = FieldStatus.NOT_COLLECTED, FieldStatus.NOT_PUBLISHED


def rows() -> list[ListingRow]:
    """Sephora states no regular price (as in the owner's beauty file); Ulta states one."""
    return [
        row(variant=101, regular=None),
        row(variant=102, regular=None, size=None),
        row(source=ULTA, family=20, variant=200),
        row(source=ULTA, family=20, variant=201, size="75"),
    ]


def combined() -> Dataset:
    return build_dataset_v2(
        rows(),
        [],
        generated_at=NOW,
        ulta=UltaContext(blocked_since=datetime(2026, 9, 30, 20, 55, tzinfo=UTC)),
        ulta_note=NOTE,
    )


def dumped(ds: Dataset | DatasetV3) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(dump_dataset(ds, compact=True))
    return out


def test_only_the_retailers_fields_and_capabilities_change() -> None:
    v2 = combined()
    old, new = dumped(as_v3(v2)), dumped(reexport(v2))
    assert old["products"] == new["products"]
    assert old["notObserved"] == new["notObserved"]
    meta_old, meta_new = old["meta"], new["meta"]
    assert isinstance(meta_old, dict)
    assert isinstance(meta_new, dict)
    assert {k for k in meta_old if meta_old[k] != meta_new[k]} == {"retailers"}
    for a, b in zip(meta_old["retailers"], meta_new["retailers"], strict=True):
        assert {k for k in a if a[k] != b[k]} == {"fields", "capabilities"}


def test_the_combined_file_composes_only_after_the_re_export() -> None:
    v2 = combined()
    with pytest.raises(CompositionError, match="re-export it"):
        resolved_retailers(as_v3(v2))
    assert {r.id for r in resolved_retailers(reexport(v2))} == {SEPHORA, ULTA}


def test_a_retailer_without_regular_prices_has_no_promotions() -> None:
    v2 = combined()
    assert v2.meta.fields["regular"] is OK
    assert v2.meta.capabilities.promotions
    states = {r.id: r for r in reexport(v2).meta.retailers}
    sephora, ulta = states[SEPHORA], states[ULTA]
    assert sephora.fields is not None
    assert sephora.capabilities is not None
    assert ulta.fields is not None
    assert ulta.capabilities is not None
    assert sephora.fields["regular"] is NOT_COLLECTED
    assert not sephora.capabilities.promotions
    assert ulta.fields["regular"] is OK
    assert ulta.capabilities.promotions


def test_a_retailer_keeps_the_files_state_where_its_offers_carry_the_field() -> None:
    own = {"price": OK, "regular": NOT_COLLECTED, "size": OK, "shades": OK, "gtin": NOT_PUBLISHED}
    file = {"price": PARTIAL, "regular": OK, "size": PARTIAL, "shades": NOT_COLLECTED}
    file |= {"gtin": NOT_PUBLISHED}
    assert capped(own, file) == {
        "price": PARTIAL,  # never better than the file: it may have counted stale values
        "regular": NOT_COLLECTED,  # none of the retailer's offers carries one
        "size": PARTIAL,
        "shades": NOT_COLLECTED,  # the file's absence stands, whatever the offers hold
        "gtin": NOT_PUBLISHED,
    }


def test_fields_must_be_the_files() -> None:
    with pytest.raises(ValueError, match="are not the file's"):
        capped({"price": OK}, {"price": OK, "regular": OK})


def test_a_capability_is_on_only_where_the_file_turns_it_on() -> None:
    v2 = combined()
    v2 = v2.model_copy(
        update={
            "meta": v2.meta.model_copy(
                update={"capabilities": v2.meta.capabilities.model_copy(update={"sizes": False})}
            )
        }
    )
    assert not any(r.capabilities and r.capabilities.sizes for r in reexport(v2).meta.retailers)


def test_a_snapshot_of_several_dates_is_refused() -> None:
    v2 = combined()
    v2 = v2.model_copy(
        update={"meta": v2.meta.model_copy(update={"dates": (*v2.meta.dates, *v2.meta.dates)})}
    )
    with pytest.raises(ValueError, match="one date only"):
        reexport(v2)


def test_a_retailer_without_offers_is_refused() -> None:
    v2 = combined()
    v2 = v2.model_copy(
        update={"products": tuple(p for p in v2.products if SEPHORA not in p.offers)}
    )
    with pytest.raises(ValueError, match="every retailer must have offers"):
        reexport(v2)


def test_main_writes_the_compact_body_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src, out = tmp_path / "in.json.gz", tmp_path / "out.json"
    src.write_bytes(gzip.compress(dump_dataset(combined())))
    main([str(src), str(out)])
    assert load_any(out.read_bytes()) == reexport(combined())
    printed = capsys.readouterr().out
    assert "sephora_me: " in printed
    assert "regular=not_collected" in printed
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        main([str(src), str(out)])


def test_main_refuses_a_v3_body(tmp_path: Path) -> None:
    src = tmp_path / "in.json"
    src.write_bytes(dump_dataset(reexport(combined())))
    with pytest.raises(SystemExit, match=r"not a pi\.dataset/v2 body"):
        main([str(src), str(tmp_path / "out.json")])


def test_the_output_is_deterministic() -> None:
    assert dump_dataset(reexport(combined()), compact=True) == dump_dataset(
        reexport(combined()), compact=True
    )
