"""Normalisers for first-pass matching. Pure functions: same input, same output.

Nothing is inferred beyond the text: a size, shade or concentration that is not written in
the record stays ``None``.
"""

import ast
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from importlib import resources
from types import MappingProxyType

#: Trailing words dropped from a brand when something remains, e.g. "Nars Cosmetics".
_BRAND_SUFFIXES = ("cosmetics", "makeup", "skincare", "paris", "london", "new york")

_ML_PER_UNIT = {
    "ml": Decimal(1),
    "l": Decimal(1000),
    "cl": Decimal(10),
    "floz": Decimal("29.5735"),
}
_G_PER_UNIT = {"g": Decimal(1), "gr": Decimal(1), "kg": Decimal(1000), "mg": Decimal("0.001")}
_OZ_TO_G = Decimal("28.3495")

_SIZE_RE = re.compile(
    r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(fl\.?\s*oz|ml|cl|l|kg|mg|gr|g|oz)(?![a-z])", re.IGNORECASE
)
_SHADE_CODE_RE = re.compile(r"^(?:no\s*)?([a-z]{0,3}\d+(?:\.\d+)?(?:[a-z]{1,2}\d*)?)\b")
_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?")
_BARE_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
#: List text longer than this is not parsed at all (it is never a size or shade label).
MAX_LIST_TEXT = 512
#: A leading "[...]" with no quotes, commas or nested brackets: a label unless it is a literal.
_LABEL_RE = re.compile(r"\[[^\[\]'\",]*\]")
#: Decimal numbers stay one token ("2.5"), everything else splits on non-alphanumerics.
_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)+|[a-z0-9]+")

_STOPWORDS = frozenset({"the", "and", "a", "an", "of", "for", "with", "de", "la", "le", "by"})


class Concentration(StrEnum):
    """Fragrance concentration (blueprint §8.4: EDP != EDT != parfum)."""

    PARFUM = "parfum"
    EDP = "edp"
    EDT = "edt"
    EDC = "edc"
    BODY_MIST = "body_mist"


class ItemKind(StrEnum):
    """Minis, refills and sets are separate classes (blueprint §8.4)."""

    REGULAR = "regular"
    MINI = "mini"
    REFILL = "refill"
    SET = "set"


_CONCENTRATION_PATTERNS: tuple[tuple[Concentration, re.Pattern[str]], ...] = (
    (Concentration.EDP, re.compile(r"\b(eau de parfum|edp)\b")),
    (Concentration.EDT, re.compile(r"\b(eau de toilette|edt)\b")),
    (Concentration.EDC, re.compile(r"\b(eau de cologne|edc)\b")),
    (Concentration.BODY_MIST, re.compile(r"\b(body mist|hair mist|hair and body mist)\b")),
    (Concentration.PARFUM, re.compile(r"\b(parfum|extrait|perfume)\b")),
)
_KIND_PATTERNS: tuple[tuple[ItemKind, re.Pattern[str]], ...] = (
    (ItemKind.SET, re.compile(r"\b(set|kit|gift set|coffret|duo|trio|bundle|collection)\b")),
    (ItemKind.REFILL, re.compile(r"\b(refill|recharge)\b")),
    (ItemKind.MINI, re.compile(r"\b(mini|travel size|travel|deluxe sample)\b")),
)
#: Words that describe the size, concentration or kind: removed from name tokens so the name
#: comparison is about the product, and those attributes are compared on their own.
_ATTRIBUTE_WORDS = frozenset(
    {
        "eau", "parfum", "toilette", "cologne", "edp", "edt", "edc", "extrait", "perfume",
        "ml", "cl", "l", "g", "gr", "kg", "mg", "oz", "fl", "spray", "vaporisateur",
        "mini", "travel", "size", "refill", "recharge", "set", "kit", "gift",
    }
)  # fmt: skip


def fold(text: str) -> str:
    """Lower-case, strip diacritics, ``&`` to ``and``, punctuation to spaces, spaces collapsed."""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in decomposed if not unicodedata.combining(c))
    lowered = ascii_text.lower().replace("&", " and ").replace("+", " and ")
    lowered = re.sub("['\u2019`]", "", lowered)  # "Kiehl's" -> "kiehls", "L'Oréal" -> "loreal"
    return " ".join(t.replace(",", ".") for t in _TOKEN_RE.findall(lowered))


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """``json.loads`` hook: a repeated key is an error, not "the last one wins"."""
    keys = [key for key, _ in pairs]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        msg = f"brand aliases: canonical brand listed twice: {duplicates}"
        raise ValueError(msg)
    return dict(pairs)


