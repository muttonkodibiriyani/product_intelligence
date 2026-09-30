"""Exact monetary amounts.

Rules (PRC-03, DQ-03):
* amounts are ``Decimal``; floats are rejected because they cannot represent prices exactly;
* the original precision is preserved (3-decimal currencies such as KWD survive);
* arithmetic across currencies is an error, conversion happens only in a derived FX layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# ISO 4217 minor-unit exponents for the markets we cover (extend as markets are added).
CURRENCY_EXPONENTS: dict[str, int] = {
    "AED": 2,
    "BHD": 3,
    "EGP": 2,
    "EUR": 2,
    "GBP": 2,
    "JOD": 3,
    "KWD": 3,
    "OMR": 3,
    "QAR": 2,
    "SAR": 2,
    "USD": 2,
}


class CurrencyMismatchError(ValueError):
    """Raised when combining amounts in different currencies."""


@dataclass(frozen=True, slots=True)
class Money:
    """An exact amount in a single, known currency."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        raw: object = self.amount  # runtime guard: callers may bypass static types
        if not isinstance(raw, Decimal):
            msg = f"amount must be Decimal, got {type(raw).__name__}"
            raise TypeError(msg)
        if not self.amount.is_finite():
            msg = f"amount must be finite, got {self.amount}"
            raise ValueError(msg)
        if self.currency not in CURRENCY_EXPONENTS:
            msg = f"unsupported currency {self.currency!r}"
            raise ValueError(msg)

    @classmethod
    def of(cls, amount: str | int | Decimal, currency: str) -> Money:
        """Build from a string, int or Decimal. Floats are refused on purpose."""
        if isinstance(amount, float):
            msg = "floats are not accepted for money; pass a str or Decimal"
            raise TypeError(msg)
        if isinstance(amount, bool):
            msg = "bool is not a valid amount"
            raise TypeError(msg)
        try:
            value = Decimal(amount) if not isinstance(amount, Decimal) else amount
        except InvalidOperation as exc:
            msg = f"invalid amount {amount!r}"
            raise ValueError(msg) from exc
        return cls(value, currency.upper())

    @property
    def exponent(self) -> int:
        """Minor-unit exponent of the currency."""
        return CURRENCY_EXPONENTS[self.currency]

    def rounded(self) -> Money:
        """Round half-up to the currency's minor unit (for display, never for storage)."""
        quantum = Decimal(1).scaleb(-self.exponent)
        return Money(self.amount.quantize(quantum, rounding=ROUND_HALF_UP), self.currency)

    def _check(self, other: Money) -> None:
        if self.currency != other.currency:
            msg = f"cannot combine {self.currency} with {other.currency}"
            raise CurrencyMismatchError(msg)

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: int | Decimal) -> Money:
        if isinstance(factor, bool) or not isinstance(factor, int | Decimal):
            msg = "money can only be multiplied by int or Decimal"
            raise TypeError(msg)
        return Money(self.amount * factor, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._check(other)
        return self.amount < other.amount

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"
