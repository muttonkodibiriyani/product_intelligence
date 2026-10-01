"""The data-quality gate (blueprint §7.2, DQ-05): pure checks, no I/O.

A loader (or a backfill) builds the plain facts below from what it is about to write, asks for a
verdict, and stores the verdict with the row. Nothing here reads or writes a database, and nothing
here names a source: per-source policy arrives as ``GateContext``.

Issue ``detail`` carries numbers and field names only, never source text: verdicts are logged and
exported next to the data.
"""

import re
import statistics
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from urllib.parse import urlparse

from pydantic import Field

from pi_core.base import PiModel
from pi_core.enums import QualityStatus

#: Bumped whenever a rule or threshold changes; stored with every verdict.
GATE_VERSION = "dq-gate/1"

#: A price below one unit of the market currency is a parse error, not a price (§7.2 sanity).
MIN_PRICE = Decimal(1)
#: Price vs the listing's last accepted price: x10 or /10 is a decimal-point error (§7.2).
JUMP_FACTOR = Decimal(10)
#: Price vs category peers: more than this many standard deviations from their mean (§7.2).
PEER_SIGMA = Decimal(5)
#: Fewest peers before the sigma rule applies (pi_metrics MIN_COHORT; below it, too noisy).
MIN_PEERS = 5
#: A discount deeper than this is quarantined (§7.2).
MAX_DISCOUNT = Decimal("0.90")
#: A run with this fraction fewer listings than the last good run is ``partial`` (§7.2).
MAX_COUNT_DROP = Decimal("0.20")

