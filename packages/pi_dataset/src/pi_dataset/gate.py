"""pi_api's memory rule for the files it serves, and the v3 byte gate derived from it
(docs/runbooks/pi-api-deploy.md §6).

pi_api holds every served file parsed, and a refresh holds the refreshing file twice. The
measured fit: the largest file's refresh peak is ``FIT_INTERCEPT_MIB + REFRESH_MIB_PER_MB`` per
compact MB, and every other file is resident at ``RESIDENT_MIB_PER_MB``. The set fits when that
sum is at most ``SHARE`` of the instance memory. Refreshes run one at a time, so only the
largest file counts at the refresh rate, which is why the rule takes the largest file as the
one refreshing. A set that fails is served only on a measured admission record for its largest
body (``admission_sha256``, in ``PI_API_ADMITTED``).
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Mapping

#: Least squares over the beauty file scaled to 10, 30 and 61 MB (§6): refresh peak RSS in MiB.
FIT_INTERCEPT_MIB = 70.4
REFRESH_MIB_PER_MB = 31.48
#: A served file that is not refreshing (the beauty file's measured rate).
RESIDENT_MIB_PER_MB = 20.0
#: The share of the instance memory the files may use; the rest is exports and slack.
SHARE = 0.75
MB = 1_000_000
#: The memory pi_api assumes when ``PI_API_MEMORY_MIB`` is missing or unreadable: the smallest.
DEFAULT_MEMORY_MIB = 1024
#: Rule 2 at 3Gi: the files other than the largest, in total (600 MiB at the resident rate).
OTHERS_MAX_BYTES = 30_000_000
#: The exporter's gate: the largest file allowed at 3Gi beside ``OTHERS_MAX_BYTES`` of others
#: (step F's memory; ``largest_allowed(OTHERS_MAX_BYTES, 3072)``, pinned by a test).
V3_MAX_BYTES = 51_000_000


def peak_mib(sizes: Iterable[int]) -> float:
    """The fitted peak RSS of serving files of these decompressed, compact byte sizes while
    the largest one refreshes."""
    ordered = sorted(sizes, reverse=True)
    if not ordered:
        return FIT_INTERCEPT_MIB
    largest, others = ordered[0], sum(ordered[1:])
    return FIT_INTERCEPT_MIB + REFRESH_MIB_PER_MB * largest / MB + RESIDENT_MIB_PER_MB * others / MB


def limit_mib(memory_mib: int) -> float:
    return SHARE * memory_mib


def fits(sizes: Iterable[int], memory_mib: int) -> bool:
    return peak_mib(sizes) <= limit_mib(memory_mib)


def largest_allowed(others_bytes: int, memory_mib: int) -> int:
    """The largest file that fits beside ``others_bytes`` of other files, in whole MB."""
    room = limit_mib(memory_mib) - FIT_INTERCEPT_MIB - RESIDENT_MIB_PER_MB * others_bytes / MB
    return max(0, math.floor(room / REFRESH_MIB_PER_MB)) * MB


def refusal(
    files: Mapping[str, tuple[int, str]], admitted: Mapping[str, int], memory_mib: int
) -> str | None:
    """Why serving ``files`` (path: decompressed size and ``admission_sha256``) would break the
    rule at ``memory_mib``, or ``None`` when it does not. A set over the fit passes only when its
    largest body is admitted (``admitted``: sha256 to the other files' measured total in bytes)
    and the other files together are within that total."""
    sizes = {path: size for path, (size, _) in files.items()}
    if fits(sizes.values(), memory_mib):
        return None
    largest = max(sizes, key=lambda p: (sizes[p], p))
    size, sha = files[largest]
    others = sum(sizes.values()) - size
    peak = f"{peak_mib(sizes.values()):.0f} MiB is over {SHARE:.0%} of {memory_mib} MiB"
    bound = admitted.get(sha)
    if bound is None:
        return f"{peak}, and {largest} ({size} bytes, sha256={sha}) has no admission record"
    if others > bound:
        return f"{peak}, and the other files ({others} bytes) exceed {largest}'s admitted {bound}"
    return None


def admission_sha256(body: bytes) -> str:
    """The sha256 an admission record keys on: of the decompressed body pi_api parses, never
    of a gzip object or of the exporter's file (the publisher re-serialises it)."""
    return hashlib.sha256(body).hexdigest()
