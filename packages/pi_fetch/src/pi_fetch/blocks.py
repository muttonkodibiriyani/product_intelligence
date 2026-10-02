"""Block and challenge detection. It classifies only: nothing here solves, waits out or retries a
challenge, and no cookie value is ever kept (only cookie *names* are read as vendor hints).

Two kinds of signal:

* **challenge markers** (a challenge page, or a vendor header that states a challenge): a block
  whatever the status, including a 200 challenge page;
* **vendor hints** (server header, vendor cookie names): name the vendor of a 401/403/429/503,
  but never make a 2xx page a block on their own, since CDNs also serve ordinary pages.

Every verdict has a ``BlockKind``. A challenge marker gives CHALLENGE whatever the status, a 429
included. Any other 429 is RATE_LIMITED, keeping the vendor for audit. A 401/403 (GENERIC with no
vendor signal), a vendor-hinted 503 and an empty 2xx text payload are BLOCKED. Only CHALLENGE and
BLOCKED mark a source blocked (``BlockVerdict.marks_source_blocked``). Other failures (404, 500,
…) get no verdict; ``FetchResult.ok`` is false for them anyway.
"""

from collections.abc import Iterable

from pi_fetch.types import (
    TOO_MANY_REQUESTS,
    BlockKind,
    BlockVendor,
    BlockVerdict,
    FetchResult,
    PayloadKind,
)

#: Only the head of a body is scanned; challenge pages are small.
SCAN_BYTES = 256 * 1024
BLOCK_STATUSES = frozenset({401, 403, 429, 503})
GENERIC_BLOCK_STATUSES = frozenset({401, 403, 429})

_BODY_MARKERS: tuple[tuple[BlockVendor, tuple[bytes, ...]], ...] = (
    (
        BlockVendor.CLOUDFLARE,
        (
            b"cf-chl-",
            b"/cdn-cgi/challenge-platform/",
            b"cf_chl_opt",
            b"attention required! | cloudflare",
        ),
    ),
    (
        BlockVendor.AKAMAI,
        (b"sec-if-cpt-container", b"/_sec/cp_challenge/", b"bm-verify", b"errors.edgesuite.net"),
    ),
    (
        BlockVendor.PERIMETERX,
        (b"px-captcha", b"_pxcaptcha", b"captcha.px-cdn.net", b"_pxappid"),
    ),
    (
        BlockVendor.DATADOME,
        (b"captcha-delivery.com", b"datadome captcha", b"dd={'rt':"),
    ),
)

_COOKIE_HINTS: tuple[tuple[BlockVendor, tuple[str, ...]], ...] = (
    (BlockVendor.CLOUDFLARE, ("__cf_bm", "cf_clearance")),
    (BlockVendor.AKAMAI, ("_abck", "ak_bmsc", "bm_sz")),
    (BlockVendor.PERIMETERX, ("_px", "_pxhd", "_px2", "_px3")),
    (BlockVendor.DATADOME, ("datadome",)),
)


def _header(headers: Iterable[tuple[str, str]], name: str) -> list[str]:
    return [v for k, v in headers if k.lower() == name]


def _cookie_names(headers: Iterable[tuple[str, str]]) -> set[str]:
    names = set()
    for value in _header(headers, "set-cookie"):
        name, _, _ = value.partition("=")
        names.add(name.strip().lower())
    return names


def _challenge_marker(
    headers: list[tuple[str, str]], head: bytes
) -> tuple[BlockVendor, str] | None:
    if any(v.strip().lower() == "challenge" for v in _header(headers, "cf-mitigated")):
        return BlockVendor.CLOUDFLARE, "cf-mitigated: challenge header"
    if _header(headers, "x-datadome") and any(
        "captcha-delivery" in v for v in _header(headers, "x-dd-b") + _header(headers, "location")
    ):
        return BlockVendor.DATADOME, "datadome captcha redirect"
    for vendor, markers in _BODY_MARKERS:
        for marker in markers:
            if marker in head:
                return vendor, f"challenge page marker {marker.decode()!r}"
    return None


def _vendor_hint(headers: list[tuple[str, str]]) -> tuple[BlockVendor, str] | None:
    server = " ".join(_header(headers, "server")).lower()
    if "cloudflare" in server or _header(headers, "cf-ray"):
        return BlockVendor.CLOUDFLARE, "cloudflare edge"
    if "akamaighost" in server:
        return BlockVendor.AKAMAI, "akamai edge"
    if "datadome" in server or _header(headers, "x-datadome"):
        return BlockVendor.DATADOME, "datadome header"
    cookies = _cookie_names(headers)
    for vendor, names in _COOKIE_HINTS:
        hit = sorted(cookies.intersection(names))
        if hit:
            return vendor, f"{vendor.value} cookie {hit[0]}"
    return None


def detect_response(
    status: int,
    headers: Iterable[tuple[str, str]],
    body: bytes,
    kind: PayloadKind,
) -> BlockVerdict | None:
    """Classify a raw response. ``headers`` are the unredacted pairs (cookie names are read)."""
    pairs = list(headers)
    head = body[:SCAN_BYTES].lower()
    marker = _challenge_marker(pairs, head)
    if marker is not None:
        vendor, reason = marker
        return BlockVerdict(
            kind=BlockKind.CHALLENGE, vendor=vendor, reason=reason, http_status=status
        )
    refusal = BlockKind.RATE_LIMITED if status == TOO_MANY_REQUESTS else BlockKind.BLOCKED
    if status in BLOCK_STATUSES:
        hint = _vendor_hint(pairs)
        if hint is not None:
            vendor, reason = hint
            return BlockVerdict(
                kind=refusal, vendor=vendor, reason=f"http {status}, {reason}", http_status=status
            )
        if status in GENERIC_BLOCK_STATUSES:
            return BlockVerdict(
                kind=refusal,
                vendor=BlockVendor.GENERIC,
                reason=f"http {status}",
                http_status=status,
            )
    if 200 <= status < 300 and kind is not PayloadKind.IMAGE and not body.strip():
        return BlockVerdict(
            kind=BlockKind.BLOCKED,
            vendor=BlockVendor.GENERIC,
            reason="empty payload",
            http_status=status,
        )
    return None


def detect(result: FetchResult) -> BlockVerdict | None:
    """Re-classify a stored result (headers already redacted, so no cookie-name hints)."""
    return detect_response(
        result.http_status, result.headers.items(), result.body, result.request.kind
    )
