"""Page attributes shared by the retailer readers: HTML fragments to text and bullet lines, the
ingredient-list test, enum and colour checks.

Every reader names the fields it reads; nothing here walks a page object, so a key the reader
does not name (unit cost, merchandising scores, API keys) can never become a reading.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Mapping
from typing import Final

from pi_capture.generic import _Emitter

__all__ = ["emit_bullets", "emit_enum", "emit_hex", "emit_inci", "emit_texts", "html_lines"]

_TAG = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"<\s*(?:/?\s*(?:li|p|div|ul|ol)|br)\b[^>]*>", re.I)
_SPACE = re.compile(r"\s+")
_SPACE_BEFORE_MARK = re.compile(r"\s+([,.;:!?])")  # left by a removed tag: "<b>x</b>, y"
_BULLET = re.compile(r"^[•\-\u2013*]\s*")
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

# An INCI list names these; a list of fragrance notes, actives with claims or a placeholder does
# not. Kept short and generic: one of them in the first items is enough.
_INCI_ANCHORS: Final = re.compile(
    r"\b(?:aqua|water|eau|glycerin|dimethicone|alcohol|parfum|fragrance|mica|silica|talc|"
    r"limonene|linalool|tocopherol|phenoxyethanol|squalane|ci\s?\d{5}|butylene glycol|"
    r"isododecane|octyldodecanol|ethyl acetate|caprylic)\b",
    re.I,
)
_INCI_MIN_ITEMS: Final = 6
_INCI_MAX_WORDS: Final = 8  # a long item is a sentence, not an ingredient name
_INCI_SHORT_SHARE: Final = 0.8
_INCI_PREFIX = re.compile(r"^(?:ingredients?\s*:\s*)", re.I)
# "Fragrance notes: …", "Top: Pink Pepper, …, Heart: …": a perfume's notes, not its ingredients
_NOTES = re.compile(r"\bnotes?\s*:|\b(?:top|heart|base)\s*:", re.I)


def html_text(fragment: str) -> str:
    """Tags out, entities decoded, whitespace collapsed."""
    text = _SPACE.sub(" ", html.unescape(_TAG.sub(" ", fragment))).strip()
    return _SPACE_BEFORE_MARK.sub(r"\1", text)


def html_lines(fragment: str) -> list[str]:
    """One line per paragraph, list item or break, bullet marks dropped, blanks and repeats out."""
    out: list[str] = []
    for part in _BREAK.split(fragment):
        line = _BULLET.sub("", html_text(part))
        if line and line not in out:
            out.append(line)
    return out


def _is_inci(text: str) -> bool:
    body = _INCI_PREFIX.sub("", _BULLET.sub("", text))
    # several bulleted parts are a kit or a list of actives with claims
    if _NOTES.search(body) or "•" in body:
        return False
    items = [i.strip() for i in re.split(r"[,|]", body) if i.strip()]
    if len(items) < _INCI_MIN_ITEMS:
        return False
    short = sum(1 for i in items if len(i.split()) <= _INCI_MAX_WORDS)
    if short < _INCI_SHORT_SHARE * len(items):
        return False
    return any(_INCI_ANCHORS.search(i) for i in items[:30])


def emit_inci(em: _Emitter, fragment: str, path: str) -> None:
    """``inci_list`` from an ingredients field, only when it reads as an INCI list; fragrance
    notes, actives with claims and "see the packaging" placeholders are ``parse_failed``."""
    text = html_text(fragment)
    if not text:
        return
    if _is_inci(text):
        em.observed("inci_list", text, _INCI_PREFIX.sub("", _BULLET.sub("", text)), path)
    else:
        em.failed(
            "inci_list", text, path, "not an INCI list (fragrance notes, actives or a placeholder)"
        )


def emit_bullets(em: _Emitter, fragment: str, path: str) -> None:
    """``bullets`` from an HTML fragment of paragraphs or list items. A heading line ending in a
    colon ("Set includes:", "How to use:") is a label, not a bullet."""
    lines = [line for line in html_lines(fragment) if not line.endswith(":")]
    if lines:
        em.observed("bullets", "\n".join(lines), lines, path)


def emit_texts(em: _Emitter, key: str, values: object, path: str) -> None:
    """A ``text[]`` key from a string or a list of strings, page order, repeats out."""
    items = [values] if isinstance(values, str) else values
    out: list[str] = []
    for item in items if isinstance(items, list) else []:
        text = html_text(item) if isinstance(item, str) else ""
        if text and text not in out:
            out.append(text)
    if out:
        em.observed(key, "\n".join(out), out, path)


def emit_enum(em: _Emitter, key: str, values: object, path: str, table: Mapping[str, str]) -> None:
    """An ``enum`` key from a site facet (one value or a list). Exactly one value, and it maps:
    observed. Several values or one outside ``table``: ``parse_failed``, nothing picked."""
    items = [values] if isinstance(values, str) else values
    raw = (
        [v.strip() for v in items if isinstance(v, str) and v.strip()]
        if isinstance(items, list)
        else []
    )
    if not raw:
        return
    joined = "|".join(raw)
    if len(raw) > 1:
        em.failed(key, joined, path, "several facet values; the attribute takes one")
    elif (value := table.get(_norm(raw[0]))) is None:
        em.failed(key, joined, path, "outside the attribute's values")
    else:
        em.observed(key, joined, value, path)


def emit_hex(em: _Emitter, value: object, path: str) -> None:
    """``colour_hex`` as ``#RRGGBB``, upper case; anything else is ``parse_failed``."""
    if not isinstance(value, str) or not value.strip():
        return
    if _HEX.match(value.strip()) is None:
        em.failed("colour_hex", value, path, "not a #RRGGBB colour")
    else:
        em.observed("colour_hex", value, value.strip().upper(), path)


def _norm(value: str) -> str:
    return re.sub(r"[^a-z]+", "_", value.lower()).strip("_")


def enum_table(pairs: Iterable[tuple[str, str]]) -> dict[str, str]:
    """A facet-value -> attribute-value table, keys normalised the way :func:`emit_enum` looks
    them up (lower case, runs of non-letters as one underscore)."""
    return {_norm(k): v for k, v in pairs}
