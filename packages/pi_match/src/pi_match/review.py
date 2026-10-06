"""``pi-match-review``: proposed exact pairs as pages one person can review, and back as decisions.

    uv run pi-match-review export --matches matches.json --source ulta_ae=beauty.json \\
        --source sephora_me=sephora.json --source faces_ae=faces.json --out packet/ [--batch 50]
    uv run pi-match-review import --packet packet/pairs.json --answers decisions.json ... \\
        [--decisions decisions.jsonl] --out decisions.jsonl

``export`` writes every ``proposed`` exact edge whose two listings are in the source files, most
confident first, as static HTML pages of ``--batch`` pairs (``batch-01.html`` ...) with an
``index.html``, plus ``pairs.json``, the manifest that maps the numbers on the pages back to the
pairs and the listing fingerprints the reviewer saw. Each pair shows both photos, brand, name, size,
concentration, price per retailer and plain-language flags, and takes one answer: same product,
different, or not sure. Answers stay in the browser (one store for the whole packet, with the time
of each answer) until the reviewer presses *Export my decisions*, which downloads
``decisions.json`` (or copies the same text), so a part-reviewed packet still counts.

``import`` turns those answers into ``Decision`` lines for ``pi-match-run --decisions``: *same*
is ``approve``, *different* is ``reject``, *not sure* and unanswered pairs make no decision. Each
decision carries the fingerprints from the manifest, so a listing that changed after the review
sends its pair back to review instead of reusing the answer (``pi_match.incremental``). The
reviewer is never named in the file (SEC-06): the run records ``decided_by=human``.

Nothing is auto-approved here, and the source and match files are only read. Scraped text is
escaped, and photos and links are shown only from each retailer's own hosts.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pi_core.enums import MatchClass, ReviewState
from pi_match.listings import listings
from pi_match.match import prepare
from pi_match.matchfile import Decision, Edge, ListingRef, MatchFile, Verdict
from pi_match.run_cli import _source, load_decisions

#: Retailer -> the hosts its photos and product pages may come from.
HOSTS: Mapping[str, frozenset[str]] = {
    "faces_ae": frozenset({"www.faces.ae"}),
    "sephora_me": frozenset({"www.sephora.me", "img-product.sephora.me"}),
    "ulta_ae": frozenset({"www.ulta.ae", "media.alshaya.com"}),
}
SHOP: Mapping[str, str] = {"faces_ae": "Faces", "sephora_me": "Sephora", "ulta_ae": "Ulta"}
ANSWERS: Mapping[str, Verdict] = {"yes": Verdict.APPROVE, "no": Verdict.REJECT}
#: The price flag (review-only): a pair's log price ratio this many robust sds from its retailer
#: pair's median, with the sd floored so near-identical prices do not flag a few percent.
PRICE_K, PRICE_FLOOR, PRICE_MIN_PAIRS = 3.5, 0.10, 30
_LISTING_FLAGS = {
    "name_size_conflict": "the name and the size field give different sizes",
    "name_url_concentration_conflict": "the page address names another concentration",
    "name_url_form_conflict": "the page address names another kind of product",
}

Key = tuple[str, str]


@dataclass(frozen=True)
class Side:
    retailer: str
    token: str
    brand: str
    name: str
    size: str | None
    concentration: str | None
    price: Decimal | None
    regular: Decimal | None
    currency: str | None
    image: str | None
    url: str | None
    flags: tuple[str, ...]


@dataclass(frozen=True)
class Row:
    number: int
    edge: Edge
    a: Side
    b: Side
    flags: tuple[str, ...]


def _last_amount(series: Mapping[str, Any], basis: str) -> Decimal | None:
    for point in reversed(series.get(basis) or ()):
        if point and Decimal(point["amount"]) > 0:
            return Decimal(point["amount"])
    return None


def _allowed(url: str | None, retailer: str) -> str | None:
    """``url`` when it is https on one of ``retailer``'s own hosts, else nothing."""
    if not url:
        return None
    parts = urlsplit(url)
    ok = parts.scheme == "https" and parts.hostname in HOSTS.get(retailer, frozenset())
    return url if ok else None


