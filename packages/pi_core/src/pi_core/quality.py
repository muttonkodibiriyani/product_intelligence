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
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from urllib.parse import urlparse

from pydantic import Field, field_validator

from pi_core.base import PiModel
from pi_core.enums import QualityStatus
from pi_core.listing import is_valid_gtin

#: Bumped whenever a rule or threshold changes; stored with every verdict.
GATE_VERSION = "dq-gate/1"

#: Default floor: a price below one unit of the market currency is a parse error, not a price
#: (§7.2 sanity). A market with a high-value currency sets its own via ``GateContext.min_price``.
MIN_PRICE = Decimal(1)
#: Price vs the listing's last accepted price: x10 or /10 is a decimal-point error (§7.2).
JUMP_FACTOR = Decimal(10)
#: Price vs category peers: more than this many standard deviations from their mean (§7.2).
#: When the peers all share one price (sigma 0), JUMP_FACTOR vs their median applies instead.
PEER_SIGMA = Decimal(5)
#: Fewest peers before the sigma rule applies (pi_metrics MIN_COHORT; below it, too noisy).
MIN_PEERS = 5
#: A discount deeper than this is quarantined (§7.2): current, promo or member price vs the
#: stated regular price, else (promo and member) vs the current price.
MAX_DISCOUNT = Decimal("0.90")
#: A run with this fraction fewer listings than the last good run is ``partial`` (§7.2).
MAX_COUNT_DROP = Decimal("0.20")

#: Markup by tag syntax, not any bracketed word ("<Me>", "<A Team>", "<P> Louise" are text):
#: a closing tag, a tag with name=value attributes, a self-closing tag, a known lower-case bare
#: tag, a comment or doctype, or an entity.
_HTML_TAGS = (
    "a|abbr|article|aside|b|blockquote|body|br|button|center|code|dd|del|div|dl|dt|em|figure"
    "|figcaption|font|footer|form|h[1-6]|head|header|hr|html|i|iframe|img|input|ins|label|li"
    "|link|main|mark|meta|nav|noscript|ol|option|p|path|picture|pre|s|script|section|select"
    "|small|source|span|strike|strong|style|sub|sup|svg|table|tbody|td|template|textarea|tfoot"
    "|th|thead|title|tr|tt|u|ul|video"
)
_HTML_RE = re.compile(
    "|".join(
        (
            r"</[a-zA-Z][a-zA-Z0-9]*\s*>",
            r"""<[a-zA-Z][a-zA-Z0-9-]*(?:\s+[a-zA-Z_:][\w:.-]*\s*=\s*(?:"[^"<>]*"|'[^'<>]*'|[^\s"'<>=]+))+\s*/?>""",
            r"<[a-zA-Z][a-zA-Z0-9]*\s*/>",
            rf"<(?:{_HTML_TAGS})>",
            r"(?i:<!--|<!doctype\b)",
            r"(?i:&(?:amp|nbsp|quot|lt|gt|#\d+|#x[0-9a-f]+);)",
        )
    )
)
#: UTF-8 read as Latin-1/CP-1252 ("Ã" before a continuation byte's Latin-1/CP-1252 form,
#: including C1 controls, so "SÃO" is text), the replacement character, and C0/C1 controls.
_CP1252_TAIL = "\x80-\xbf\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192\u02c6\u02dc\u2013\u2014\u2018-\u201e\u2020-\u2022\u2026\u2030\u2039\u203a\u20ac\u2122"  # noqa: E501
_JUNK_RE = re.compile(
    f"Ã[{_CP1252_TAIL}]|â€|Â[\\s\\xa0®©™]|\ufffd|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]"
)
#: Values allowed in ``Issue.detail`` besides numbers: ISO currency codes.
_ISO_CURRENCY_RE = re.compile(r"[A-Z]{3}")


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
    GTIN_INVALID = "gtin_invalid"
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
    #: Expected image hosts (compared case-insensitively); empty means any https host.
    image_hosts: frozenset[str] = frozenset()
    #: Lowest plausible price in ``market_currency`` (e.g. lower for KWD than for AED).
    min_price: Decimal = Field(default=MIN_PRICE, gt=0)

    @field_validator("image_hosts")
    @classmethod
    def _lower_hosts(cls, hosts: frozenset[str]) -> frozenset[str]:
        return frozenset(host.lower().rstrip(".") for host in hosts)


