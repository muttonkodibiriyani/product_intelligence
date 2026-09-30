"""Deterministic logical keys.

Rows get ``bigint`` identity ids from the database; what makes ingestion logically exactly-once
is the logical key, a SHA-256 over a record's natural key (``offer_observation.idempotency_key``,
DAT-09). Re-parsing or replaying the same input yields the same key. The encoding is fixed
forever: changing it would re-key all history.
"""

import hashlib
from datetime import UTC, datetime


def _encode(part: object) -> str:
    if part is None:
        return "-"
    if isinstance(part, datetime):
        if part.tzinfo is None:
            msg = "naive datetimes cannot be part of a key"
            raise ValueError(msg)
        text = part.astimezone(UTC).isoformat()
    else:
        text = str(part)
    # Length-prefixed so no choice of part contents can make two keys collide.
    return f"{len(text)}:{text}"


def logical_key(kind: str, *parts: object) -> str:
    """Lowercase SHA-256 hex over ``kind`` and ``parts``.

    ``None`` is encoded distinctly from ``""``. Datetimes must be timezone-aware and are encoded
    in UTC, so the same instant written in any offset produces the same key.
    """
    encoded = "|".join([_encode(kind), *(_encode(p) for p in parts)])
    return hashlib.sha256(encoded.encode()).hexdigest()