def _offer_of(data: Mapping[str, Any], retailer: str, tokens: set[str]) -> dict[str, Any]:
    """Token -> ``retailer``'s offer, for the tokens ``listings`` gave. A token is a one-offer
    product's id or one half of ``m-<token>-<token>``; an id with no single fitting split gives
    no offer (and so no price), never a guess."""
    out: dict[str, Any] = {}
    for product in data["products"]:
        pid: str = product["id"]
        offer = None
        for key, found in (product.get("offers") or {}).items():
            context = {c["id"]: c["retailer"] for c in data["meta"].get("contexts") or ()}
            if found is not None and context.get(key, key) == retailer:
                offer = found
        if offer is None:
            continue
        if pid in tokens:
            out[pid] = offer
            continue
        if not pid.startswith("m-"):
            continue
        rest = pid[2:]
        cuts = [i for i, ch in enumerate(rest) if ch == "-"]
        fits = {t for i in cuts for t in (rest[:i], rest[i + 1 :]) if t in tokens}
        if len(fits) == 1:
            out[fits.pop()] = offer
    return out


def sides(data: Mapping[str, Any], retailer: str) -> dict[Key, Side]:
    """Every listing of ``retailer`` in a dataset file, as the reviewer sees it."""
    records = listings(data, retailer)[0]
    offer_of = _offer_of(data, retailer, {r.source_key for r in records})
    out: dict[Key, Side] = {}
    for record in records:
        offer = offer_of.get(record.source_key) or {}
        series = offer.get("series") or {}
        prepared = prepare(record)
        out[(retailer, record.source_key)] = Side(
            retailer=retailer,
            token=record.source_key,
            brand=record.brand,
            name=record.name,
            size=record.size if isinstance(record.size, str) else None,
            concentration=None if prepared.concentration is None else prepared.concentration.value,
            price=_last_amount(series, "price"),
            regular=_last_amount(series, "regular"),
            currency=offer.get("currency"),
            image=_allowed(record.image_url, retailer),
            url=_allowed(record.url, retailer),
            flags=tuple(_LISTING_FLAGS.get(f, f) for f in prepared.flags),
        )
    return out


def price_outliers(rows: Sequence[tuple[Side, Side]]) -> dict[tuple[Key, Key], str]:
    """Pairs whose price ratio is far from what is usual for their two retailers, as text.

    The ratio is a review hint, never money: it is computed in floats and changes no decision.
    """
    by_pair: dict[tuple[str, str], list[tuple[Side, Side, float]]] = defaultdict(list)
    for a, b in rows:
        if a.price and b.price and a.currency == b.currency:
            by_pair[(a.retailer, b.retailer)].append((a, b, math.log(a.price / b.price)))
    out: dict[tuple[Key, Key], str] = {}
    for found in by_pair.values():
        if len(found) < PRICE_MIN_PAIRS:
            continue
        xs = [x for _, _, x in found]
        median = statistics.median(xs)
        mad = statistics.median(abs(x - median) for x in xs)
        sd = max(1.4826 * mad, PRICE_FLOOR)
        for a, b, x in found:
            if abs(x - median) > PRICE_K * sd:
                out[((a.retailer, a.token), (b.retailer, b.token))] = (
                    f"the prices are far apart ({SHOP.get(a.retailer, a.retailer)} {a.price}, "
                    f"{SHOP.get(b.retailer, b.retailer)} {b.price} {a.currency}): "
                    "a different size or set, or a sale"
                )
    return out


def _flags(a: Side, b: Side, price: str | None) -> tuple[str, ...]:
    out: list[str] = []
    if price:
        out.append(price)
    for side in (a, b):
        shop = SHOP.get(side.retailer, side.retailer)
        out.extend(f"{shop}: {f}" for f in side.flags)
        if side.image is None:
            out.append(f"{shop}: no photo")
    if (a.concentration is None) != (b.concentration is None):
        missing = a if a.concentration is None else b
        out.append(f"{SHOP.get(missing.retailer, missing.retailer)}: no concentration stated")
    return tuple(out)


