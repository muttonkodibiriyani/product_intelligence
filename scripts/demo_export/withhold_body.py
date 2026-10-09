"""Withhold one retailer of a published body beside a windowed one (ADR-0013 §8), from the bodies
alone: no database, no crawl.

A served set where any retailer has a crawl window refuses every windowless retailer with offers
unless it is WITHHELD: its ``since`` (last observed market day) is set and one whole-retailer
``notObserved`` entry runs from the day after ``since`` to the set's cutoff day
(``pi_dataset.v3._withheld_errors`` on the composed view, ``pi_api.windows``). The exporter's F1
``--withhold`` writes that at export time; this writes it into a body already published, the
same entry by the same rule (``v2.withhold``), so its offers and every value stay as they are.

``since`` is the market day of the retailer's latest ``capturedAt`` and must be the body's last
date; ``until`` is the windowed body's cutoff day in the retailer's market, never before the
body's own. Nothing is guessed: a retailer with a window, no offers, a ``since`` or a
whole-retailer entry already is refused (Coordinator ruling 01a122bf-547a).

    uv run python -m scripts.demo_export.withhold_body IN OUT --retailer ID --beside WINDOWED
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
from datetime import date, timedelta
from pathlib import Path
from typing import overload

from pi_dataset import Dataset, DatasetV3, dump_dataset, load_any
from pi_dataset.models import NotObserved
from pi_dataset.v3 import NotObservedV3, local_date
from scripts.demo_export.v2 import SINCE, with_since

#: The approved withhold reason (Coordinator 01a122bf-547a), dated by ``v2.with_since``.
WHY = {"en": f"Not observed since {SINCE}", "ar": f"لم تُرصد منذ {SINCE}"}


def last_observed(ds: Dataset | DatasetV3, retailer: str) -> date:
    """The market day of ``retailer``'s latest ``capturedAt``; it must be the body's last date."""
    zone = ds.market_of(retailer).time_zone
    owner = {c.id: c.retailer for c in ds.meta.contexts} if isinstance(ds, DatasetV3) else {}
    captured = [
        o.evidence.captured_at
        for p in ds.products
        for key, o in p.offers.items()
        if owner.get(key, key) == retailer
    ]
    if not captured:
        raise ValueError(f"{retailer}: no offers, nothing to withhold")
    since = local_date(max(captured), zone)
    if since != ds.meta.dates[-1]:
        raise ValueError(f"{retailer}: last capture {since} is not the body's last date")
    return since


@overload
def withhold_body(ds: Dataset, retailer: str, until: date) -> Dataset: ...
@overload
def withhold_body(ds: DatasetV3, retailer: str, until: date) -> DatasetV3: ...
def withhold_body(ds: Dataset | DatasetV3, retailer: str, until: date) -> Dataset | DatasetV3:
    """``ds`` with ``retailer`` withheld to ``until``; ``ValueError`` if it can't be."""
    r = next((r for r in ds.meta.retailers if r.id == retailer), None)
    if r is None:
        raise ValueError(f"the body has no retailer {retailer}")
    if getattr(r, "window", None) is not None:
        raise ValueError(f"{retailer} has a crawl window: it is counted, not withheld")
    if r.since is not None or any(
        n.retailer == retailer and n.categories is None and getattr(n, "context", None) is None
        for n in ds.not_observed
    ):
        raise ValueError(f"{retailer} is already withheld")
    since = last_observed(ds, retailer)
    day = local_date(ds.meta.cutoff, ds.market_of(retailer).time_zone)
    if until < day:
        raise ValueError(f"withheld until {until}: before the body's cutoff day {day}")
    entry = NotObserved(
        retailer=retailer,
        start=min(since + timedelta(days=1), day),
        end=until,
        categories=None,
        why=with_since(WHY, since),
    )
    if isinstance(ds, DatasetV3):
        entry = NotObservedV3(**entry.model_dump(), context=None)  # the whole retailer
    retailers = tuple(
        x.model_copy(update={"since": since}) if x.id == retailer else x for x in ds.meta.retailers
    )
    return ds.model_copy(
        update={
            "meta": ds.meta.model_copy(update={"retailers": retailers}),
            "not_observed": (*ds.not_observed, entry),
        }
    )


def read_any(path: Path) -> Dataset | DatasetV3:
    raw = path.read_bytes()
    return load_any(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)


def until_of(windowed: DatasetV3, time_zone: str) -> date:
    """The windowed body's cutoff day in ``time_zone``; it must have a crawl window."""
    if all(r.window is None for r in windowed.meta.retailers):
        raise ValueError("the --beside body has no crawl window")
    return local_date(windowed.meta.cutoff, time_zone)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", type=Path, help="the body (gzip or plain, v2 or v3)")
    parser.add_argument("output", type=Path, help="the withheld body, compact (never overwritten)")
    parser.add_argument("--retailer", required=True, help="the retailer to withhold")
    parser.add_argument("--beside", required=True, type=Path, help="the windowed v3 body")
    args = parser.parse_args(argv)
    if args.output.exists():
        raise SystemExit(f"{args.output} exists: refusing to overwrite")
    ds, windowed = read_any(args.input), read_any(args.beside)
    if not isinstance(windowed, DatasetV3):
        raise SystemExit(f"{args.beside}: not a pi.dataset/v3 body")
    if windowed.meta.scope != ds.meta.scope:
        raise SystemExit(f"--beside scope {windowed.meta.scope} is not {ds.meta.scope}")
    try:
        until = until_of(windowed, ds.market_of(args.retailer).time_zone)
        out = withhold_body(ds, args.retailer, until)
    except (ValueError, StopIteration) as e:
        raise SystemExit(f"{args.input}: {e}") from None
    body = dump_dataset(out, compact=True)
    if load_any(body) != out:  # what pi-api reads back must be what was built
        raise SystemExit("the written body does not read back as built")
    args.output.write_bytes(body)
    entry = out.not_observed[-1]
    since = next(r.since for r in out.meta.retailers if r.id == args.retailer)
    print(f"sha256 {hashlib.sha256(body).hexdigest()} bytes {len(body)}")
    print(f"{args.retailer}: since={since} notObserved={entry.start}..{entry.end} why={entry.why}")


if __name__ == "__main__":
    main()
