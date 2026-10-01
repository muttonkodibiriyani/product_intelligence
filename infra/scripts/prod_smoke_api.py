#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Read-only API smoke for the main→prod deploy runbook; the OWNER runs it, nothing else does.

    read -rs PI_TOKEN      # the owner's own ID token, NOT exported (runbook N1)
    PI_TOKEN="$PI_TOKEN" uv run --locked --script infra/scripts/prod_smoke_api.py save \
        --out "$W/smoke"
    PI_TOKEN="$PI_TOKEN" uv run --locked --script infra/scripts/prod_smoke_api.py check \
        --out "$W/smoke" --expect-api 1.x.y

Only GET requests. It never creates, signs in or deletes a user: the token comes from the
``PI_TOKEN`` environment variable, never from argv, and is never printed or written. A 401 on a
call that sent the token exits 3 ("token expired: refresh it and re-run"); that is not a FAIL.
Redirects are never followed (the token must not travel to another host or over http): any 3xx
from the API is a FAIL, and ``--base`` must be https.

``save`` (before the deploy) records the version, cutoff, per-retailer counts, a cursor and every
served card price of 0.01 or less in the walked retailer's own contexts (the #146 floor) to
``<out>/baseline.json``; it exits 1 when the low-price count differs from
``--known-low-price`` (an unexplained data change).
``check`` (after it) runs S1-S8 of the runbook against that baseline, writes
``<out>/check.json`` and exits 1 on any FAIL. REVIEW lines need the owner's judgement,
not a rollback.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

BASE = "https://productintelligence-beeb3.web.app/api/v1"
EXPECTED = {"sephora_me": 9529, "ulta_ae": 7275}
IMAGE_HOSTS = {"sephora_me": "img-product.sephora.me", "ulta_ae": "media.alshaya.com"}
EVIDENCE_HOSTS = {"sephora_me": "www.sephora.me", "ulta_ae": "www.ulta.ae"}
#: The live Ulta catalogue object, as described in the runbook's baselines.
CATALOGUE_GENERATION = "1790852220300614"
#: The default --category-param; any user value replaces it (it is not appended to).
CATEGORY_PARAM = "retailers=sephora_me,ulta_ae"
KNOWN_LOW_PRICE = 2
FLOOR = Decimal("0.01")
PAGE = 100
CURSOR_QUERY = {"limit": "5"}  # a replayed cursor must use the query it was issued for
TOKEN_ENV = "PI_TOKEN"  # noqa: S105 -- the variable's name, not a credential
EXPIRED = 3


class TokenExpiredError(Exception):
    """A call that sent the token got 401: the owner's ID token (1 h) needs a refresh."""