def build(file: MatchFile, by_key: Mapping[Key, Side]) -> list[Row]:
    """The proposed exact edges with both listings known, most confident first, numbered."""
    decided = {d.pair() for d in file.decisions}
    edges = [
        e
        for e in file.edges
        if e.match_class is MatchClass.EXACT
        and e.review_state is ReviewState.PROPOSED
        and e.pair() not in decided
        and e.a.key() in by_key
        and e.b.key() in by_key
    ]
    edges.sort(key=lambda e: (-(e.confidence or Decimal(0)), e.pair()))
    prices = price_outliers([(by_key[e.a.key()], by_key[e.b.key()]) for e in edges])
    rows: list[Row] = []
    for number, e in enumerate(edges, start=1):
        a, b = by_key[e.a.key()], by_key[e.b.key()]
        rows.append(Row(number, e, a, b, _flags(a, b, prices.get(e.pair()))))
    return rows


def manifest(file: MatchFile, rows: Sequence[Row], batch: int) -> dict[str, Any]:
    """``pairs.json``: number -> pair and fingerprints; ``packet`` is a hash of the content."""
    pairs = {
        str(r.number): {
            "a": r.edge.a.model_dump(by_alias=True),
            "b": r.edge.b.model_dump(by_alias=True),
            "fingerprintA": file.listings[r.a.retailer][r.a.token],
            "fingerprintB": file.listings[r.b.retailer][r.b.token],
        }
        for r in rows
    }
    body = {"scope": file.scope, "generatedAt": file.generated_at, "batch": batch, "pairs": pairs}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]
    return {"packet": digest, **body}


# ---------------------------------------------------------------- pages

_STYLE = """
body{font:15px/1.4 system-ui,sans-serif;margin:0 auto;max-width:1100px;padding:16px;color:#1a1a1a}
h1{font-size:20px}.help{background:#f4f4f4;padding:10px 14px;border-radius:6px}
.pair{border:1px solid #ccc;border-radius:8px;margin:18px 0;padding:12px}
.pair.done{border-color:#2e7d32}.sides{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.side img{width:100%;max-width:320px;height:320px;object-fit:contain;background:#fafafa}
.nophoto{height:320px;display:flex;align-items:center;justify-content:center;background:#eee}
.shop{font-weight:700}.flags{background:#fff4d6;padding:6px 10px;margin:8px 0;border-radius:4px}
.ask{display:flex;gap:18px;font-size:16px;margin-top:8px}.ask label{cursor:pointer}
dl{display:grid;grid-template-columns:max-content 1fr;gap:2px 10px;margin:6px 0}dt{color:#555}
.bar{position:sticky;top:0;background:#fff;padding:8px 0;border-bottom:1px solid #ddd}
textarea{width:100%;height:60px}
.warn{color:#8a1c1c;font-weight:600}
"""

