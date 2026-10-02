"""Generic page extractors: the machine-readable blocks most retailers publish on a product page.

Everything here is a pure function over HTML text. Nothing fetches. The extractors return the
blocks whole (JSON-LD, OpenGraph and other metas, microdata, ``__NEXT_DATA__``, React Server
Component chunks) and :func:`readings_from_generic` maps the fields that have a registry key onto
``Reading`` objects, raw text beside each value. A field that is absent is simply not emitted;
a field that is present but cannot be normalised is a ``parse_failed`` reading that keeps the
retailer's text.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from pi_capture.model import Reading
from pi_capture.registry import AttributeLevel, get
from pi_core.money import CURRENCY_EXPONENTS

__all__ = [
    "LOOKED_FOR",
    "GenericFacts",
    "find_json_objects",
    "generic_facts",
    "jsonld_blocks",
    "meta_tags",
    "meta_tags_all",
    "microdata_items",
    "next_data",
    "parse_jsonld",
    "readings_from_generic",
    "rsc_chunks",
    "rsc_text",
]

JsonObject = dict[str, Any]

_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }
)
_PRODUCT_TYPES = frozenset({"Product", "IndividualProduct", "ProductModel", "ProductGroup"})


# ------------------------------------------------------------------ HTML collection
@dataclass
class _MicroItem:
    itemtype: str | None
    props: dict[str, list[Any]] = field(default_factory=dict)


@dataclass
class _Open:
    """An open element, kept on the stack while its content is collected."""

    tag: str
    itemprop: str | None
    item: _MicroItem | None
    text: list[str] = field(default_factory=list)


class _Collector(HTMLParser):
    """One pass over the document collecting scripts, metas, links, microdata and <title>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[tuple[dict[str, str | None], str]] = []
        self.metas: list[dict[str, str | None]] = []
        self.links: list[dict[str, str | None]] = []
        self.html_lang: str | None = None
        self.title: str | None = None
        self.top_items: list[_MicroItem] = []
        self._stack: list[_Open] = []
        self._script: dict[str, str | None] | None = None
        self._script_text: list[str] = []
        self._in_title = False
        self._title_text: list[str] = []

    # -- microdata helpers
    def _current_item(self) -> _MicroItem | None:
        for open_ in reversed(self._stack):
            if open_.item is not None:
                return open_.item
        return None

    def _assign(self, prop: str | None, value: Any, owner: _MicroItem | None) -> None:
        if prop is None or owner is None:
            return
        for name in prop.split():
            owner.props.setdefault(name, []).append(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "script":
            self._script = a
            self._script_text = []
            return
        if tag == "meta":
            self.metas.append(a)
        elif tag == "link":
            self.links.append(a)
        elif tag == "html" and self.html_lang is None:
            self.html_lang = a.get("lang")
        elif tag == "title":
            self._in_title = True
            self._title_text = []

        itemprop = a.get("itemprop")
        owner = self._current_item()
        item: _MicroItem | None = None
        if "itemscope" in a:
            item = _MicroItem(itemtype=a.get("itemtype"))
            if itemprop is None or owner is None:
                self.top_items.append(item)
            else:
                self._assign(itemprop, item, owner)
            itemprop = None  # consumed by the nested item
        if tag in _VOID_TAGS:
            self._assign(itemprop, _void_value(tag, a), owner)
            return
        if itemprop is not None and (value := _attr_value(tag, a)) is not None:
            self._assign(itemprop, value, owner)
            itemprop = None
        self._stack.append(_Open(tag=tag, itemprop=itemprop, item=item))

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script is not None:
            self.scripts.append((self._script, "".join(self._script_text)))
            self._script = None
            return
        if tag == "title" and self._in_title:
            self.title = " ".join("".join(self._title_text).split())
            self._in_title = False
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i].tag == tag:
                closed = self._stack[i:]
                del self._stack[i:]
                text = " ".join("".join(closed[0].text).split())
                self._assign(closed[0].itemprop, text, self._current_item())
                if self._stack:
                    self._stack[-1].text.append(text)
                break

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script_text.append(data)
            return
        if self._in_title:
            self._title_text.append(data)
        if self._stack:
            self._stack[-1].text.append(data)


def _void_value(tag: str, a: Mapping[str, str | None]) -> str:
    if tag == "meta":
        return a.get("content") or ""
    if tag in {"img", "source", "embed", "track"}:
        return a.get("src") or ""
    if tag == "link":
        return a.get("href") or ""
    return ""


