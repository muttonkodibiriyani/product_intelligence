"""The v3 byte gate: one number for the exporter and pi_api (docs/runbooks/pi-api-deploy.md §6).

A dataset body (decompressed, as pi_api parses it) at most ``V3_MAX_BYTES`` long is served on
the default memory budget. A larger one is served only on a measured admission record for its
exact bytes: ``admission_sha256`` of the body, listed in ``PI_API_ADMITTED`` by the deploy.
"""

from __future__ import annotations

import hashlib

#: Compact JSON bytes; see §6 for the fit it comes from.
V3_MAX_BYTES = 51_000_000


def admission_sha256(body: bytes) -> str:
    """The sha256 an admission record keys on: of the decompressed body pi_api parses, never
    of a gzip object or of the exporter's file (the publisher re-serialises it)."""
    return hashlib.sha256(body).hexdigest()