_SCRIPT = """
(function(){
const body=document.body,packet=body.dataset.packet,total=Number(body.dataset.total);
const store='pi-review-'+packet;
let disk=null,memory='{}';
try{disk=window.localStorage;disk.getItem(store);}catch(e){disk=null;}
if(!disk)document.getElementById('warn').hidden=false;
function load(){return JSON.parse((disk?disk.getItem(store):memory)||'{}');}
function keep(all){const t=JSON.stringify(all);if(disk)disk.setItem(store,t);else memory=t;}
const saved=load();
const inputs=[...document.querySelectorAll('input[type=radio]')];
function exported(){
  const all=load(),answers={},list=[];
  for(const n of Object.keys(all).sort(function(x,y){return x-y;})){
    answers[n]=all[n].verdict;
    list.push({pair:Number(n),a:all[n].a,b:all[n].b,verdict:all[n].verdict,decidedAt:all[n].at});
  }
  return JSON.stringify({packet:packet,exportedAt:new Date().toISOString(),
    answers:answers,decisions:list},null,1);
}
function refresh(){
  const all=load(),n=Object.keys(all).length;
  document.getElementById('count').textContent=n+' of '+total+' pairs answered in total';
  for(const p of document.querySelectorAll('.pair'))p.classList.toggle('done',p.dataset.n in all);
  document.getElementById('copy').value=exported();
}
function change(e){
  const i=e.target,p=i.closest('.pair'),all=load();
  all[i.name]={verdict:i.value,a:p.dataset.a,b:p.dataset.b,at:new Date().toISOString()};
  keep(all);
  refresh();
}
for(const i of inputs){
  if(saved[i.name]&&saved[i.name].verdict===i.value)i.checked=true;
  i.addEventListener('change',change);
}
document.getElementById('save').addEventListener('click',function(){
  const box=document.getElementById('copy');box.focus();box.select();
  const url=URL.createObjectURL(new Blob([exported()],{type:'application/json'}));
  const link=document.createElement('a');
  link.href=url;link.download='decisions.json';
  document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url);
});
refresh();
})();
"""


def _hash(text: str) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()


def _csp() -> str:
    images = " ".join(sorted(f"https://{h}" for hosts in HOSTS.values() for h in hosts))
    return (
        f"default-src 'none'; img-src {images}; style-src '{_hash(_STYLE)}'; "
        f"script-src '{_hash(_SCRIPT)}'; base-uri 'none'; form-action 'none'"
    )


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _price(side: Side) -> str:
    if side.price is None:
        return "not shown"
    text = f"{side.price} {side.currency or ''}".strip()
    if side.regular is not None and side.regular > side.price:
        text += f" (was {side.regular})"
    return text


def _side(side: Side) -> str:
    shop = SHOP.get(side.retailer, side.retailer)
    photo = (
        f'<img src="{_e(side.image)}" alt="{_e(shop)} photo" loading="lazy" '
        'referrerpolicy="no-referrer">'
        if side.image
        else '<div class="nophoto">No photo</div>'
    )
    link = (
        f'<a href="{_e(side.url)}" target="_blank" rel="noopener noreferrer">Open on {_e(shop)}</a>'
        if side.url
        else ""
    )
    return (
        f'<div class="side"><div class="shop">{_e(shop)}</div>{photo}<dl>'
        f"<dt>Brand</dt><dd>{_e(side.brand)}</dd><dt>Name</dt><dd>{_e(side.name)}</dd>"
        f"<dt>Size</dt><dd>{_e(side.size or 'not stated')}</dd>"
        f"<dt>Concentration</dt><dd>{_e(side.concentration or 'not stated')}</dd>"
        f"<dt>Price</dt><dd>{_e(_price(side))}</dd></dl>{link}</div>"
    )


_CHOICES = (("yes", "Yes, same product"), ("no", "No, different"), ("unsure", "Not sure"))


def _ref(side: Side) -> str:
    return f"{side.retailer}:{side.token}"


def _pair(row: Row) -> str:
    flags = (
        '<div class="flags">Check: ' + "; ".join(_e(f) for f in row.flags) + "</div>"
        if row.flags
        else ""
    )
    n = row.number
    ask = "".join(
        f'<label><input type="radio" name="{n}" value="{value}"> {label}</label>'
        for value, label in _CHOICES
    )
    return (
        f'<section class="pair" data-n="{n}" data-a="{_e(_ref(row.a))}" data-b="{_e(_ref(row.b))}">'
        f"<h2>Pair {n}</h2>{flags}"
        f'<div class="sides">{_side(row.a)}{_side(row.b)}</div><div class="ask">{ask}</div>'
        "</section>"
    )