def _attr_value(tag: str, a: Mapping[str, str | None]) -> str | None:
    if tag in {"a", "area"}:
        return a.get("href")
    if tag in {"audio", "video", "iframe"}:
        return a.get("src")
    if tag == "time" and a.get("datetime") is not None:
        return a.get("datetime")
    if tag == "data" and a.get("value") is not None:
        return a.get("value")
    if tag == "meta":
        return a.get("content")
    return None


def _collect(html: str) -> _Collector:
    c = _Collector()
    c.feed(html)
    c.close()
    return c


# ------------------------------------------------------------------ public block readers
def _is_jsonld(attrs: Mapping[str, str | None]) -> bool:
    kind = (attrs.get("type") or "").split(";")[0].strip().lower()
    return kind == "application/ld+json"


def parse_jsonld(html: str) -> tuple[list[JsonObject], list[str]]:
    """All JSON-LD objects on the page, plus the raw text of every block that was not valid JSON.

    A block holding an array contributes each object in it. Numbers decode as ``Decimal``.
    """
    blocks: list[JsonObject] = []
    failed: list[str] = []
    for attrs, text in _collect(html).scripts:
        if not _is_jsonld(attrs):
            continue
        try:
            data = json.loads(text, parse_float=Decimal, parse_constant=_refuse_constant)
        except ValueError:
            failed.append(text)
            continue
        items = data if isinstance(data, list) else [data]
        objects = [d for d in items if isinstance(d, dict)]
        if not objects:
            failed.append(text)
        blocks.extend(objects)
    return blocks, failed


def jsonld_blocks(html: str) -> list[JsonObject]:
    return parse_jsonld(html)[0]


def meta_tags_all(html: str) -> dict[str, list[str]]:
    """Every meta/link/title value by key, in document order; see :func:`meta_tags` for the keys."""
    c = _collect(html)
    out: dict[str, list[str]] = {}
    if c.html_lang:
        out["html:lang"] = [c.html_lang]
    if c.title:
        out["title"] = [c.title]
    for m in c.metas:
        key = m.get("property") or m.get("name")
        content = m.get("content")
        if key and content is not None:
            out.setdefault(key.strip(), []).append(content)
    for link in c.links:
        rel = (link.get("rel") or "").lower().split()
        href = link.get("href")
        if href is None:
            continue
        if "canonical" in rel:
            out.setdefault("canonical", []).append(href)
        if "alternate" in rel and link.get("hreflang"):
            out.setdefault(f"hreflang:{(link.get('hreflang') or '').lower()}", []).append(href)
    return out


def meta_tags(html: str) -> dict[str, str]:
    """First value per key: ``og:*``, ``twitter:*``, ``product:*``, plain ``name=`` metas,
    ``canonical``, ``hreflang:<tag>``, ``html:lang`` and ``title``."""
    return {k: v[0] for k, v in meta_tags_all(html).items()}


def microdata_items(html: str) -> list[JsonObject]:
    """Top-level microdata items as ``{"@type": itemtype, prop: [values...]}`` dicts.

    Property values are strings; a nested ``itemscope`` is a nested dict. Every property is a
    list because microdata allows repeats (several images, several offers).
    """
    return [_micro_to_dict(item) for item in _collect(html).top_items]


def _micro_to_dict(item: _MicroItem) -> JsonObject:
    out: JsonObject = {"@type": item.itemtype}
    for name, values in item.props.items():
        out[name] = [_micro_to_dict(v) if isinstance(v, _MicroItem) else v for v in values]
    return out


def next_data(html: str) -> JsonObject | None:
    """The ``__NEXT_DATA__`` script decoded. ``None`` when absent; invalid JSON raises."""
    for attrs, text in _collect(html).scripts:
        if attrs.get("id") == "__NEXT_DATA__":
            data = json.loads(text, parse_float=Decimal, parse_constant=_refuse_constant)
            if not isinstance(data, dict):
                raise ValueError("__NEXT_DATA__ is not a JSON object")
            return data
    return None