def parse_brand_aliases(raw: str) -> dict[str, str]:
    """``brand_aliases.json`` (``{canonical: [alias, ...]}``, the shape of ``brand.aliases``)
    inverted to ``alias -> canonical``. Every spelling must already be ``fold``ed.

    Raises ``ValueError`` on any other shape: a repeated canonical, a value that isn't a list of
    strings (a bare string would otherwise become one alias per character), a repeated alias,
    an alias that is itself canonical, or an unfolded spelling.
    """
    data = json.loads(raw, object_pairs_hook=_unique_keys)
    if not isinstance(data, dict):
        msg = "brand aliases: expected an object {canonical: [alias, ...]}"
        raise ValueError(msg)
    aliases: dict[str, str] = {}
    for canonical, spellings in data.items():
        if not isinstance(spellings, list) or not all(isinstance(a, str) for a in spellings):
            msg = f"brand aliases: {canonical!r} must map to a list of strings"
            raise ValueError(msg)
        for alias in spellings:
            if alias in aliases or alias in data:
                msg = f"brand alias {alias!r} is listed twice or is itself a canonical brand"
                raise ValueError(msg)
            if fold(alias) != alias or fold(canonical) != canonical:
                msg = f"brand alias {alias!r} -> {canonical!r} is not folded"
                raise ValueError(msg)
            aliases[alias] = canonical
    return aliases


#: Brand spellings that differ between retailers, keyed by the normalised spelling. Data, not
#: code (ADR-0007 §4): edit ``brand_aliases.json``, which a reviewer reads as a plain list.
BRAND_ALIASES: Mapping[str, str] = MappingProxyType(
    parse_brand_aliases(
        resources.files("pi_match").joinpath("brand_aliases.json").read_text(encoding="utf-8")
    )
)


def normalise_brand(brand: str) -> str:
    """A brand key comparable across retailers ("Estée Lauder" == "ESTEE LAUDER")."""
    key = fold(brand)
    key = BRAND_ALIASES.get(key, key)
    for suffix in _BRAND_SUFFIXES:
        if key.endswith(f" {suffix}"):
            key = key.removesuffix(f" {suffix}")
            break
    return BRAND_ALIASES.get(key, key)


@dataclass(frozen=True, slots=True)
class Size:
    """A size in a base unit: ``ml`` for volume, ``g`` for mass."""

    amount: Decimal
    unit: str  # "ml" or "g"

    def same_as(self, other: "Size", tolerance: Decimal = Decimal("0.03")) -> bool:
        """Equal unit and amounts within ``tolerance`` (3%: 30 ml == 1 fl oz)."""
        if self.unit != other.unit:
            return False
        big = max(self.amount, other.amount)
        return big == 0 or abs(self.amount - other.amount) / big <= tolerance


def is_listed(value: str | Sequence[str] | None) -> bool:
    """True for a list: a JSON array, or text that starts like one ("['100'] ['ML']").

    A bracketed label that is not a literal ("[Limited] 50ml") is plain text, not a list.
    """
    if value is None:
        return False
    if not isinstance(value, str):
        return True
    text = value.lstrip()
    label = _LABEL_RE.match(text)
    return text.startswith("[") and (label is None or _literal(label.group())[0])


def list_groups(value: str | Sequence[str]) -> tuple[tuple[str, ...], ...] | None:
    """The flat lists in ``value``: a JSON array is one list; text may hold several side by side.

    ``"['50', '90'] ['ML']"`` is two lists. Each list in text is parsed with ``json``, else with
    ``ast.literal_eval`` (literals only, never code). Only flat lists of strings or numbers count.
    Text longer than ``MAX_LIST_TEXT``, any parse failure and any other shape give None.
    """
    if not isinstance(value, str):
        items = _flat_items(list(value))
        return None if items is None else (items,)
    rest = value.strip()
    if not rest.startswith("[") or len(rest) > MAX_LIST_TEXT:
        return None
    groups: list[tuple[str, ...]] = []
    while rest:
        parsed = _first_list(rest)
        if parsed is None:
            return None
        items, rest = parsed
        groups.append(items)
        rest = rest.lstrip()
    return tuple(groups)


def _first_list(text: str) -> tuple[tuple[str, ...], str] | None:
    """The list that ``text`` starts with, and the text after it; None when there is none."""
    if not text.startswith("["):
        return None
    for end, char in enumerate(text):
        if char != "]":
            continue
        found, value = _literal(text[: end + 1])
        if found:  # the first "]" that closes a valid literal ends the list
            items = _flat_items(value)
            return None if items is None else (items, text[end + 1 :])
    return None


def _literal(text: str) -> tuple[bool, object]:
    try:
        return True, json.loads(text)
    except ValueError:
        pass
    try:
        return True, ast.literal_eval(text)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False, None


def _flat_items(value: object) -> tuple[str, ...] | None:
    """The non-empty items of a flat list of strings or numbers, as text; else None."""
    if not isinstance(value, list):
        return None
    items: list[str] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, str | int | float | Decimal):
            return None
        text = str(item).strip()
        if text:
            items.append(text)
    return tuple(items)