def _page(title: str, packet: str, total: int, content: str) -> str:
    tail = f"<script>{_SCRIPT}</script>"
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{_e(_csp())}">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_e(title)}</title><style>{_STYLE}</style></head>"
        f'<body data-packet="{_e(packet)}" data-total="{total}">{content}{tail}</body></html>\n'
    )


_HELP = (
    '<p class="help">For each pair: is it <b>the same product</b>, the same item you could buy at '
    "either shop (same brand, same product, same size, same concentration)? A different size, a "
    "gift set, a refill or another version is <b>Different</b>. If you cannot tell, choose "
    "<b>Not sure</b>. Your answers are kept in this browser across all pages. When you stop, "
    "press <b>Export my decisions</b> and send the decisions.json file (or copy the text below "
    "the button). Every answered pair counts, even if you stop half-way.</p>"
)


def _bar(title: str) -> str:
    return (
        f'<div class="bar"><h1>{_e(title)}</h1><span id="count"></span> '
        '<button id="save" type="button">Export my decisions</button>'
        '<textarea id="copy" readonly aria-label="Decisions as text"></textarea>'
        '<p id="warn" class="warn" hidden>This viewer cannot keep answers after the page is '
        "closed, and may block the download. Before you close or change page, copy all the text "
        "in the box above and send it. To keep answers between visits, download the folder and "
        "open index.html from your computer.</p></div>"
    )


def pages(rows: Sequence[Row], packet: str, batch: int) -> dict[str, str]:
    """File name -> HTML: ``index.html`` and one page per ``batch`` pairs."""
    chunks = [rows[i : i + batch] for i in range(0, len(rows), batch)]
    out: dict[str, str] = {}
    links: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        name = f"batch-{i:02d}.html"
        first, last = chunk[0].number, chunk[-1].number
        title = f"Match review, page {i} of {len(chunks)} (pairs {first}-{last})"
        body = _bar(title) + _HELP + "".join(_pair(r) for r in chunk)
        out[name] = _page(title, packet, len(rows), body)
        links.append(f'<li><a href="{name}">{_e(title)}</a></li>')
    index = (
        _bar(f"Match review: {len(rows)} pairs")
        + _HELP
        + f"<p>Most confident pairs first, {batch} per page.</p><ul>{''.join(links)}</ul>"
    )
    out["index.html"] = _page("Match review", packet, len(rows), index)
    return out