_RSC_RE = re.compile(r"self\.__next_f\.push\(\s*\[\s*1\s*,\s*\"((?:[^\"\\]|\\.)*)\"\s*\]\s*\)")
_JS_ESCAPE_RE = re.compile(r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", re.DOTALL)
_JS_SIMPLE_ESCAPES = {
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "0": "\0",
    '"': '"',
    "'": "'",
    "\\": "\\",
    "/": "/",
    "\n": "",
}


def _js_unescape(literal: str) -> str:
    def one(m: re.Match[str]) -> str:
        esc = m.group(1)
        if esc[0] in "ux" and len(esc) > 1:
            return chr(int(esc[1:], 16))
        return _JS_SIMPLE_ESCAPES.get(esc, esc)

    text = _JS_ESCAPE_RE.sub(one, literal)
    # ``😀`` pairs come out as two surrogates; re-pair them.
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def rsc_chunks(html: str) -> list[str]:
    """Each ``self.__next_f.push([1,"…"])`` payload, decoded, in document order."""
    chunks: list[str] = []
    for attrs, text in _collect(html).scripts:
        if attrs.get("type") not in (None, "", "text/javascript", "module"):
            continue
        chunks.extend(_js_unescape(m.group(1)) for m in _RSC_RE.finditer(text))
    return chunks


def rsc_text(html: str) -> str:
    """All React Server Component chunks joined, ready for :func:`find_json_objects`."""
    return "".join(rsc_chunks(html))


def _refuse_constant(token: str) -> Any:
    """``NaN``/``Infinity`` are not JSON; a block using them is invalid, never a number."""
    raise ValueError(f"{token} is not accepted")


_DECODER = json.JSONDecoder(parse_float=Decimal, parse_constant=_refuse_constant)


def _enclosing_braces(text: str, positions: Sequence[int]) -> dict[int, list[int]]:
    """For each position, the indexes of the ``{`` enclosing it, innermost first, in one pass.

    Quoted strings are skipped so braces inside them do not count. A JSON string cannot hold a raw
    newline, so a newline ends one; that keeps a stray quote in surrounding script text from
    swallowing the rest of the document. Unclosed braces still count as enclosing: the decoder
    decides whether the span is an object.
    """
    wanted = sorted(set(positions))
    out: dict[int, list[int]] = {}
    stack: list[int] = []
    in_string = escaped = False
    next_wanted = 0
    for i, ch in enumerate(text):
        if next_wanted < len(wanted) and i == wanted[next_wanted]:
            out[i] = stack[::-1]
            next_wanted += 1
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch in {'"', "\n"}:
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            stack.pop()
    return out


def find_json_objects(text: str, key: str) -> list[JsonObject]:
    """Every JSON object in ``text`` that has ``key`` as a direct member (innermost such object).

    Works on RSC payloads and other JSON-bearing text. Braces are matched in a single pass over
    the text; for each ``"key":`` occurrence the innermost enclosing brace that decodes to an
    object holding the key is taken, walking outwards only past spans that do not decode. The
    work is one scan plus one decode attempt per candidate brace. Nothing is guessed.
    """
    needle = re.compile(r'"' + re.escape(key) + r'"\s*:')
    matches = [m.start() for m in needle.finditer(text)]
    if not matches:
        return []
    enclosing = _enclosing_braces(text, matches)
    found: list[JsonObject] = []
    seen_starts: set[int] = set()
    for at in matches:
        for start in enclosing[at]:
            if start in seen_starts:
                break
            try:
                obj, end = _DECODER.raw_decode(text, start)
            except ValueError:
                continue
            if isinstance(obj, dict) and end > at and key in obj:
                seen_starts.add(start)
                found.append(obj)
                break
    return found


@dataclass(frozen=True, slots=True)
class GenericFacts:
    """Facts a page publishes that have no registry key yet, kept so nothing is thrown away."""

    availability: str | None = None
    item_condition: str | None = None
    seller: str | None = None
    price: str | None = None
    currency: str | None = None
    #: ``"low-high"`` when an AggregateOffer gave a range instead of one price.
    price_range: str | None = None
    og_type: str | None = None
    og_locale: str | None = None


def _as_str(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | Decimal):
        return str(value)
    return None


def _name_of(value: Any) -> str | None:
    """A schema.org thing given as a string or as ``{"name": …}``."""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        return _as_str(value.get("name"))
    return _as_str(value)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _types(node: Mapping[str, Any]) -> set[str]:
    return {t for t in _as_list(node.get("@type")) if isinstance(t, str)}


def _walk(blocks: Sequence[JsonObject]) -> Iterator[tuple[str, JsonObject]]:
    """Yield (path, node) for every top-level node, descending into ``@graph`` only."""
    for i, block in enumerate(blocks):
        graph = block.get("@graph")
        if isinstance(graph, list):
            for j, node in enumerate(graph):
                if isinstance(node, dict):
                    yield f"jsonld[{i}].@graph[{j}]", node
        else:
            yield f"jsonld[{i}]", block


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


_AMOUNT_RE = re.compile(r"^(?P<sign>[-+\u2212]?)(?P<body>\d[\d., ]*|[.,]\d{1,2})$")
_SPACED_RE = re.compile(r"^(?P<int>\d{1,3}(?: \d{3})+)(?:(?P<mark>[.,])(?P<frac>\d+))?$")
_THIN_SPACES = str.maketrans({"\u00a0": " ", "\u202f": " ", "\u2009": " "})
MAX_GROUP = 3  # thousands grouping: three digits per group, a first group of one to three


class _AmountError(ValueError):
    """A printed amount that must not be turned into a number; ``str(e)`` says why."""


def _grouped(groups: Sequence[str]) -> bool:
    """``["1", "299", "000"]`` is thousands grouping; a first group of 4+ digits or a short later
    group is not."""
    return 1 <= len(groups[0]) <= MAX_GROUP and all(len(x) == MAX_GROUP for x in groups[1:])


def _spaced(body: str) -> tuple[str, str]:
    """Spaces are thousands grouping and nothing else: ``1 299,50`` reads, ``12 50`` does not."""
    m = _SPACED_RE.match(body)
    if m is None:
        raise _AmountError("spaces do not read as thousands grouping")
    integer = m.group("int").replace(" ", "")
    if m.group("mark") is None:
        return integer, "' ' read as thousands grouping"
    if len(m.group("frac")) > MAX_GROUP:
        raise _AmountError("more decimals than any currency allows")
    note = f"' ' read as thousands grouping, {m.group('mark')!r} as the decimal mark"
    return integer + "." + m.group("frac"), note


def _unmix(body: str) -> tuple[str, str]:
    """Both ``.`` and ``,`` present: the last one is the decimal mark, the other groups by three."""
    decimal_mark = "." if body.rfind(".") > body.rfind(",") else ","
    grouping = "," if decimal_mark == "." else "."
    head, _, tail = body.rpartition(decimal_mark)
    groups = head.split(grouping)
    if grouping in tail or not _grouped(groups):
        raise _AmountError("mixed separators do not read as a number")
    return "".join(groups) + "." + tail, f"decimal mark {decimal_mark!r}, grouping {grouping!r}"


def _one_mark(body: str, mark: str, exponent: int) -> tuple[str, str | None]:
    """Only ``mark`` present: repeated -> thousands; 1-2 digits after -> decimal; 3 -> ambiguous
    unless the first group has 4+ digits (then the mark cannot group and is the decimal mark)."""
    parts = body.split(mark)
    if len(parts) > 2:
        if not _grouped(parts):
            raise _AmountError("separators do not read as a number")
        return "".join(parts), f"{mark!r} read as thousands grouping"
    if len(parts[1]) == MAX_GROUP and 1 <= len(parts[0]) <= MAX_GROUP:
        if mark == "." and exponent == 3:
            return parts[0] + "." + parts[1], "'.' read as the decimal mark (three minor places)"
        raise _AmountError("ambiguous separator: could be thousands or decimals")
    if len(parts[1]) > MAX_GROUP:
        raise _AmountError("more decimals than any currency allows")
    worth_noting = bool(parts[1]) and (mark == "," or len(parts[1]) == MAX_GROUP)
    note = f"{mark!r} read as the decimal mark" if worth_noting else None
    return (parts[0] or "0") + "." + parts[1] if parts[1] else parts[0], note


def _parse_amount(text: str, exponent: int) -> tuple[Decimal | None, str | None, str | None]:
    """``(value, reason, note)`` for a printed amount; ambiguous separators are refused.

    Rules, in order: both ``.`` and ``,`` present -> the last one is the decimal mark and the other
    must group thousands in threes; one mark used several times -> thousands grouping; one mark
    once with 1-2 digits after it -> decimal mark; one mark once with exactly 3 digits after it ->
    ambiguous ("1,250" is 1250 or 1.250), accepted only for a ``.`` when the currency has three
    minor places (KWD, BHD, OMR print 12.500) and refused otherwise. Grouping needs a first group
    of one to three digits, so "1234,567" cannot be grouped and the mark is the decimal mark.
    Spaces (plain, no-break, narrow, thin) are thousands grouping only: "1 299,50" reads,
    "12 50" (fils set as a superscript) and "1 2 3" are refused. Negative amounts, exponents,
    words and non-finite values are refused.
    """
    m = _AMOUNT_RE.match(text.translate(_THIN_SPACES).strip())
    if m is None:
        return None, f"not a number: {text!r}", None
    if m.group("sign") in {"-", "\u2212"}:
        return None, f"negative amount: {text!r}", None
    body = m.group("body")
    note: str | None = None
    try:
        if " " in body:
            body, note = _spaced(body)
        elif "." in body and "," in body:
            body, note = _unmix(body)
        elif "." in body or "," in body:
            body, note = _one_mark(body, "." if "." in body else ",", exponent)
    except _AmountError as e:
        return None, f"{e}: {text!r}", None
    return Decimal(body), None, note


def _minor_units(amount: str, currency: str | None) -> tuple[int | None, str | None, str | None]:
    """``("189.00", "AED") -> (18900, None, None)``; ``("12,50", "AED") -> (1250, None, note)``;
    on failure ``(None, reason, None)``. Negative, non-finite and ambiguous amounts are refused."""
    if currency is None:
        return None, "no currency given beside the price", None
    exponent = CURRENCY_EXPONENTS.get(currency.upper())
    if exponent is None:
        return None, f"unknown currency {currency!r}", None
    dec, reason, note = _parse_amount(amount, exponent)
    if dec is None:
        return None, reason, None
    scaled = dec.scaleb(exponent)
    if scaled != scaled.to_integral_value():
        return None, f"more decimals than {currency.upper()} allows", None
    return int(scaled), None, note


class _Emitter:
    """Collects readings, first source wins per key, and refuses duplicates by construction."""

    def __init__(self) -> None:
        self.readings: list[Reading] = []
        self._keys: set[str] = set()

    def has(self, key: str) -> bool:
        return key in self._keys

    def observed(  # noqa: PLR0913 - a reading has exactly these parts
        self,
        key: str,
        raw: str,
        value: Any,
        path: str,
        note: str | None = None,
        *,
        currency: str | None = None,
    ) -> None:
        self._emit(Reading(key, get(key).level, "observed", raw, value, path, note, currency))

    def failed(
        self, key: str, raw: str, path: str, note: str, *, currency: str | None = None
    ) -> None:
        self._emit(Reading(key, get(key).level, "parse_failed", raw, None, path, note, currency))

    def _emit(self, reading: Reading) -> None:
        if reading.key in self._keys:
            return
        self._keys.add(reading.key)
        self.readings.append(reading)


def _emit_price(  # noqa: PLR0913, PLR0917 - one call site shape, kept explicit
    em: _Emitter,
    key: str,
    amount: str,
    currency: str | None,
    path: str,
    note: str | None = None,
) -> None:
    """A money reading: minor units as the value, the currency as its own field, raw text kept."""
    minor, reason, parse_note = _minor_units(amount, currency)
    code = currency.upper() if currency and _CURRENCY_CODE.match(currency.strip()) else None
    raw = f"{amount} {currency}" if currency else amount
    if minor is None:
        em.failed(key, raw, path, reason or "could not read price", currency=code)
    else:
        notes = [n for n in (note, parse_note) if n]
        em.observed(key, raw, minor, path, "; ".join(notes) or None, currency=code)


_CURRENCY_CODE = re.compile(r"^[A-Za-z]{3}$")


def _emit_gtin(em: _Emitter, raw: str, path: str) -> None:
    digits = raw.replace(" ", "")
    if digits.isdigit() and len(digits) <= 14:
        em.observed("gtin", raw, digits.zfill(14), path, "padded to 14 digits")
    else:
        em.failed("gtin", raw, path, "not an 8-14 digit barcode")


def _emit_language(em: _Emitter, raw: str, path: str) -> None:
    lang = raw.replace("_", "-").split("-")[0].lower()
    if lang in {"ar", "en"}:
        em.observed("language", raw, lang, path)
    else:
        em.failed("language", raw, path, "outside the ar|en enum; needs review")


def _offer_nodes(product: Mapping[str, Any]) -> list[JsonObject]:
    nodes: list[JsonObject] = []
    for offer in _as_list(product.get("offers")):
        if not isinstance(offer, dict):
            continue
        if "AggregateOffer" in _types(offer) and isinstance(offer.get("offers"), list):
            nodes.extend(o for o in offer["offers"] if isinstance(o, dict))
        nodes.append(offer)
    return nodes


def _map_product(em: _Emitter, facts: dict[str, str | None], path: str, p: JsonObject) -> None:
    if (name := _as_str(p.get("name"))) is not None:
        em.observed("title", name, name, f"{path}.name")
    if (brand := _name_of(p.get("brand"))) is not None:
        em.observed("brand", brand, brand, f"{path}.brand")
    if (desc := _as_str(p.get("description"))) is not None:
        em.observed("description", desc, desc, f"{path}.description")
    images = [
        u
        for img in _as_list(p.get("image"))
        if (
            u := _as_str(img.get("url") or img.get("contentUrl"))
            if isinstance(img, dict)
            else _as_str(img)
        )
        is not None
    ]
    if images:
        em.observed("image_urls", _compact(p["image"]), images, f"{path}.image")
        em.observed(
            "image_count",
            _compact(p["image"]),
            len(images),
            f"{path}.image",
            "counted from image_urls",
        )
    if p.get("video") is not None:
        em.observed("has_video", _compact(p["video"]), True, f"{path}.video")
    if (sku := _as_str(p.get("sku"))) is not None:
        em.observed("retailer_sku", sku, sku, f"{path}.sku")
    for gkey in ("gtin", "gtin14", "gtin13", "gtin12", "gtin8"):
        if (gtin := _as_str(p.get(gkey))) is not None:
            _emit_gtin(em, gtin, f"{path}.{gkey}")
            break
    if (mpn := _as_str(p.get("mpn"))) is not None:
        em.observed("mpn", mpn, mpn, f"{path}.mpn")
    rating = p.get("aggregateRating")
    if isinstance(rating, dict):
        _map_rating(em, f"{path}.aggregateRating", rating)
    for i, offer in enumerate(_offer_nodes(p)):
        _map_offer(em, facts, f"{path}.offers[{i}]", offer)


def _map_rating(em: _Emitter, path: str, rating: Mapping[str, Any]) -> None:
    if (rv := _as_str(rating.get("ratingValue"))) is not None:
        try:
            value = Decimal(rv.replace(",", "."))
        except InvalidOperation:
            value = Decimal("NaN")
        if value.is_finite() and 0 <= value <= 10:
            em.observed("rating_value", rv, value, f"{path}.ratingValue")
        else:
            em.failed("rating_value", rv, f"{path}.ratingValue", "not a rating between 0 and 10")
    for ckey in ("ratingCount", "reviewCount"):
        if (rc := _as_str(rating.get(ckey))) is not None:
            if rc.isdigit():
                em.observed("rating_count", rc, int(rc), f"{path}.{ckey}")
            else:
                em.failed("rating_count", rc, f"{path}.{ckey}", "not a whole number")
            break


def _map_offer(
    em: _Emitter, facts: dict[str, str | None], path: str, offer: Mapping[str, Any]
) -> None:
    currency = _as_str(offer.get("priceCurrency"))
    price = _as_str(offer.get("price"))
    price_path = f"{path}.price"
    price_note: str | None = None
    low, high = _as_str(offer.get("lowPrice")), _as_str(offer.get("highPrice"))
    if price is None and low is not None:
        if high is None or high == low:
            # one price published as a range of one: take it, say where it came from
            price, price_path = low, f"{path}.lowPrice"
            price_note = "AggregateOffer with a single price (lowPrice == highPrice)"
        else:
            facts.setdefault("price_range", f"{low}-{high}")
    for i, ps in enumerate(_as_list(offer.get("priceSpecification"))):
        if not isinstance(ps, dict):
            continue
        ps_price, ps_currency = _as_str(ps.get("price")), _as_str(ps.get("priceCurrency"))
        kind = _as_str(ps.get("priceType")) or ""
        if ps_price is None:
            continue
        if kind.endswith("ListPrice"):
            _emit_price(
                em,
                "regular_price_minor",
                ps_price,
                ps_currency or currency,
                f"{path}.priceSpecification[{i}].price",
            )
        elif price is None:
            price, price_path = ps_price, f"{path}.priceSpecification[{i}].price"
            currency = currency or ps_currency
    if price is not None:
        _emit_price(em, "price_minor", price, currency, price_path, price_note)
        facts.setdefault("price", price)
        facts.setdefault("currency", currency)
    _map_offer_facts(em, facts, path, offer)


def _map_offer_facts(
    em: _Emitter, facts: dict[str, str | None], path: str, offer: Mapping[str, Any]
) -> None:
    if (count := _as_str(offer.get("offerCount"))) is not None:
        if count.isdigit():
            em.observed("offer_count", count, int(count), f"{path}.offerCount")
        else:
            em.failed("offer_count", count, f"{path}.offerCount", "not a whole number")
    if (avail := _as_str(offer.get("availability"))) is not None:
        facts.setdefault("availability", avail)
    if (cond := _as_str(offer.get("itemCondition"))) is not None:
        facts.setdefault("item_condition", cond)
    if (seller := _name_of(offer.get("seller"))) is not None:
        facts.setdefault("seller", seller)


def _map_breadcrumbs(em: _Emitter, path: str, node: Mapping[str, Any]) -> None:
    elements = [e for e in _as_list(node.get("itemListElement")) if isinstance(e, dict)]
    if not elements:
        return

    def order(ie: tuple[int, JsonObject]) -> int:
        pos = _position(ie[1])
        return ie[0] if pos is None else pos

    ordered = sorted(enumerate(elements), key=order)
    names = [n for _, e in ordered if (n := _name_of(e.get("name") or e.get("item"))) is not None]
    raw = _compact(node["itemListElement"])
    if names:
        em.observed("breadcrumb", raw, names, f"{path}.itemListElement")
    else:
        em.failed("breadcrumb", raw, f"{path}.itemListElement", "no readable names")


def _position(e: Mapping[str, Any]) -> int | None:
    pos = e.get("position")
    if isinstance(pos, bool):
        return None
    if isinstance(pos, int):
        return pos
    if isinstance(pos, str | Decimal) and str(pos).isdigit():
        return int(pos)
    return None


def _map_metas(em: _Emitter, facts: dict[str, str | None], all_: Mapping[str, list[str]]) -> None:
    first = {k: v[0] for k, v in all_.items()}

    def pick(*keys: str) -> tuple[str, str] | None:
        for k in keys:
            if v := first.get(k, "").strip():
                return k, v
        return None

    if not em.has("title") and (hit := pick("og:title", "twitter:title")):
        em.observed("title", hit[1], hit[1], f"meta[{hit[0]}]")
    if not em.has("description") and (hit := pick("og:description", "description")):
        em.observed("description", hit[1], hit[1], f"meta[{hit[0]}]")
    if not em.has("brand") and (hit := pick("og:brand", "product:brand")):
        em.observed("brand", hit[1], hit[1], f"meta[{hit[0]}]")
    if not em.has("image_urls"):
        for k in ("og:image", "og:image:secure_url", "twitter:image"):
            urls = [u for u in all_.get(k, ()) if u.strip()]
            if urls:
                em.observed("image_urls", "\n".join(urls), urls, f"meta[{k}]")
                em.observed(
                    "image_count",
                    "\n".join(urls),
                    len(urls),
                    f"meta[{k}]",
                    "counted from image_urls",
                )
                break
    if not em.has("has_video") and (hit := pick("og:video", "og:video:url")):
        em.observed("has_video", hit[1], True, f"meta[{hit[0]}]")
    if not em.has("price_minor") and (amt := pick("product:price:amount", "og:price:amount")):
        cur = pick("product:price:currency", "og:price:currency")
        _emit_price(em, "price_minor", amt[1], cur[1] if cur else None, f"meta[{amt[0]}]")
        facts.setdefault("price", amt[1])
        facts.setdefault("currency", cur[1] if cur else None)
    if avail := pick("product:availability", "og:availability"):
        facts.setdefault("availability", avail[1])
    if og_type := pick("og:type"):
        facts.setdefault("og_type", og_type[1])
    if og_locale := pick("og:locale"):
        facts.setdefault("og_locale", og_locale[1])


def _map_page(em: _Emitter, all_: Mapping[str, list[str]], url: str | None) -> None:
    canonical = next((u for u in all_.get("canonical", ()) if u.strip()), None)
    if canonical is None and (og_url := all_.get("og:url")):
        canonical = og_url[0].strip() or None
    if canonical is not None:
        em.observed("canonical_url", canonical, canonical, "link[canonical]")
        path = urlsplit(canonical).path
        if path:
            em.observed("listing_id", canonical, path, "link[canonical]", "path of canonical url")
    if url is not None:
        em.observed("page_url", url, url, "request.url")
        if not em.has("listing_id") and (path := urlsplit(url).path):
            em.observed("listing_id", url, path, "request.url", "path of page url")
    lang = all_.get("html:lang")
    if lang:
        em.observed("page_language", lang[0], lang[0], "html[lang]")
        _emit_language(em, lang[0], "html[lang]")
    elif og_locale := all_.get("og:locale"):
        em.observed("page_language", og_locale[0], og_locale[0], "meta[og:locale]")
        _emit_language(em, og_locale[0], "meta[og:locale]")


#: Every registry key the generic extractors know how to read. A capture made with them records
#: this as ``looked_for`` so coverage can separate "not on the page" from "nobody looked".
LOOKED_FOR: frozenset[str] = frozenset(
    {
        "title",
        "brand",
        "description",
        "image_urls",
        "image_count",
        "has_video",
        "retailer_sku",
        "gtin",
        "mpn",
        "rating_value",
        "rating_count",
        "price_minor",
        "regular_price_minor",
        "offer_count",
        "breadcrumb",
        "canonical_url",
        "listing_id",
        "page_url",
        "page_language",
        "language",
        "structured_data",
    }
)


def readings_from_generic(html: str, *, locale: str, url: str | None = None) -> list[Reading]:
    """Map the page's machine-readable blocks onto registry keys.

    JSON-LD wins, OpenGraph and other metas fill the gaps, the document fills page-level keys.
    ``locale`` is recorded on the capture, not here; it is accepted so callers pass the same
    arguments to every extractor. Absent fields are not emitted.
    """
    del locale  # the capture carries it; readings are locale-neutral
    return _extract(html, url)[0]


def generic_facts(html: str) -> GenericFacts:
    """Published facts without a registry key (availability, seller, condition, OpenGraph type)."""
    return _extract(html, None)[1]


def _extract(html: str, url: str | None) -> tuple[list[Reading], GenericFacts]:
    em = _Emitter()
    facts: dict[str, str | None] = {}
    blocks, failed = parse_jsonld(html)
    products = [(path, n) for path, n in _walk(blocks) if _types(n) & _PRODUCT_TYPES]
    for path, node in products[:1]:
        _map_product(em, facts, path, node)
    for path, node in _walk(blocks):
        if "BreadcrumbList" in _types(node):
            _map_breadcrumbs(em, path, node)
            break
    for item in microdata_items(html):
        # itemscope without itemtype gives @type None (seen on Faces pages).
        if str(item.get("@type") or "").rsplit("/", 1)[-1] in _PRODUCT_TYPES:
            _map_product(em, facts, "microdata", _micro_as_jsonld(item))
            break
    all_ = meta_tags_all(html)
    _map_metas(em, facts, all_)
    _map_page(em, all_, url)
    if blocks:
        raw = "\n".join(t for a, t in _collect(html).scripts if _is_jsonld(a))
        em.observed("structured_data", raw, blocks, "jsonld", f"{len(blocks)} block(s)")
    for i, text in enumerate(failed):
        em.readings.append(
            Reading(
                "structured_data",
                AttributeLevel.OFFER,
                "parse_failed",
                text,
                None,
                f"jsonld.failed[{i}]",
                "not valid JSON",
            )
        )
    return em.readings, GenericFacts(**{k: facts.get(k) for k in GenericFacts.__slots__})


def _micro_as_jsonld(item: Mapping[str, Any]) -> JsonObject:
    """Flatten microdata lists to JSON-LD shape (single values unwrapped, lists kept for image)."""
    out: JsonObject = {}
    for k, v in item.items():
        if k == "@type":
            out[k] = str(v).rsplit("/", 1)[-1]
        elif isinstance(v, list):
            vals = [_micro_as_jsonld(x) if isinstance(x, dict) else x for x in v]
            out[k] = vals if (len(vals) > 1 or k in {"image", "offers"}) else vals[0]
        else:
            out[k] = v
    return out