class RedirectError(Exception):
    """The API answered 3xx. Redirects are refused, so this is a FAIL, never followed."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_: Any, **__: Any) -> None:
        return None  # urllib then raises HTTPError with the 3xx status


_OPENER = urllib.request.build_opener(_NoRedirect)


@dataclass(frozen=True)
class Response:
    status: int
    body: Any
    size: int
    content_type: str = ""

    @property
    def data(self) -> Any:
        return (self.body or {}).get("data") or {} if self.status == 200 else {}


#: (url, headers) -> Response. Production uses urllib; tests call an in-process app.
Transport = Callable[[str, Mapping[str, str]], Response]


def urllib_transport(url: str, headers: Mapping[str, str]) -> Response:
    request = urllib.request.Request(url, headers=dict(headers))  # noqa: S310 -- https only
    try:
        with _OPENER.open(request, timeout=60) as r:
            raw, status, ctype = r.read(), r.status, r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        raw, status, ctype = e.read(), e.code, e.headers.get("Content-Type", "")
    body = None
    if "json" in ctype:
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
    return Response(status, body, len(raw), ctype)


class Api:
    def __init__(self, transport: Transport, token: str, base: str = BASE) -> None:
        self._transport = transport
        self._token = token
        self.base = base

    def get(
        self, path: str, params: Mapping[str, str] | None = None, *, auth: bool = True
    ) -> Response:
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = {"Authorization": f"Bearer {self._token}"} if auth else {}
        r = self._transport(url, headers)
        if 300 <= r.status < 400:
            raise RedirectError(f"{path} -> {r.status}")
        if auth and r.status == 401:
            raise TokenExpiredError(path)
        return r

    def fetch(self, url: str) -> Response:
        """An unauthenticated GET of a public URL (an image on its CDN)."""
        return self._transport(url, {})


@dataclass
class Report:
    problems: list[str] = field(default_factory=list)
    reviews: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

    def expect(self, ok: bool, what: str) -> None:
        self._line(("ok     " if ok else "FAIL   ") + what)
        if not ok:
            self.problems.append(what)

    def review(self, what: str) -> None:
        self._line("REVIEW " + what)
        self.reviews.append(what)

    def info(self, what: str) -> None:
        self._line("       " + what)

    def _line(self, text: str) -> None:
        print(text)
        self.lines.append(text)


def amount(money: Any) -> Decimal | None:
    if not isinstance(money, dict):
        return None
    try:
        return Decimal(str(money.get("amount")))
    except InvalidOperation:
        return None


def low(money: Any) -> bool:
    value = amount(money)
    return value is not None and value <= FLOOR


def contexts(api: Api) -> dict[str, str]:
    """Context id -> retailer id, from /meta."""
    return {c["id"]: c["retailer"] for c in api.get("/meta").data.get("contexts") or []}


def cards(api: Api, retailer: str) -> Iterator[dict[str, Any]]:
    """Every /products card of one retailer, following nextCursor."""
    params = {"retailer": retailer, "limit": str(PAGE)}
    cursor: str | None = None
    while True:
        r = api.get("/products", {**params, "cursor": cursor} if cursor else params)
        if r.status != 200:
            raise RuntimeError(f"/products?retailer={retailer} -> {r.status}")
        yield from r.data.get("items") or []
        cursor = r.data.get("nextCursor")
        if not cursor:
            return


def low_rows(
    card: Mapping[str, Any], ctx: Mapping[str, str], retailer: str
) -> list[dict[str, str]]:
    """The card's served prices of 0.01 or less, one row per context OF ``retailer``.

    A card carries every context's price, so a product sold by both retailers is walked twice;
    counting only the walked retailer's contexts gives each (product, context) exactly once.
    """
    return [
        {"retailer": retailer, "product": card["id"], "context": c, "amount": str(amount(m))}
        for c, m in (card.get("prices") or {}).items()
        if ctx.get(c, c) == retailer and low(m)
    ]


def coverage(api: Api) -> dict[str, int]:
    return {x["id"]: x["productCount"] for x in api.get("/coverage").data.get("retailers") or []}


def image_url(card: Mapping[str, Any]) -> str | None:
    img = card.get("image")
    return img.get("url") if isinstance(img, dict) else img


def save(api: Api, out: Path, known_low: int) -> int:
    r = api.get("/products", CURSOR_QUERY)
    meta = (r.body or {}).get("meta") or {}
    ctx = contexts(api)
    rows = [row for rid in EXPECTED for card in cards(api, rid) for row in low_rows(card, ctx, rid)]
    baseline = {
        "apiVersion": meta.get("apiVersion"),
        "cutoff": meta.get("cutoff"),
        "counts": coverage(api),
        "cursor": r.data.get("nextCursor"),
        "lowPrice": rows,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "baseline.json").write_text(json.dumps(baseline, indent=1, sort_keys=True))
    print(f"api {baseline['apiVersion']}, cutoff {baseline['cutoff']}, counts {baseline['counts']}")
    print(f"cursor saved: {bool(baseline['cursor'])}")
    for row in rows:
        print(f"low price: {row['retailer']} {row['product']} {row['context']} {row['amount']}")
    status = 0
    if baseline["counts"].get("ulta_ae") != EXPECTED.get("ulta_ae"):
        print(
            f"STOP: ulta_ae serves {baseline['counts'].get('ulta_ae')}, "
            f"expected {EXPECTED.get('ulta_ae')}"
        )
        status = 1
    if len(rows) != known_low:
        print(
            f"STOP: {len(rows)} served prices <= 0.01, the recorded count is {known_low}: "
            "an unexplained data change"
        )
        status = 1
    if not baseline["cursor"]:
        print("STOP: no cursor saved")
        status = 1
    print(f"saved {out / 'baseline.json'}" + ("" if status else "; baseline OK"))
    return status


def s1_meta(api: Api, rep: Report, expect_api: str) -> None:
    r = api.get("/meta", auth=False)
    rep.expect(r.status == 401, f"S1 /meta without a token -> 401 ({r.status})")
    r = api.get("/meta")
    version = ((r.body or {}).get("meta") or {}).get("apiVersion")
    rep.expect(r.status == 200, f"S1 /meta with the token -> 200 ({r.status})")
    rep.expect(version == expect_api, f"S1 apiVersion {version} == {expect_api}")
    retailers = sorted(x.get("id") for x in r.data.get("retailers") or [])
    rep.expect(retailers == sorted(EXPECTED), f"S1 retailers {retailers}")


def s2_counts(api: Api, rep: Report, baseline: Mapping[str, Any]) -> None:
    got = coverage(api)
    rep.expect(
        got.get("ulta_ae") == EXPECTED["ulta_ae"],
        f"S2 ulta_ae {got.get('ulta_ae')} == {EXPECTED['ulta_ae']}",
    )
    rep.expect(
        got == baseline.get("counts"), f"S2 /coverage {got} == baseline {baseline.get('counts')}"
    )


def s3_images(api: Api, rep: Report) -> None:
    for rid, host in IMAGE_HOSTS.items():
        r = api.get("/products", {"retailer": rid, "limit": "50"})
        items = r.data.get("items") or []
        urls = [u for u in map(image_url, items) if u]
        bad = [u for u in urls if not u.startswith(f"https://{host}/")]
        rep.expect(
            bool(items) and not bad, f"S3 {rid}: {len(urls)} images, all on {host} (bad {bad[:2]})"
        )
        if rid == "ulta_ae" and urls:
            img = api.fetch(urls[0])
            rep.expect(
                img.status == 200 and img.content_type.startswith("image/"),
                f"S3 an ulta_ae image answers {img.status} {img.content_type or '-'}",
            )
        if items:
            offers = api.get(f"/products/{items[0]['id']}").data.get("offers") or []
            own: dict[str, Any] = next((o for o in offers if o.get("retailer") == rid), {})
            url = str((own.get("evidence") or {}).get("url") or "")
            rep.expect(
                url.startswith(f"https://{EVIDENCE_HOSTS[rid]}/"),
                f"S3 {rid} evidence on {EVIDENCE_HOSTS[rid]}",
            )


def floor_caveats(body: Any) -> dict[str, int]:
    return {
        c["params"]["retailer"]: int(c["params"]["count"])
        for c in (body or {}).get("caveats") or []
        if c.get("code") == "invalid_price_excluded"
    }


def s4_floor(api: Api, rep: Report, baseline: Mapping[str, Any]) -> None:
    """#146: each recorded low price is withheld (null + invalid_low), never dropped.

    (i) every baseline product is still served; (ii) its card price at the recorded context is
    null WITH priceFlags invalid_low, and its detail offer there is price null + priceFlag
    invalid_low; (iii) the invalid_price_excluded caveat vs the baseline; (iv) no card price
    <= 0.01 in any retailer's own contexts, and no detail regular <= 0.01 on baseline products.
    """
    ctx = contexts(api)
    before = baseline.get("lowPrice") or []
    seen: dict[str, dict[str, Any]] = {}
    still_low: list[dict[str, str]] = []
    for rid in EXPECTED:
        for card in cards(api, rid):
            seen[card["id"]] = card
            still_low += low_rows(card, ctx, rid)
    rep.expect(
        not still_low, f"S4(iv) 0 served card prices <= 0.01 ({len(still_low)}: {still_low[:2]})"
    )
    for row in before:
        pid, c = row["product"], row["context"]
        served = seen.get(pid)
        rep.expect(served is not None, f"S4(i) {pid} still served (withheld, not dropped)")
        if served is None:
            continue
        flag = (served.get("priceFlags") or {}).get(c)
        price = (served.get("prices") or {}).get(c, "absent")
        rep.expect(
            price is None and flag == "invalid_low",
            f"S4(ii) card {pid} {c}: price {price}, flag {flag}",
        )
        offers = api.get(f"/products/{pid}").data.get("offers") or []
        own = [o for o in offers if o.get("context") == c] or [
            o for o in offers if o.get("retailer") == row["retailer"]
        ]
        ok = bool(own) and all(
            o.get("price") is None and o.get("priceFlag") == "invalid_low" for o in own
        )
        rep.expect(ok, f"S4(ii) /products/{pid} offer at {c}: price null, priceFlag invalid_low")
        regular = [o for o in offers if low(o.get("regular"))]
        rep.expect(not regular, f"S4(iv) /products/{pid}: no regular <= 0.01")
    for rid in EXPECTED:
        want = sum(1 for row in before if row["retailer"] == rid)
        got = floor_caveats(api.get("/summary", {"retailer": rid}).body).get(rid, 0)
        what = f"S4(iii) {rid} invalid_price_excluded count {got}, baseline {want}"
        if got == want:
            rep.expect(True, what)
        elif got > want:
            # The caveat counts offers withheld on ANY date, price or regular; the baseline sees
            # only the latest card prices. More is explainable history; the owner judges it.
            rep.review(what + " (caveat also counts other dates and regular-only values)")
        else:
            rep.expect(False, what + " (fewer withheld than recorded)")


def s5_gallery(api: Api, rep: Report) -> None:
    r = api.get("/catalogues/ulta_ae")
    gen = r.data.get("generation")
    rep.expect(r.status == 200, f"S5 /catalogues/ulta_ae -> 200 ({r.status})")
    rep.expect(
        gen == CATALOGUE_GENERATION,
        f"S5 served catalogue generation {gen} == {CATALOGUE_GENERATION}",
    )
    sku = None
    for card in (
        api.get("/products", {"retailer": "ulta_ae", "limit": "20"}).data.get("items") or []
    ):
        offers = api.get(f"/products/{card['id']}").data.get("offers") or []
        sku = next(
            (o["sku"] for o in offers if o.get("retailer") == "ulta_ae" and o.get("sku")), None
        )
        if sku:
            break
    rep.expect(sku is not None, f"S5 an ulta_ae offer names its catalogue sku ({sku})")
    if sku is None:
        return
    r = api.get(f"/catalogues/ulta_ae/skus/{urllib.parse.quote(sku, safe='')}")
    images = r.data.get("images") or []  # CatalogueDetail.images; record has only imageIds
    urls = [i["url"] for i in images if i.get("url")]
    bad = [u for u in urls if not u.startswith(f"https://{IMAGE_HOSTS['ulta_ae']}/")]
    rep.expect(
        r.status == 200 and bool(urls) and not bad,
        f"S5 sku {sku}: {len(urls)} gallery images on media.alshaya.com (bad {bad[:2]})",
    )
    if urls:
        img = api.fetch(urls[0])
        rep.expect(
            img.status == 200 and img.content_type.startswith("image/"),
            f"S5 a gallery image answers {img.status}",
        )


def s6_category(api: Api, rep: Report, route: str, params: Mapping[str, str]) -> None:
    r = api.get(route, params)
    rep.expect(r.status == 200, f"S6 {route} with the token -> 200 ({r.status})")
    r = api.get(route, params, auth=False)
    rep.expect(r.status == 401, f"S6 {route} without a token -> 401 ({r.status})")


def s7_summary(api: Api, rep: Report) -> None:
    for rid in EXPECTED:
        r = api.get("/summary", {"retailer": rid})
        rep.expect(
            r.status == 200 and r.data.get("retailer") == rid,
            f"S7 /summary?retailer={rid} -> {r.status}",
        )
    top = api.get("/summary", {"retailer": "ulta_ae"}).data.get("topDiscounts") or []
    rep.expect(not top, f"S7 ulta_ae shows no discounts (#131; {len(top)})")


def s8_cursor(api: Api, rep: Report, baseline: Mapping[str, Any]) -> None:
    r = api.get("/products", {**CURSOR_QUERY, "cursor": str(baseline.get("cursor") or "")})
    n = len(r.data.get("items") or [])
    rep.expect(
        r.status == 200 and n > 0, f"S8 the baseline cursor still pages ({r.status}, {n} items)"
    )


def check(api: Api, out: Path, args: argparse.Namespace) -> int:
    baseline = json.loads((out / "baseline.json").read_text())
    rep = Report()
    s1_meta(api, rep, args.expect_api)
    s2_counts(api, rep, baseline)
    if not args.counts_only:
        s3_images(api, rep)
        s4_floor(api, rep, baseline)
        s5_gallery(api, rep)
        s6_category(
            api,
            rep,
            args.category_route,
            dict(p.split("=", 1) for p in args.category_param or [CATEGORY_PARAM]),
        )
        s7_summary(api, rep)
        s8_cursor(api, rep, baseline)
    verdict = "FAIL" if rep.problems else ("REVIEW" if rep.reviews else "PASS")
    (out / "check.json").write_text(
        json.dumps(
            {
                "verdict": verdict,
                "problems": rep.problems,
                "reviews": rep.reviews,
                "lines": rep.lines,
            },
            indent=1,
        )
    )
    print(f"PROD API SMOKE {verdict} ({len(rep.problems)} problems, {len(rep.reviews)} to review)")
    return 1 if rep.problems else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("mode", choices=["save", "check"])
    p.add_argument("--out", type=Path, required=True, help="baseline.json / check.json directory")
    p.add_argument("--base", default=BASE, help="API base (the optional tag URL + /api/v1)")
    p.add_argument("--expect-api", default="", help="check: API_VERSION at MAIN_SHA")
    p.add_argument("--known-low-price", type=int, default=KNOWN_LOW_PRICE)
    p.add_argument("--category-route", default="/category-compare")
    p.add_argument("--category-param", action="append", default=None)
    p.add_argument(
        "--counts-only",
        action="store_true",
        help="check: S1-S2 only (re-runs after (6) and rollback)",
    )
    args = p.parse_args(argv)
    if not args.base.startswith("https://"):
        p.error("--base must be https (the token is sent to it)")
    if args.mode == "check" and not args.expect_api:
        p.error("check needs --expect-api")
    return args


def main(argv: list[str] | None = None, transport: Transport = urllib_transport) -> int:
    args = parse_args(argv)
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        print(
            f"no {TOKEN_ENV} in this command's environment. Load it with `read -rs {TOKEN_ENV}` "
            f'(not exported) and prefix only this command: {TOKEN_ENV}="${TOKEN_ENV}" uv run ...'
        )
        return 2
    api = Api(transport, token, args.base)
    try:
        return (
            save(api, args.out, args.known_low_price)
            if args.mode == "save"
            else check(api, args.out, args)
        )
    except RedirectError as e:
        print(f"FAIL: {e}. Redirects are refused, so the token never follows one; check --base.")
        return 1
    except TokenExpiredError as e:
        print(
            f"401 on {e}: the token expired. Refresh {TOKEN_ENV} and re-run this step (not a FAIL)."
        )
        return EXPIRED


if __name__ == "__main__":
    sys.exit(main())
