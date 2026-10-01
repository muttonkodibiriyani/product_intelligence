"""Display tidy for the exported names and brands.

Owner ruling (2026-10-01): this is display only. pi_db keeps every name and brand exactly as the
retailer published it; only the exported dataset shows the tidied text. It applies to Sephora
rows only: any other retailer's rows (Ulta) pass through untouched and never influence Sephora's
display. Nothing is guessed:

- whitespace runs (tabs, newlines, no-break spaces) become one space, zero-width characters go,
  and the ends are trimmed;
- one brand spelt in different letter cases (``SHU UEMURA`` / ``Shu Uemura``) is shown in one
  spelling: the one most rows use, then the one that is not all capitals, then the first in order
  (so an exact tie between ``NARS`` and ``Nars`` shows ``Nars``);
- a name that repeats its brand at the start (``Brand Product``, ``Brand - Product``) is shown
  without it, because ``Product.brand`` already says it. The name is kept whole when the brand
  runs on into a longer word (``Dior`` / ``Diorshow``), or when what is left names nothing: empty,
  only a size (``Dior 10ml``) or only a bracketed note (``Dior (Limited)``);
- all-capital names are kept as published (changing case would be a guess).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import replace

from scripts.demo_export.export import ListingRow

WHITESPACE = re.compile(r"\s+")
ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")
#: What may separate a repeated brand from the rest of the name.
BRAND_SEPARATORS = " -\u2013\u2014:|,"
#: Parts of a name that do not name a product on their own: bracketed notes and sizes.
BRACKETED = re.compile(r"\([^)]*\)|\[[^\]]*\]")
SIZE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:ml|l|g|kg|mg|oz|fl\.?\s?oz|pcs?|x)\b", re.IGNORECASE)
#: A word: two or more letters in any script.
WORD = re.compile(r"[^\W\d_]{2,}")
#: The retailer whose display is tidied (v1 slot); other retailers' rows are passed through.
TIDIED_RETAILER = "s"


def clean_text(value: str) -> str:
    return WHITESPACE.sub(" ", ZERO_WIDTH.sub("", value)).strip()


def brand_spellings(brands: Iterable[str]) -> dict[str, str]:
    """casefolded brand -> the one spelling to show."""
    counts = Counter(clean_text(brand) for brand in brands)
    spellings: dict[str, list[str]] = {}
    for spelling in counts:
        spellings.setdefault(spelling.casefold(), []).append(spelling)
    return {
        key: min(forms, key=lambda form: (-counts[form], form.isupper(), form))
        for key, forms in spellings.items()
    }


def display_name(name: str, brand: str) -> str:
    """The cleaned name, without a leading repeat of ``brand``."""
    cleaned, brand = clean_text(name), clean_text(brand)
    head, rest = cleaned[: len(brand)], cleaned[len(brand) :]
    if not brand or head.casefold() != brand.casefold() or not rest:
        return cleaned
    if rest[0] not in BRAND_SEPARATORS:
        return cleaned
    rest = rest.lstrip(BRAND_SEPARATORS).strip()
    if not WORD.search(SIZE.sub(" ", BRACKETED.sub(" ", rest))):
        return cleaned
    return rest


def tidy_rows(rows: Sequence[ListingRow]) -> list[ListingRow]:
    """The rows with Sephora's display names and brands (a copy; the input rows are not changed).
    Brand spellings are chosen from Sephora rows only; other retailers' rows are returned as-is."""
    spellings = brand_spellings(row.brand for row in rows if row.retailer == TIDIED_RETAILER)
    tidied = []
    for row in rows:
        if row.retailer != TIDIED_RETAILER:
            tidied.append(row)
            continue
        brand = spellings[clean_text(row.brand).casefold()]
        tidied.append(replace(row, brand=brand, name=display_name(row.name, brand)))
    return tidied