_HTML_RE = re.compile(
    r"<[a-zA-Z/!][^>]{0,200}>|&(?:amp|nbsp|quot|lt|gt|#\d+|#x[0-9a-f]+);", re.IGNORECASE
)
#: UTF-8 read as Latin-1/CP-1252, the replacement character, and control characters.
_JUNK_RE = re.compile("Ã.|â€|Â[\\s\\xa0®©™]|\ufffd|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_IMAGE_PATH_RE = re.compile(r"\.(jpe?g|png|webp|avif|gif)$", re.IGNORECASE)


class Severity(StrEnum):
    """How much one issue weighs. ``INFO`` is counted but never changes the status."""

    INFO = "info"
    WARNING = "warning"
    QUARANTINE = "quarantine"


class Check(StrEnum):
    """Every check the gate can raise. Codes are stable: they are stored with verdicts."""

    PRICE_NONPOSITIVE = "price_nonpositive"
    PRICE_IMPLAUSIBLE = "price_implausible"
    PRICE_WITHOUT_CURRENCY = "price_without_currency"
    CURRENCY_NOT_MARKET = "currency_not_market"
    PRICE_NULL_WITHOUT_REASON = "price_null_without_reason"
    REGULAR_BELOW_CURRENT = "regular_below_current"
    DISCOUNT_GT_90 = "discount_gt_90"
    WAS_PRICE_PRESENT = "was_price_present"
    PRICE_MISSING = "price_missing"
    SIZE_UNPARSED = "size_unparsed"
    SIZE_MISSING = "size_missing"
    IMAGE_URL_BAD = "image_url_bad"
    TEXT_HTML = "text_html"
    TEXT_JUNK = "text_junk"
    GTIN_MISSING = "gtin_missing"
    DUPLICATE_KEY = "duplicate_key"
    COUNT_DROP = "count_drop"
    CONTEXT_EMPTY = "context_empty"
    STALE = "stale"


class Issue(PiModel):
    """One failed check: which field, how bad, and the numbers behind it (no source text)."""

    check: Check
    severity: Severity
    field: str | None = None
    detail: dict[str, str] = Field(default_factory=dict)


class Verdict(PiModel):
    """The gate's outcome for one record; ``status`` is the worst issue, else accepted."""

    status: QualityStatus
    issues: tuple[Issue, ...] = ()
    gate_version: str = GATE_VERSION


class GateContext(PiModel):
    """Per-source, per-market policy. The caller supplies it; the gate never guesses it."""

    market_currency: str = Field(min_length=3, max_length=3)
    #: False where the retailer's stated regular ("was") price is never displayed (a warning
    #: when present; the export strips it).
    was_price_displayed: bool = True
    #: Expected image hosts; empty means any https host.
    image_hosts: frozenset[str] = frozenset()


class ObservationFacts(PiModel):
    """The price fields of one offer observation about to be written."""

    price_current: Decimal | None = None
    price_regular_stated: Decimal | None = None
    price_promo: Decimal | None = None
    price_member: Decimal | None = None
    currency: str | None = None
    #: Null reasons per field (DQ-02), as stored in ``offer_observation.field_state``.
    field_state: dict[str, str] = Field(default_factory=dict)
    #: The listing's last accepted ``price_current`` in the same currency, if any.
    last_accepted_price: Decimal | None = None
    #: Accepted current prices of comparable listings (same category, same currency).
    peer_prices: tuple[Decimal, ...] = ()


class ListingFacts(PiModel):
    """The descriptive fields of one listing about to be written."""

    name: str | None = None
    brand: str | None = None
    #: The size as published, and the amount the caller parsed from it (None when it could not).
    size_label: str | None = None
    size_value: Decimal | None = None
    #: "size" when the listing is a size variant, "shade" for a shade variant, else None.
    variant_kind: str | None = None
    image_urls: tuple[str, ...] = ()
    gtin: str | None = None
    #: Whether the run holds any observation with a price for this listing; None when unknown.
    has_price_observation: bool | None = None


class RunFacts(PiModel):
    """Counts of one crawl run, for the run-level checks."""

    listings: int = Field(ge=0)
    #: Listings in the last run of the same scope that was not partial; None for a first run.
    last_good_listings: int | None = Field(default=None, ge=0)
    #: Rows fetched per collection context (e.g. locale), for empty-context detection.
    fetched_by_context: dict[str, int] = Field(default_factory=dict)
    newest_observed_at: datetime | None = None


class RunVerdict(PiModel):
    """Run-level outcome: issues, and whether the run must be recorded as ``partial``."""

    partial: bool
    issues: tuple[Issue, ...] = ()
    gate_version: str = GATE_VERSION


def verdict(issues: Iterable[Issue]) -> Verdict:
    """The verdict for these issues: quarantined beats warning beats accepted; INFO never counts."""
    found = tuple(issues)
    severities = {issue.severity for issue in found}
    if Severity.QUARANTINE in severities:
        status = QualityStatus.QUARANTINED
    elif Severity.WARNING in severities:
        status = QualityStatus.WARNING
    else:
        status = QualityStatus.ACCEPTED
    return Verdict(status=status, issues=found)


def check_observation(obs: ObservationFacts, ctx: GateContext) -> Verdict:
    """Price sanity, currency, discount and was-price checks for one observation."""
    return verdict(_observation_issues(obs, ctx))


def _observation_issues(obs: ObservationFacts, ctx: GateContext) -> Iterable[Issue]:
    prices = {
        "price_current": obs.price_current,
        "price_regular_stated": obs.price_regular_stated,
        "price_promo": obs.price_promo,
        "price_member": obs.price_member,
    }
    for name, value in prices.items():
        if value is not None and value <= 0:
            yield _issue(Check.PRICE_NONPOSITIVE, Severity.QUARANTINE, name, value=value)
    priced = [name for name, value in prices.items() if value is not None]
    if priced and obs.currency is None:
        yield _issue(Check.PRICE_WITHOUT_CURRENCY, Severity.QUARANTINE, "currency")
    if obs.currency is not None and obs.currency != ctx.market_currency:
        yield _issue(
            Check.CURRENCY_NOT_MARKET,
            Severity.QUARANTINE,
            "currency",
            currency=obs.currency,
            expected=ctx.market_currency,
        )
    if obs.price_current is None and "price_current" not in obs.field_state:
        yield _issue(Check.PRICE_NULL_WITHOUT_REASON, Severity.QUARANTINE, "price_current")
    current, regular = obs.price_current, obs.price_regular_stated
    if current is not None and current > 0:
        yield from _implausible(current, obs)
        if regular is not None and regular > 0:
            if regular < current:
                yield _issue(
                    Check.REGULAR_BELOW_CURRENT,
                    Severity.QUARANTINE,
                    "price_regular_stated",
                    current=current,
                    regular=regular,
                )
            elif 1 - current / regular > MAX_DISCOUNT:
                yield _issue(
                    Check.DISCOUNT_GT_90,
                    Severity.QUARANTINE,
                    "price_current",
                    current=current,
                    regular=regular,
                )
    if regular is not None and not ctx.was_price_displayed:
        yield _issue(Check.WAS_PRICE_PRESENT, Severity.WARNING, "price_regular_stated")


def _implausible(current: Decimal, obs: ObservationFacts) -> Iterable[Issue]:
    if current < MIN_PRICE:
        yield _issue(
            Check.PRICE_IMPLAUSIBLE,
            Severity.QUARANTINE,
            "price_current",
            rule="below_min",
            value=current,
        )
        return
    last = obs.last_accepted_price
    if last is not None and last > 0 and not last / JUMP_FACTOR < current < last * JUMP_FACTOR:
        yield _issue(
            Check.PRICE_IMPLAUSIBLE,
            Severity.QUARANTINE,
            "price_current",
            rule="jump_x10",
            value=current,
            last=last,
        )
        return
    if len(obs.peer_prices) >= MIN_PEERS:
        mean = statistics.mean(obs.peer_prices)
        sigma = statistics.pstdev(obs.peer_prices)
        if sigma > 0 and abs(current - mean) > PEER_SIGMA * sigma:
            yield _issue(
                Check.PRICE_IMPLAUSIBLE,
                Severity.QUARANTINE,
                "price_current",
                rule="peer_sigma",
                value=current,
                peers=len(obs.peer_prices),
            )


def check_listing(listing: ListingFacts, ctx: GateContext) -> Verdict:
    """Missing price, size, image, text and GTIN checks for one listing."""
    return verdict(_listing_issues(listing, ctx))


def _listing_issues(listing: ListingFacts, ctx: GateContext) -> Iterable[Issue]:
    if listing.has_price_observation is False:
        # §7.2 "missing critical field": accepted with a reason, excluded from price metrics.
        yield _issue(Check.PRICE_MISSING, Severity.WARNING, "price_current")
    if listing.size_label and listing.size_value is None:
        yield _issue(Check.SIZE_UNPARSED, Severity.WARNING, "size")
    if not listing.size_label and listing.variant_kind == "size":
        yield _issue(Check.SIZE_MISSING, Severity.WARNING, "size")
    bad = sum(not _image_ok(url, ctx.image_hosts) for url in listing.image_urls)
    if bad:
        yield _issue(Check.IMAGE_URL_BAD, Severity.WARNING, "images", bad=bad)
    for name, text in (("name", listing.name), ("brand", listing.brand)):
        if not text:
            continue
        if _HTML_RE.search(text):
            yield _issue(Check.TEXT_HTML, Severity.QUARANTINE, name)
        elif _JUNK_RE.search(text):
            yield _issue(Check.TEXT_JUNK, Severity.WARNING, name)
    if not listing.gtin:
        yield _issue(Check.GTIN_MISSING, Severity.INFO, "gtin")


def _image_ok(url: str, hosts: frozenset[str]) -> bool:
    parsed = urlparse(url.strip())
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and bool(_IMAGE_PATH_RE.search(parsed.path))
        and (not hosts or parsed.hostname in hosts)
    )