def parse_size(text: str | Sequence[str] | None) -> Size | None:
    """The first size written in ``text`` ("50ml", "1.7 fl oz", "3,5 g"), else None.

    A list (see ``list_groups``) gives a size only when it holds exactly one: one distinct item
    (``['100 ml']``), one number then its unit (``[50, "ml"]``), or one distinct number beside one
    distinct unit (``['100'] ['ML']``).
    Several sizes or units (``['50', '90'] ['ML']``) are ambiguous and give None, never the first.
    """
    if not text:
        return None
    if isinstance(text, str) and not is_listed(text):
        match = _SIZE_RE.search(text)
        return None if match is None else _size(match)
    groups = list_groups(text)
    return None if groups is None else _size_from_groups(groups)


def _size_from_groups(groups: tuple[tuple[str, ...], ...]) -> Size | None:
    if len(groups) == 1 and len(groups[0]) == 2:  # [50, "ml"]: a number, then its unit
        value, unit = groups[0]
        if _BARE_NUMBER_RE.fullmatch(value) and not _BARE_NUMBER_RE.fullmatch(unit):
            return _one_size(f"{value} {unit}")
    if len(groups) == 2 and groups[0] and all(_BARE_NUMBER_RE.fullmatch(v) for v in groups[0]):
        values, units = set(groups[0]), {unit.lower() for unit in groups[1]}
        if len(values) != 1 or len(units) != 1:
            return None
        return _one_size(f"{values.pop()} {units.pop()}")
    distinct = {item for group in groups for item in group}
    return _one_size(distinct.pop()) if len(distinct) == 1 else None


def _one_size(text: str) -> Size | None:
    """The size when every number in ``text`` belongs to the same size ("1.7 fl oz / 50 ml")."""
    sizes = [_size(match) for match in _SIZE_RE.finditer(text)]
    if not sizes or len(_NUMBER_RE.findall(text)) != len(sizes):
        return None
    first = sizes[0]
    return first if all(first.same_as(other) for other in sizes[1:]) else None


def _size(match: re.Match[str]) -> Size:
    amount = Decimal(match.group(1).replace(",", "."))
    unit = re.sub(r"[\s.]", "", match.group(2).lower())
    if unit in _ML_PER_UNIT:
        return Size(_plain(amount * _ML_PER_UNIT[unit]), "ml")
    if unit == "oz":
        return Size(_plain(amount * _OZ_TO_G), "g")
    return Size(_plain(amount * _G_PER_UNIT[unit]), "g")


def _plain(value: Decimal) -> Decimal:
    """Trailing zeros dropped without exponent form: 30.0 -> 30, 3.50 -> 3.5."""
    value = value.normalize()
    return value.quantize(Decimal(1)) if value == value.to_integral_value() else value


@dataclass(frozen=True, slots=True)
class Shade:
    """A shade: a code (e.g. ``"n12"``, ``"220"``) and/or a folded name."""

    code: str | None
    name: str | None


def parse_shade(text: str | Sequence[str] | None) -> Shade | None:
    """Split a shade label ("220 Natural Beige", "N12 - Vanilla") into code and name.

    A list (see ``list_groups``) gives its shade only when it holds one distinct item.
    """
    if not text:
        return None
    if not isinstance(text, str) or is_listed(text):
        groups = list_groups(text)
        distinct = {item for group in groups or () for item in group}
        if len(distinct) != 1:
            return None
        text = distinct.pop()
    folded = fold(text)
    if not folded:
        return None
    match = _SHADE_CODE_RE.match(folded)
    if match is None:
        return Shade(None, folded)
    code = match.group(1)
    name = folded[match.end() :].strip() or None
    return Shade(code, name)


def concentration(text: str) -> Concentration | None:
    """The fragrance concentration written in ``text``, else None."""
    folded = fold(text)
    for value, pattern in _CONCENTRATION_PATTERNS:
        if pattern.search(folded):
            return value
    return None


def item_kind(text: str) -> ItemKind:
    """SET / REFILL / MINI when the text says so, else REGULAR."""
    folded = fold(text)
    for value, pattern in _KIND_PATTERNS:
        if pattern.search(folded):
            return value
    return ItemKind.REGULAR


def name_tokens(name: str, brand_key: str = "") -> frozenset[str]:
    """Product-name tokens without the brand, stopwords, sizes and attribute words."""
    folded = re.sub(r"\bspf\s*(\d+)", r"spf\1", fold(_SIZE_RE.sub(" ", name)))
    brand_words = set(brand_key.split())
    return frozenset(
        token
        for token in folded.split()
        if token not in _STOPWORDS
        and token not in _ATTRIBUTE_WORDS
        and token not in brand_words
        and not re.fullmatch(r"\d+(\.\d+)?", token)
    )


def valid_gtin(gtin: str | None) -> str | None:
    """The GTIN-8/12/13/14 digits when the check digit is valid, left-padded to 14; else None."""
    if gtin is None:
        return None
    digits = re.sub(r"\D", "", gtin)
    if len(digits) not in {8, 12, 13, 14}:
        return None
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return digits.zfill(14) if (10 - total % 10) % 10 == check else None