def export(file: MatchFile, sources: Mapping[str, Mapping[str, Any]], out: Path, batch: int) -> int:
    """Writes the packet to ``out``; returns the number of pairs."""
    by_key: dict[Key, Side] = {}
    for retailer, data in sources.items():
        by_key.update(sides(data, retailer))
    rows = build(file, by_key)
    meta = manifest(file, rows, batch)
    out.mkdir(parents=True, exist_ok=True)
    (out / "pairs.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    for name, text in pages(rows, meta["packet"], batch).items():
        (out / name).write_text(text, encoding="utf-8")
    return len(rows)


# ---------------------------------------------------------------- answers back


class AnswersError(ValueError):
    """An answers file that does not belong to the packet or contradicts another."""


def _answers(meta: Mapping[str, Any], found: Mapping[str, Any]) -> dict[str, str]:
    """Pair number -> answer, from ``answers`` and/or the ``decisions`` list of an export.

    A ``decisions`` entry names its two listings; they must be the pair the packet gave that
    number, so an answer can never land on another pair.
    """
    out = {str(k): v for k, v in (found.get("answers") or {}).items()}
    for entry in found.get("decisions") or []:
        number = str(entry.get("pair"))
        pair = meta["pairs"].get(number)
        if pair is None:
            msg = f"pair {number} is not in the packet"
            raise AnswersError(msg)
        refs = {f"{r['retailer']}:{r['token']}" for r in (pair["a"], pair["b"])}
        if {entry.get("a"), entry.get("b")} != refs:
            msg = f"pair {number} names other listings than the packet"
            raise AnswersError(msg)
        if out.setdefault(number, entry.get("verdict")) != entry.get("verdict"):
            msg = f"pair {number} answered both {out[number]!r} and {entry.get('verdict')!r}"
            raise AnswersError(msg)
    return out


def decisions(meta: Mapping[str, Any], answers: Sequence[Mapping[str, Any]]) -> list[Decision]:
    """The decisions in ``answers`` (one per saved page), checked against the packet."""
    chosen: dict[str, str] = {}
    for found in answers:
        if found.get("packet") != meta["packet"]:
            msg = f"answers for packet {found.get('packet')!r}, not {meta['packet']!r}"
            raise AnswersError(msg)
        for number, answer in _answers(meta, found).items():
            if number not in meta["pairs"]:
                msg = f"pair {number} is not in the packet"
                raise AnswersError(msg)
            if answer not in (*ANSWERS, "unsure"):
                msg = f"pair {number}: unknown answer {answer!r}"
                raise AnswersError(msg)
            if chosen.setdefault(number, answer) != answer:
                msg = f"pair {number} answered both {chosen[number]!r} and {answer!r}"
                raise AnswersError(msg)
    out: list[Decision] = []
    for number, answer in chosen.items():
        if answer not in ANSWERS:
            continue
        pair = meta["pairs"][number]
        out.append(
            Decision(
                a=ListingRef.model_validate(pair["a"]),
                b=ListingRef.model_validate(pair["b"]),
                verdict=ANSWERS[answer],
                match_class=MatchClass.EXACT,
                fingerprint_a=pair["fingerprintA"],
                fingerprint_b=pair["fingerprintB"],
            )
        )
    return sorted(out, key=lambda d: d.pair())


def merged(existing: Sequence[Decision], new: Sequence[Decision]) -> list[Decision]:
    """``existing`` plus ``new``; a pair already decided another way is refused, not replaced."""
    by_pair = {d.pair(): d for d in existing}
    clash = [
        d.pair() for d in new if d.pair() in by_pair and by_pair[d.pair()].verdict != d.verdict
    ]
    if clash:
        msg = f"already decided the other way (edit the decisions file by hand): {clash[:5]}"
        raise AnswersError(msg)
    for d in new:
        by_pair.setdefault(d.pair(), d)
    return sorted(by_pair.values(), key=lambda d: d.pair())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pi-match-review", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("export", help="write the review packet")
    ex.add_argument("--matches", type=Path, required=True)
    ex.add_argument("--source", type=_source, action="append", required=True)
    ex.add_argument("--batch", type=int, default=50)
    ex.add_argument("--out", type=Path, required=True)
    im = sub.add_parser("import", help="answers -> decisions.jsonl")
    im.add_argument("--packet", type=Path, required=True)
    im.add_argument("--answers", type=Path, action="append", required=True)
    im.add_argument("--decisions", type=Path)
    im.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "export":
        if args.batch < 1:
            parser.error("--batch must be at least 1")
        file = MatchFile.model_validate_json(args.matches.read_text(encoding="utf-8"))
        cache: dict[Path, Any] = {}
        sources = {
            r: cache.setdefault(p, json.loads(p.read_text(encoding="utf-8")))
            for r, p in args.source
        }
        print(json.dumps({"pairs": export(file, sources, args.out, args.batch)}))
        return 0
    meta = json.loads(args.packet.read_text(encoding="utf-8"))
    try:
        new = decisions(meta, [json.loads(p.read_text(encoding="utf-8")) for p in args.answers])
        old = load_decisions(args.decisions) if args.decisions is not None else ()
        result = merged(old, new)
    except AnswersError as exc:
        raise SystemExit(f"pi-match-review: {exc}") from exc
    lines = "".join(d.model_dump_json(by_alias=True) + "\n" for d in result)
    args.out.write_text(lines, encoding="utf-8")
    counts = {v.value: sum(d.verdict is v for d in new) for v in (Verdict.APPROVE, Verdict.REJECT)}
    print(json.dumps({"new": counts, "total": len(result)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
