"""Block and challenge detection: recorded, never solved (ADR-0006).

The marker list is a superset of ``sephora_snapshot.extract.CHALLENGE_MARKERS`` (a test enforces
it) plus the Akamai interstitial (``bm-verify``, ``/_sec/verify``), Amazon's robot check and
Distil/Imperva pages. A marker only counts in the first 20 KB of a non-200 response or of a short
(< 60 KB) 200 page, so an ordinary page that merely loads reCAPTCHA for a form is not a block.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

CHALLENGE_MARKERS: Final = (
    "/cdn-cgi/challenge-platform/",
    "Access Denied",
    "Reference&#32;&#35;",
    "captcha",
    "px-captcha",
    "_Incapsula_Resource",
    "bm-verify",
    "/_sec/verify",
    "validateCaptcha",
    "api-services-support@amazon.com",
    "Pardon Our Interruption",
)
HEAD_CHARS: Final = 20_000
SHORT_PAGE_CHARS: Final = 60_000
CHALLENGE: Final = "challenge"
BLOCKED: Final = "blocked"
RATE_LIMITED: Final = "rate_limited"


@dataclass(frozen=True)
class Verdict:
    kind: str  # challenge | blocked | rate_limited
    reason: str


def detect(status: int, text: str) -> Verdict | None:
    head = text[:HEAD_CHARS]
    for marker in CHALLENGE_MARKERS:
        if marker in head and (status != 200 or len(text) < SHORT_PAGE_CHARS):
            return Verdict(CHALLENGE, f"marker {marker!r} (http {status})")
    if status == 429:
        return Verdict(RATE_LIMITED, "http 429")
    if status in (401, 403):
        return Verdict(BLOCKED, f"http {status}")
    return None
