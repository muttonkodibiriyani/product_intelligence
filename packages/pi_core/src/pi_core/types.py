"""Annotated field types shared by the pi_core models.

Each type encodes one storage rule so every model enforces it the same way:

* ``Amount``: exact ``Decimal`` that fits ``numeric(18,4)``; floats and bools are refused (PRC-03).
* ``PositiveAmount``: an ``Amount`` strictly above zero. Every price is ``None`` or positive;
  missing is never zero, it is ``None`` plus a ``field_state`` reason (DQ-02).
* ``UtcDatetime``: timezone-aware, normalised to UTC so ids and comparisons are stable (DAT-03).
* ``CurrencyCode``: an ISO 4217 code listed in ``CURRENCY_EXPONENTS``.
* ``Size``: exact positive ``Decimal`` pack size; floats refused, the unit is kept alongside.
* ``DbId``: a positive ``bigint`` identity id assigned by the database.
* ``ContentHash``: lowercase SHA-256 hex digest (DAT-04).
"""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, BeforeValidator, Field, StringConstraints

from pi_core.money import CURRENCY_EXPONENTS

#: ``numeric(18,4)``: at most 14 integer digits and 4 fractional digits.
AMOUNT_SCALE = 4
AMOUNT_INTEGER_DIGITS = 14
_AMOUNT_QUANTUM = Decimal(1).scaleb(-AMOUNT_SCALE)
_AMOUNT_LIMIT = Decimal(10) ** AMOUNT_INTEGER_DIGITS


def refuse_float(value: object) -> object:
    if isinstance(value, bool | float):
        msg = f"{type(value).__name__} is not accepted; pass a str, int or Decimal"
        raise TypeError(msg)
    return value


def _check_amount(value: Decimal) -> Decimal:
    # Bound first: quantize() on a value beyond the Decimal context precision would raise.
    if abs(value) >= _AMOUNT_LIMIT:
        msg = f"amount {value} does not fit numeric(18,{AMOUNT_SCALE})"
        raise ValueError(msg)
    if value != value.quantize(_AMOUNT_QUANTUM):
        msg = f"amount {value} has more than {AMOUNT_SCALE} decimal places"
        raise ValueError(msg)
    return value


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _check_currency(value: str) -> str:
    if value not in CURRENCY_EXPONENTS:
        msg = f"unsupported currency {value!r}"
        raise ValueError(msg)
    return value


# pydantic's Decimal already refuses NaN and infinity.
Amount = Annotated[Decimal, BeforeValidator(refuse_float), AfterValidator(_check_amount)]
PositiveAmount = Annotated[Amount, Field(gt=0)]
Size = Annotated[Decimal, BeforeValidator(refuse_float), Field(gt=0, allow_inf_nan=False)]
UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]
CurrencyCode = Annotated[str, AfterValidator(_check_currency)]
ContentHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
# Kept verbatim (never stripped) so source keys and names stay as published.
NonEmptyStr = Annotated[str, StringConstraints(pattern=r"\S")]
#: A database row id (``bigint GENERATED ALWAYS AS IDENTITY``).
DbId = Annotated[int, Field(ge=1)]


def content_hash_of(payload: bytes) -> str:
    """SHA-256 hex digest used for evidence, content and image versioning (DAT-04)."""
    return hashlib.sha256(payload).hexdigest()
