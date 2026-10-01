"""Every registered ``VerticalProfile``, by ``<name>@<version>``."""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType

from pi_profiles.base import VerticalProfile
from pi_profiles.beauty import BEAUTY_V1

#: The ``variant.attributes_schema`` / ``meta.profile`` ref shape; migration 0004 checks the same
#: literal with PostgreSQL ``~``, so keep it engine-neutral: ASCII classes and bounded repeats only
#: (no ``\d``, ``\w``, lookarounds or flags, which differ between Python and PostgreSQL).
REF_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,62}@[1-9][0-9]{0,8}$")

PROFILES: Mapping[str, VerticalProfile] = MappingProxyType({p.ref: p for p in (BEAUTY_V1,)})


class UnknownProfileError(LookupError):
    """A ref that names no registered profile. Never falls back to another version."""


def get_profile(ref: str) -> VerticalProfile:
    """The profile registered as ``ref`` (``"beauty@1"``)."""
    if not REF_PATTERN.fullmatch(ref):
        msg = f"not a profile ref: {ref!r}"
        raise UnknownProfileError(msg)
    try:
        return PROFILES[ref]
    except KeyError:
        msg = f"no registered profile {ref}; registered: {sorted(PROFILES)}"
        raise UnknownProfileError(msg) from None
