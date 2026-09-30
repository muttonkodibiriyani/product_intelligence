"""Deterministic identifiers.

Ids are UUIDv5 values derived from a record's natural key, so re-parsing or replaying the same
input yields the same id and ingestion is logically exactly-once (DAT-09). The namespace is
fixed forever: changing it would re-key all history.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid5

#: Namespace for every pi_core id. Never change this value.
PI_NAMESPACE = UUID("6f1d3c2e-8a4b-5c7d-9e0f-1a2b3c4d5e6f")


def _encode(part: object) -> str:
    if part is None:
        return "-"
    if isinstance(part, datetime):
        if part.tzinfo is None:
            msg = "naive datetimes cannot be part of an id"
            raise ValueError(msg)
        text = part.astimezone(UTC).isoformat()
    else:
        text = str(part)
    # Length-prefixed so no choice of part contents can make two keys collide.
    return f"{len(text)}:{text}"


def stable_id(kind: str, *parts: object) -> UUID:
    """UUIDv5 over ``kind`` and ``parts``.

    ``None`` is encoded distinctly from ``""``. Datetimes must be timezone-aware and are encoded
    in UTC, so the same instant written in any offset produces the same id.
    """
    return uuid5(PI_NAMESPACE, "|".join([_encode(kind), *(_encode(p) for p in parts)]))
