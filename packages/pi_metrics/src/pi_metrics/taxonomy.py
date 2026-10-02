"""A shared category taxonomy over both retailers' breadcrumbs, read at serve time (taxonomy@1).

A product's ``category`` is the exporter's one-level code (one of ``BUCKETS``) followed by the
naming offer's own breadcrumb, at most three levels, verbatim. ``classify`` maps it to:

- a **common** category (``lipstick``, ``moisturizer`` ...) by rules on the breadcrumb levels.
  The deepest level that any rule matches decides. Within a level, the match ending last wins
  (English puts the head noun last: "Powder Brush" is ``tools``), then the longest, so
  "Tinted Moisturiser" is ``foundation``, not ``moisturizer``. A level that lists categories
  ("Cleansers & Exfoliators", "Masks, Peels") is read item by item, split on "&", "," and
  "and": items naming different categories make the product ``ambiguous``, as do two categories
  tying within one item. No rule anywhere makes it ``no_rule``.
  Neither is forced into a category: both are reported as unmapped, as is a product with no
  breadcrumb at all (``no_breadcrumb``: today's served file carries the code only, so ``common``
  maps nothing until an export publishes breadcrumbs).
- a **bucket**: the common category's bucket when it has one, else the exporter's code. This is
  where taxonomy@1 corrects the exporter's keyword order ("eye" before "skin"): an eye cream is
  ``eye_care``, so its bucket is ``skincare``, whatever the code says.

The rules only ever read the published breadcrumb, so a new rule is a code change and never a
re-export. ``TAXONOMY_VERSION`` changes with any rule, key or label.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pi_dataset import ContractModel, ProductV3

TAXONOMY_VERSION = "taxonomy@1"


class Label(ContractModel):
    en: str
    ar: str


#: The exporter's one-level codes (``scripts/demo_export/export.py`` ``ALLOWED_CATEGORIES``).
BUCKETS: dict[str, Label] = {
    "foundation": Label(en="Foundation", ar="كريم الأساس"),
    "concealer": Label(en="Concealer", ar="كونسيلر"),
    "lips": Label(en="Lips", ar="الشفاه"),
    "cheek": Label(en="Cheek", ar="الخدود"),
    "eyes": Label(en="Eyes", ar="العيون"),
    "skincare": Label(en="Skincare", ar="العناية بالبشرة"),
    "fragrance": Label(en="Fragrance", ar="العطور"),
    "body": Label(en="Body", ar="الجسم"),
    "other": Label(en="Other", ar="أخرى"),
}


class Common(ContractModel):
    label: Label
    #: The ``BUCKETS`` key it belongs to; ``None`` keeps the exporter's code as the bucket.
    bucket: str | None
    #: Regular expressions matched against one case-folded breadcrumb level. Each starts at a
    #: word boundary; a match's (end, length) is its specificity.
    patterns: tuple[str, ...]


def _c(en: str, ar: str, bucket: str | None, *patterns: str) -> Common:
    return Common(label=Label(en=en, ar=ar), bucket=bucket, patterns=patterns)


#: taxonomy@1. Keys are stable: a client may key its own labels on them.
COMMON: dict[str, Common] = {
    "lipstick": _c(
        "Lipstick",
        "أحمر الشفاه",
        "lips",
        r"lipsticks?",
        r"liquid lip",
        r"lip stains?",
        r"lip tints?",
    ),
    "lip_gloss": _c("Lip gloss", "ملمع الشفاه", "lips", r"lip gloss(es)?", r"gloss(es)?", r"plump"),
    "lip_liner": _c("Lip liner", "محدد الشفاه", "lips", r"lip ?liners?", r"lip pencils?"),
    "lip_care": _c(
        "Lip care",
        "العناية بالشفاه",
        "lips",
        r"lip balms?",
        r"balms?",
        r"lip (care|treatments?|oils?|masks?|scrubs?)",
    ),
    "foundation": _c(
        "Foundation",
        "كريم الأساس",
        "foundation",
        r"foundations?",
        r"(bb|cc) creams?",
        r"tinted moisturi[sz]ers?",
        r"skin tints?",
    ),
    "concealer": _c(
        "Concealer", "كونسيلر", "concealer", r"conceal", r"correctors?", r"colou?r correct"
    ),
    "powder": _c("Powder", "بودرة", None, r"(face |setting |loose |pressed )?powders?"),
    "primer": _c("Primer", "برايمر", None, r"(face )?primers?"),
    "setting_spray": _c(
        "Setting spray", "مثبت المكياج", None, r"(setting|fixing) (sprays?|mists?)"
    ),
    "blush": _c("Blush", "أحمر الخدود", "cheek", r"blush(es|ers?)?"),
    "bronzer": _c("Bronzer & contour", "برونزر وكونتور", "cheek", r"bronz", r"contour"),
    "highlighter": _c("Highlighter", "هايلايتر", "cheek", r"highlight", r"illuminat"),
    "mascara": _c("Mascara", "ماسكارا", "eyes", r"mascaras?"),
    "eyeliner": _c(
        "Eyeliner", "محدد العيون", "eyes", r"eye ?liners?", r"eye pencils?", r"kohl", r"kajal"
    ),
    "eyeshadow": _c("Eyeshadow", "ظلال العيون", "eyes", r"eye ?shadows?", r"eye ?shadow palettes?"),
    "brows": _c("Brows", "الحواجب", "eyes", r"brows?", r"eyebrows?"),
    "lashes": _c("Lashes", "الرموش", "eyes", r"(false )?lash(es)?", r"lash serums?"),
    "moisturizer": _c(
        "Moisturizer",
        "مرطب",
        "skincare",
        r"moisturi[sz]",
        r"(day|night|face|gel) creams?",
    ),
    "serum": _c("Serum", "سيروم", "skincare", r"serums?", r"ampoules?", r"essences?"),
    "face_oil": _c("Face oil", "زيت الوجه", "skincare", r"(face|facial) oils?"),
    "cleanser": _c(
        "Cleanser",
        "منظف",
        "skincare",
        r"cleans",
        r"cleansing (balms?|oils?)",
        r"face wash(es)?",
        r"micellar",
        r"make[- ]?up removers?",
    ),
    "toner": _c("Toner", "تونر", "skincare", r"toners?", r"(face|facial) mists?"),
    "exfoliator": _c(
        "Exfoliator", "مقشر", "skincare", r"exfoliat", r"peels?", r"(face|facial) scrubs?"
    ),
    "mask": _c("Mask", "ماسك", "skincare", r"masks?", r"(face|sheet) masks?"),
    "eye_care": _c(
        "Eye care",
        "العناية بالعيون",
        "skincare",
        r"eye (creams?|care|serums?|gels?|masks?|patch(es)?)",
        r"under[- ]eye",
    ),
    "sunscreen": _c(
        "Sun care", "الحماية من الشمس", "skincare", r"sunscreens?", r"spf", r"sun (care|protection)"
    ),
    "fragrance": _c(
        "Fragrance",
        "العطور",
        "fragrance",
        r"fragrances?",
        r"perfumes?",
        r"parfums?",
        r"eau de",
        r"colognes?",
        r"body mists?",
    ),
    "body_care": _c(
        "Body care",
        "العناية بالجسم",
        "body",
        r"body (lotions?|creams?|butters?|oils?|scrubs?|washe?s?|care)",
        r"shower",
        r"bath",
        r"hand (creams?|care)",
        r"deodorants?",
        r"hair remov",
    ),
    "hair_care": _c(
        "Hair care",
        "العناية بالشعر",
        None,
        r"hair",
        r"hair (masks?|oils?|sprays?|serums?)",
        r"shampoos?",
        r"conditioners?",
    ),
    "tools": _c(
        "Tools & brushes",
        "الأدوات والفرش",
        None,
        r"brush(es)?",
        r"sponges?",
        r"tools?",
        r"applicators?",
        r"sharpeners?",
        r"curlers?",
    ),
    "sets": _c(
        "Sets & gifts",
        "المجموعات والهدايا",
        None,
        r"(gift |value )?sets\b",
        r"kits?\b",
        r"gifts?\b",
    ),
}

_COMPILED = {
    key: tuple(re.compile(rf"\b{pattern}") for pattern in common.patterns)
    for key, common in COMMON.items()
}


class Level(StrEnum):
    BUCKET = "bucket"
    COMMON = "common"


class Unmapped(StrEnum):
    #: The product's ``category`` is the exporter's code alone: there is no breadcrumb to read.
    #: True of every product in today's served file; ``bucket`` still comes from the code.
    NO_BREADCRUMB = "no_breadcrumb"
    #: No rule matched any breadcrumb level.
    NO_RULE = "no_rule"
    #: The deciding level names two categories: a list of them ("Masks & Peels"), or two
    #: tying on the best match.
    AMBIGUOUS = "ambiguous"


class Placement(ContractModel):
    """Where one product sits. Exactly one of ``common`` and ``unmapped`` is set."""

    bucket: str
    common: str | None
    unmapped: Unmapped | None
    #: The breadcrumb level that decided ``common`` (or tied), for audit; ``None`` if none did.
    matched: str | None


#: What separates the items of a list-style level ("Cleansers & Exfoliators").
_LIST = re.compile(r"\s*(?:&|,|\band\b)\s*")


def _item_match(text: str) -> tuple[tuple[int, int], set[str]]:
    """The best (end, length) of any match on one item and every key that reaches it."""
    best, keys = (0, 0), set[str]()
    for key, patterns in _COMPILED.items():
        score = max(
            ((m.end(), len(m.group(0))) for p in patterns for m in p.finditer(text)),
            default=(0, 0),
        )
        if score > best:
            best, keys = score, {key}
        elif score[0] and score == best:
            keys.add(key)
    return best, keys


def _level_keys(level: str) -> set[str]:
    """Every key one breadcrumb level names: one per item of a list, the best within each."""
    keys = set[str]()
    for item in _LIST.split(level.casefold()):
        best, found = _item_match(item)
        if best[0]:
            keys |= found
    return keys


def classify(category: tuple[str, ...]) -> Placement:
    """taxonomy@1 for one product ``category`` (code, then up to three breadcrumb levels)."""
    code = category[0].casefold() if category else "other"
    code = code if code in BUCKETS else "other"
    if len(category) < 2:
        return Placement(bucket=code, common=None, unmapped=Unmapped.NO_BREADCRUMB, matched=None)
    for level in reversed(category[1:]):
        keys = _level_keys(level)
        if not keys:
            continue
        if len(keys) > 1:
            return Placement(bucket=code, common=None, unmapped=Unmapped.AMBIGUOUS, matched=level)
        (key,) = keys
        return Placement(
            bucket=COMMON[key].bucket or code, common=key, unmapped=None, matched=level
        )
    return Placement(bucket=code, common=None, unmapped=Unmapped.NO_RULE, matched=None)


def place(product: ProductV3) -> Placement:
    return classify(product.category)


def label(level: Level, key: str) -> Label:
    return BUCKETS[key] if level is Level.BUCKET else COMMON[key].label
