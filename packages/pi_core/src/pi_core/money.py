"""Exact monetary amounts.

Rules (PRC-03, DQ-03):
* amounts are ``Decimal``; floats are rejected because they cannot represent prices exactly;
* the original precision is preserved (3-decimal currencies such as KWD survive);
* arithmetic across currencies is an error, conversion happens only in a derived FX layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# ISO 4217 minor-unit exponents for every active currency with a minor unit (List One;
# funds and precious metals without a minor unit are excluded). Mauritania (MRU) and Madagascar
# (MGA) are listed by ISO with 2 decimals although their subdivisions are not decimal.
# Snapshot of ISO 4217 List One as maintained by SIX, checked 2026-09-30: includes XCG (2025),
# ZWG (2024), SLE and VED; excludes the withdrawn ANG, CUC, HRK, SLL and ZWL. Re-check on amendment.
CURRENCY_EXPONENTS: dict[str, int] = {
    "AED": 2,
    "AFN": 2,
    "ALL": 2,
    "AMD": 2,
    "AOA": 2,
    "ARS": 2,
    "AUD": 2,
    "AWG": 2,
    "AZN": 2,
    "BAM": 2,
    "BBD": 2,
    "BDT": 2,
    "BGN": 2,
    "BHD": 3,
    "BIF": 0,
    "BMD": 2,
    "BND": 2,
    "BOB": 2,
    "BOV": 2,
    "BRL": 2,
    "BSD": 2,
    "BTN": 2,
    "BWP": 2,
    "BYN": 2,
    "BZD": 2,
    "CAD": 2,
    "CDF": 2,
    "CHE": 2,
    "CHF": 2,
    "CHW": 2,
    "CLF": 4,
    "CLP": 0,
    "CNY": 2,
    "COP": 2,
    "COU": 2,
    "CRC": 2,
    "CUP": 2,
    "CVE": 2,
    "CZK": 2,
    "DJF": 0,
    "DKK": 2,
    "DOP": 2,
    "DZD": 2,
    "EGP": 2,
    "ERN": 2,
    "ETB": 2,
    "EUR": 2,
    "FJD": 2,
    "FKP": 2,
    "GBP": 2,
    "GEL": 2,
    "GHS": 2,
    "GIP": 2,
    "GMD": 2,
    "GNF": 0,
    "GTQ": 2,
    "GYD": 2,
    "HKD": 2,
    "HNL": 2,
    "HTG": 2,
    "HUF": 2,
    "IDR": 2,
    "ILS": 2,
    "INR": 2,
    "IQD": 3,
    "IRR": 2,
    "ISK": 0,
    "JMD": 2,
    "JOD": 3,
    "JPY": 0,
    "KES": 2,
    "KGS": 2,
    "KHR": 2,
    "KMF": 0,
    "KPW": 2,
    "KRW": 0,
    "KWD": 3,
    "KYD": 2,
    "KZT": 2,
    "LAK": 2,
    "LBP": 2,
    "LKR": 2,
    "LRD": 2,
    "LSL": 2,
    "LYD": 3,
    "MAD": 2,
    "MDL": 2,
    "MGA": 2,
    "MKD": 2,
    "MMK": 2,
    "MNT": 2,
    "MOP": 2,
    "MRU": 2,
    "MUR": 2,
    "MVR": 2,
    "MWK": 2,
    "MXN": 2,
    "MXV": 2,
    "MYR": 2,
    "MZN": 2,
    "NAD": 2,
    "NGN": 2,
    "NIO": 2,
    "NOK": 2,
    "NPR": 2,
    "NZD": 2,
    "OMR": 3,
    "PAB": 2,
    "PEN": 2,
    "PGK": 2,
    "PHP": 2,
    "PKR": 2,
    "PLN": 2,
    "PYG": 0,
    "QAR": 2,
    "RON": 2,
    "RSD": 2,
    "RUB": 2,
    "RWF": 0,
    "SAR": 2,
    "SBD": 2,
    "SCR": 2,
    "SDG": 2,
    "SEK": 2,
    "SGD": 2,
    "SHP": 2,
    "SLE": 2,
    "SOS": 2,
    "SRD": 2,
    "SSP": 2,
    "STN": 2,
    "SVC": 2,
    "SYP": 2,
    "SZL": 2,
    "THB": 2,
    "TJS": 2,
    "TMT": 2,
    "TND": 3,
    "TOP": 2,
    "TRY": 2,
    "TTD": 2,
    "TWD": 2,
    "TZS": 2,
    "UAH": 2,
    "UGX": 0,
    "USD": 2,
    "USN": 2,
    "UYI": 0,
    "UYU": 2,
    "UYW": 4,
    "UZS": 2,
    "VED": 2,
    "VES": 2,
    "VND": 0,
    "VUV": 0,
    "WST": 2,
    "XAF": 0,
    "XCD": 2,
    "XCG": 2,
    "XOF": 0,
    "XPF": 0,
    "YER": 2,
    "ZAR": 2,
    "ZMW": 2,
    "ZWG": 2,
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