def duplicate_keys(rows: Iterable[tuple[str, str]]) -> frozenset[str]:
    """Keys seen more than once in a run with different content (``(key, content_hash)`` rows).

    The same key with the same content is a harmless re-fetch, not a duplicate.
    """
    hashes: defaultdict[str, set[str]] = defaultdict(set)
    for key, content_hash in rows:
        hashes[key].add(content_hash)
    return frozenset(key for key, seen in hashes.items() if len(seen) > 1)


def duplicate_issue(key_count: int) -> Issue:
    """The quarantine issue for a listing whose key is in ``duplicate_keys``."""
    return _issue(Check.DUPLICATE_KEY, Severity.QUARANTINE, "source_listing_key", rows=key_count)


def check_run(run: RunFacts, *, as_of: datetime, max_age: timedelta) -> RunVerdict:
    """Count drop, empty contexts and freshness for one run. ``as_of`` is a label, not a clock."""
    issues: list[Issue] = []
    partial = False
    last = run.last_good_listings
    if last and Decimal(last - run.listings) / last > MAX_COUNT_DROP:
        partial = True
        issues.append(
            _issue(Check.COUNT_DROP, Severity.WARNING, None, listings=run.listings, last=last)
        )
    for context, fetched in sorted(run.fetched_by_context.items()):
        if fetched == 0:
            issues.append(_issue(Check.CONTEXT_EMPTY, Severity.WARNING, None, context=context))
    newest = run.newest_observed_at
    if newest is None or as_of - newest > max_age:
        issues.append(_issue(Check.STALE, Severity.WARNING, "observed_at"))
    return RunVerdict(partial=partial, issues=tuple(issues))


def _issue(check: Check, severity: Severity, field: str | None, **detail: object) -> Issue:
    return Issue(
        check=check,
        severity=severity,
        field=field,
        detail={key: str(value) for key, value in detail.items()},
    )