class ObservationFacts(PiModel):
    """The price fields of one offer observation about to be written."""

    price_current: Decimal | None = None
    price_regular_stated: Decimal | None = None
    price_promo: Decimal | None = None
    price_member: Decimal | None = None
    currency: str | None = None
    #: Null reasons per field (DQ-02), as stored in ``offer_observation.field_state``. A blank
    #: reason is no reason.
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
    #: A naive datetime is taken as UTC (as is ``as_of``), never compared raw.
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
        # Source text never reaches detail: the code is echoed only when it is ISO-shaped.
        shown = {"currency": obs.currency} if _ISO_CURRENCY_RE.fullmatch(obs.currency) else {}
        yield _issue(Check.CURRENCY_NOT_MARKET, Severity.QUARANTINE, "currency", **shown)
    if obs.price_current is None and not obs.field_state.get("price_current", "").strip():
        yield _issue(Check.PRICE_NULL_WITHOUT_REASON, Severity.QUARANTINE, "price_current")
    current, regular = obs.price_current, obs.price_regular_stated
    if current is not None and current > 0:
        yield from _implausible(current, obs, ctx.min_price)
    yield from _discounts(obs)
    if regular is not None and not ctx.was_price_displayed:
        yield _issue(Check.WAS_PRICE_PRESENT, Severity.WARNING, "price_regular_stated")


def _discounts(obs: ObservationFacts) -> Iterable[Issue]:
    """Regular below current, and any discount deeper than MAX_DISCOUNT (current, promo, member)."""
    current, regular = _positive(obs.price_current), _positive(obs.price_regular_stated)
    if current is not None and regular is not None and regular < current:
        yield _issue(
            Check.REGULAR_BELOW_CURRENT,
            Severity.QUARANTINE,
            "price_regular_stated",
            current=current,
            regular=regular,
        )
    offers = (
        ("price_current", current, regular),
        ("price_promo", _positive(obs.price_promo), regular or current),
        ("price_member", _positive(obs.price_member), regular or current),
    )
    for name, price, reference in offers:
        if price is not None and reference is not None and 1 - price / reference > MAX_DISCOUNT:
            yield _issue(
                Check.DISCOUNT_GT_90, Severity.QUARANTINE, name, price=price, reference=reference
            )


def _positive(value: Decimal | None) -> Decimal | None:
    return value if value is not None and value > 0 else None


def _implausible(current: Decimal, obs: ObservationFacts, floor: Decimal) -> Iterable[Issue]:
    if current < floor:
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
        if sigma > 0:
            far, rule = abs(current - mean) > PEER_SIGMA * sigma, "peer_sigma"
        else:  # every peer has the same price: no spread to measure, so use the x10 ratio
            median = statistics.median(obs.peer_prices)
            far = median > 0 and not median / JUMP_FACTOR < current < median * JUMP_FACTOR
            rule = "peer_ratio"
        if far:
            yield _issue(
                Check.PRICE_IMPLAUSIBLE,
                Severity.QUARANTINE,
                "price_current",
                rule=rule,
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
    gtin = (listing.gtin or "").strip()
    if not gtin:
        yield _issue(Check.GTIN_MISSING, Severity.INFO, "gtin")
    elif not is_valid_gtin(gtin):
        yield _issue(Check.GTIN_INVALID, Severity.WARNING, "gtin", length=len(gtin))


def _image_ok(url: str, hosts: frozenset[str]) -> bool:
    """An https URL on an expected host. The path needs no extension: CDNs often serve without."""
    try:
        parsed = urlparse(url.strip())
        host = parsed.hostname  # lower-cased by urlparse
    except ValueError:  # e.g. a malformed IPv6 host
        return False
    return (
        parsed.scheme.lower() == "https"
        and bool(host)
        and (not hosts or (host or "").rstrip(".") in hosts)
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
    empty = sum(fetched == 0 for fetched in run.fetched_by_context.values())
    if empty:  # a count: context keys come from the caller and stay out of detail
        issues.append(
            _issue(
                Check.CONTEXT_EMPTY,
                Severity.WARNING,
                "fetched_by_context",
                empty=empty,
                contexts=len(run.fetched_by_context),
            )
        )
    newest = run.newest_observed_at
    if newest is None or _utc(as_of) - _utc(newest) > max_age:
        issues.append(_issue(Check.STALE, Severity.WARNING, "observed_at"))
    return RunVerdict(partial=partial, issues=tuple(issues))


def _utc(moment: datetime) -> datetime:
    """Aware datetimes as they are; a naive one is taken as UTC."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def _issue(check: Check, severity: Severity, field: str | None, **detail: object) -> Issue:
    return Issue(
        check=check,
        severity=severity,
        field=field,
        detail={key: str(value) for key, value in detail.items()},
    )
