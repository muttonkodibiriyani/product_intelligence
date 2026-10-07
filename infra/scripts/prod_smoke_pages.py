# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright==1.63.0"]
# ///
"""The owner's read-only page smoke for a main → prod deploy (P1-P6 in the deploy runbook).

It opens a HEADED browser in a fresh, non-persistent context. The OWNER signs IN by hand, first at
/app/en/ and then on the root dashboard's own sign-in (the root keeps a separate session). The
script never signs up, never creates or deletes a user, never types or sees a password, and never
reads PI_TOKEN. It records no trace, no HAR, no storage state, no cookies and no request headers.
It writes screenshots and one JSON verdict under --out. The screenshots show the owner's signed-in
account: they stay on the owner's machine and are never published, attached or committed.

  P1 / (root) EN + AR: document 200, signed in, dir=rtl for AR, no console/CSP errors, and the
     #/explorer thumbnails come from the allowed image hosts only
  P2 /app/{en,ar}/ landing, compare, promotions, launches: 200, every /api/v1 call < 400, no alert
  P3 /app/en/explore/?retailer=<rid> per retailer: rows > 0, >= 1 thumbnail loaded, 0 CSP blocks
     (every retailer in IMAGE_HOSTS; --retailer narrows it for a deploy that predates one)
  P4 the first Ulta product: gallery images load, all from media.alshaya.com, 0 CSP blocks
  P5 no rendered price of AED 0.00 / 0.01 (Latin or Arabic-Indic digits) on the P3/P4 pages
  P6 --category-page, the /prices page (EN + AR): 200, every /api/v1 call < 400, no alert, and
     section#p-buckets holds its "9 shared categories" meta line and exactly 9 category rows
     (the table at desktop width, the card list on a phone); a "not available yet" note FAILs

--phase before records P4-P6 as info, since live may not have the gallery or category page yet
and the two known AED 0.01 prices are still served. --phase after enforces all six.

One-time browser install (no project access):
  uvx --from playwright==1.63.0 playwright install firefox webkit
  uv run --locked --script infra/scripts/prod_smoke_pages.py --phase after --out "$W/shots" \\
      --browser firefox --viewport desktop --category-page /app/en/prices/
Exit codes: 0 PASS, 1 FAIL, 2 usage.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.sync_api import ConsoleMessage, Page, Response

BASE = "https://productintelligence-beeb3.web.app"
APP_PAGES = [
    f"/app/{loc}/{view}"
    for loc in ("en", "ar")
    for view in ("", "compare/", "promotions/", "launches/")
]
#: ``None``: no image host is verified yet (Ounass, 2026-10-07): P3 then expects no thumbnail.
IMAGE_HOSTS: dict[str, str | None] = {
    "sephora_me": "img-product.sephora.me",
    "ulta_ae": "media.alshaya.com",
    "faces_ae": "www.faces.ae",
    "ounass_ae": None,
    "bloomingdales_ae": "prodheadless.atgwasl.com",
}
VIEWPORTS = {"desktop": {"width": 1440, "height": 900}, "mobile": {"width": 390, "height": 844}}
BROWSERS = ("firefox", "webkit")
TIMEOUT = 20_000
SIGN_IN_WAIT = 300_000  # the owner signs in by hand
ROUTE_ANNOUNCER = "__next-route-announcer__"  # Next's always-present, empty role=alert
CSP_LISTENER = """
document.addEventListener('securitypolicyviolation', (e) =>
  console.error(`CSP blocked ${e.violatedDirective}: ${e.blockedURI || 'inline'}`));
"""
ROOT_THUMBS_JS = """allowed => {
  const imgs = [...document.querySelectorAll('img')]
    .filter(i => /^https?:/.test(i.src) && new URL(i.src).origin !== location.origin);
  const foreign = [...new Set(imgs.map(i => new URL(i.src).host)
    .filter(h => !allowed.includes(h)))];
  const photos = [...document.querySelectorAll('img.pphoto')];
  return {foreign, photos: photos.length,
          broken: photos.filter(i => i.complete && i.naturalWidth === 0 && !i.hidden
                                && i.offsetParent).length};
}"""
IMAGES_JS = "els => els.map(e => ({src: e.src, ok: e.complete && e.naturalWidth > 0}))"
BUCKETS_JS = """() => {
  const s = document.querySelector('section#p-buckets');
  if (!s) return null;
  const shown = e => e.getClientRects().length > 0;
  return {text: s.innerText,
          rows: [...s.querySelectorAll('table tbody th[scope=row]')].filter(shown).length,
          cards: [...s.querySelectorAll('ul > li h3')].filter(shown).length,
          notes: [...s.querySelectorAll('[role=note]')].map(n => n.innerText.slice(0, 120))};
}"""
#: The /prices page's category section (FE P3): its loaded-data meta line and row count.
BUCKETS = 9
BUCKETS_META = {
    "en": "Full catalogues · 9 shared categories ·",
    "ar": "الكتالوج الكامل · 9 فئات مشتركة ·",
}
PHONE_MAX_WIDTH = 639  # the page switches the table for a card list below 640 px

# ------------------------------------------------------------------ pure logic (unit-tested)

# Arabic-Indic (U+0660) and extended (U+06F0) digits, the Arabic decimal and thousands separators
_DIGITS = {
    **{0x660 + i: str(i) for i in range(10)},
    **{0x6F0 + i: str(i) for i in range(10)},
    0x66B: ".",
    0x66C: ",",
}
_CURRENCY = r"(?:AED|د\.?\s?إ\.?)"
_ZERO = r"(?<![\d.,])0[.,]0[01](?![\d])"
_LOW_PRICE = re.compile(rf"{_CURRENCY}\s*{_ZERO}|{_ZERO}\s*{_CURRENCY}")


def low_prices(text: str) -> list[str]:
    """Rendered AED 0.00 / 0.01 amounts (Latin or Arabic-Indic digits), currency on either side."""
    normal = (
        text.translate(_DIGITS).replace("\u00a0", " ").replace("\u200f", "").replace("\u200e", "")
    )
    return [m.group(0) for m in _LOW_PRICE.finditer(normal)]


def bucket_problems(state: dict[str, Any] | None, locale: str, width: int) -> list[str]:
    """P6: the category section rendered with data in the layout this viewport should show."""
    if state is None:
        return ["no section#p-buckets"]
    bad = [f"note: {n!r}" for n in state["notes"]]
    text = " ".join(state["text"].translate(_DIGITS).split())
    if BUCKETS_META[locale] not in text:
        bad.append(f"no {BUCKETS_META[locale]!r} line")
    shown, hidden = ("cards", "rows") if width <= PHONE_MAX_WIDTH else ("rows", "cards")
    if state[shown] != BUCKETS:
        bad.append(f"{state[shown]} category {shown}, want {BUCKETS}")
    if state[hidden]:
        bad.append(f"{state[hidden]} category {hidden} shown at {width}px")
    return bad


def off_host(urls: list[str], host: str) -> list[str]:
    return [u for u in urls if not u.startswith(f"https://{host}/")]


def shot_name(phase: str, browser: str, viewport: str, what: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", what.lower()).strip("-") or "root"
    return f"{phase}-{browser}-{viewport}-{slug}.png"


@dataclass
class Report:
    phase: str
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def check(self, check: str, bad: list[str], *, enforced: bool = True) -> None:
        """Record one P-check: a FAIL when enforced, otherwise an info note (phase before)."""
        if not bad:
            print(f"ok     {check}")
            return
        line = f"{check}: {'; '.join(bad)}"
        if enforced:
            self.problems.append(line)
            print(f"FAIL   {line}")
        else:
            self.notes.append(line)
            print(f"info   {line}")

    def verdict(self) -> str:
        return "FAIL" if self.problems else "PASS"


# ------------------------------------------------------------------ browser checks


@dataclass
class Watch:
    """Console errors (CSP violations included) and failed /api/v1 calls while one page loads."""

    errors: list[str] = field(default_factory=list)
    api: list[str] = field(default_factory=list)

    def on_console(self, m: ConsoleMessage) -> None:
        if m.type == "error":
            self.errors.append(m.text[:200])

    def on_response(self, r: Response) -> None:
        if "/api/v1/" in r.url and r.status >= 400:  # the path only, never the query
            self.api.append(f"{r.status} {r.url.split('/api/v1', 1)[1].split('?', 1)[0][:120]}")


def visit(page: Page, url: str, shot: Path, *, reload: bool = False) -> tuple[int | None, Watch]:
    """Load one URL (reload: a hash-only goto does not reload), settle, screenshot."""
    w = Watch()
    page.on("console", w.on_console)
    page.on("response", w.on_response)
    try:
        doc = page.goto(url)
        if reload:
            doc = page.reload()
        page.wait_for_load_state("networkidle", timeout=TIMEOUT * 2)
        page.wait_for_timeout(1000)
        page.screenshot(path=str(shot), full_page=True)
    finally:
        page.remove_listener("console", w.on_console)
        page.remove_listener("response", w.on_response)
    return (doc.status if doc else None), w


def alerts(page: Page) -> list[str]:
    found = [(a.get_attribute("id"), a.inner_text()[:160]) for a in page.get_by_role("alert").all()]
    return [f"alert: {t or '<empty>'!r}" for i, t in found if i != ROUTE_ANNOUNCER]


def app_page(page: Page, path: str, shot: Path) -> list[str]:
    status, w = visit(page, BASE + path, shot)
    bad = [] if status == 200 else [f"document {status}"]
    if "/sign-in" in page.url:
        bad.append("redirected to sign-in")
    if "/app/_next/" not in page.content():
        bad.append("Next app not served")
    return bad + alerts(page) + [f"api {a}" for a in w.api] + [f"console: {e}" for e in w.errors]


def wait_for_owner(page: Page, what: str, done: str) -> None:
    print(
        f">>> Sign IN by hand in the browser window ({what}). "
        f"Waiting up to {SIGN_IN_WAIT // 60_000} min."
    )
    page.wait_for_function(done, timeout=SIGN_IN_WAIT)
    page.wait_for_load_state("networkidle", timeout=TIMEOUT * 2)


def p1_root(page: Page, rep: Report, out: Callable[[str], Path]) -> None:
    page.goto(BASE + "/#/signin")
    wait_for_owner(
        page,
        "root dashboard",
        "() => !location.hash.startsWith('#/signin')"
        " && !document.querySelector('form[data-signin]')",
    )
    allowed = [host for host in IMAGE_HOSTS.values() if host]
    for lang in ("en", "ar"):
        page.evaluate(f"() => localStorage.setItem('pi.lang', '{lang}')")
        status, w = visit(
            page, BASE + "/#/dashboard", out(f"root-{lang}"), reload=True
        )  # lang is read at load
        bad = [] if status in (200, None) else [f"document {status}"]
        if page.locator("form[data-signin]").count():
            bad.append("shows the sign-in form")
        rtl = page.evaluate("() => document.documentElement.dir")
        if (lang == "ar") != (rtl == "rtl"):
            bad.append(f"dir={rtl!r}")
        _, wx = visit(page, BASE + "/#/explorer", out(f"root-{lang}-explorer"), reload=True)
        th = page.evaluate(ROOT_THUMBS_JS, allowed)
        if th["foreign"]:
            bad.append(f"explorer images from {th['foreign']}")
        if th["broken"]:
            bad.append(f"explorer: {th['broken']} broken photos")
        bad += [f"console: {e}" for e in w.errors + wx.errors]
        rep.check(f"P1 root {lang}", bad)
    page.evaluate("() => localStorage.setItem('pi.lang', 'en')")


def thumbnail_problems(imgs: Sequence[Mapping[str, Any]], host: str | None) -> list[str]:
    """P3's image check over the page's https images (``IMAGES_JS``): >= 1 thumbnail loaded
    from ``host``; with no verified host (``None``), no image from outside the app at all."""
    if host is None:
        return [
            f"image with no verified host: {str(i['src'])[:100]}"
            for i in imgs
            if not str(i["src"]).startswith(BASE)
        ]
    mine = [i for i in imgs if str(i["src"]).startswith(f"https://{host}/")]
    return [] if any(i["ok"] for i in mine) else [f"no {host} thumbnail loaded"]


def p3_to_p5(page: Page, rep: Report, out: Callable[[str], Path], retailers: Sequence[str]) -> None:
    after = rep.phase == "after"
    for rid in retailers:
        host = IMAGE_HOSTS[rid]
        status, w = visit(page, f"{BASE}/app/en/explore/?retailer={rid}", out(f"explore-{rid}"))
        rows = page.locator("tbody tr").count()
        csp = [e for e in w.errors if "CSP blocked" in e]
        bad = [] if status == 200 else [f"document {status}"]
        bad += [] if rows else ["no rows"]
        bad += thumbnail_problems(
            page.eval_on_selector_all('img[src^="https://"]', IMAGES_JS), host
        )
        rep.check(
            f"P3 explore {rid}", bad + [f"csp: {c}" for c in csp] + [f"api {a}" for a in w.api]
        )
        rep.check(
            f"P5 explore {rid}",
            [f"rendered {p}" for p in low_prices(page.inner_text("body"))],
            enforced=after,
        )
        if rid != "ulta_ae" or host is None:
            continue
        href = page.eval_on_selector_all(
            "tbody tr a[href*='/product']", "els => els.length ? els[0].getAttribute('href') : null"
        )
        if not href:
            rep.check("P4 ulta_ae product gallery", ["no product link on explore"], enforced=after)
            continue
        _, wp = visit(page, BASE + href if href.startswith("/") else href, out("product-ulta"))
        gallery = page.eval_on_selector_all("img[src^='https://']", IMAGES_JS)
        external = [g["src"] for g in gallery if not g["src"].startswith(BASE)]
        bad = (
            []
            if any(g["ok"] for g in gallery if g["src"].startswith(f"https://{host}/"))
            else ["no gallery image loaded"]
        )
        bad += [f"image off {host}: {u[:100]}" for u in off_host(external, host)]
        bad += [f"csp: {c}" for c in wp.errors if "CSP blocked" in c]
        rep.check("P4 ulta_ae product gallery", bad, enforced=after)
        rep.check(
            "P5 ulta_ae product",
            [f"rendered {p}" for p in low_prices(page.inner_text("body"))],
            enforced=after,
        )


def run(args: argparse.Namespace) -> Report:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415 (tests need no browser)

    rep = Report(args.phase)
    args.out.mkdir(parents=True, exist_ok=True)

    def out(what: str) -> Path:
        return Path(args.out) / shot_name(args.phase, args.browser, args.viewport, what)

    with sync_playwright() as pw:
        browser = getattr(pw, args.browser).launch(headless=False)
        # Fresh and non-persistent; nothing about the session is recorded or saved.
        context = browser.new_context(viewport=VIEWPORTS[args.viewport])
        page = context.new_page()
        page.add_init_script(CSP_LISTENER)
        try:
            page.goto(BASE + "/app/en/")
            wait_for_owner(
                page,
                "/app/en/",
                "() => /\\/app\\/en\\/$/.test(location.pathname)"
                " && !!document.querySelector('nav')",
            )
            for path in APP_PAGES:
                rep.check(f"P2 {path}", app_page(page, path, out(path)))
            p3_to_p5(page, rep, out, args.retailer or list(IMAGE_HOSTS))
            for loc in ("en", "ar"):
                cat = (
                    args.category_page.replace("/app/en/", f"/app/{loc}/")
                    if args.category_page
                    else None
                )
                bad = ["no --category-page given"]
                if cat:
                    bad = app_page(page, cat, out(f"category-{loc}"))
                    state = page.evaluate(BUCKETS_JS)
                    bad += bucket_problems(state, loc, VIEWPORTS[args.viewport]["width"])
                rep.check(f"P6 category {loc}", bad, enforced=args.phase == "after")
            p1_root(page, rep, out)
        except Exception as exc:
            page.screenshot(path=str(out("FAILED")), full_page=True)
            rep.check("run", [f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"])
        finally:
            context.close()
            browser.close()
    return rep


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--phase", choices=("before", "after"), required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--browser", choices=BROWSERS, required=True)
    p.add_argument("--viewport", choices=sorted(VIEWPORTS), required=True)
    p.add_argument(
        "--category-page",
        help="the /app/en/ path of the category page (required for --phase after)",
    )
    p.add_argument(
        "--retailer",
        action="append",
        choices=sorted(IMAGE_HOSTS),
        default=None,
        help="P3-P5 only these retailers (repeatable; default: all of IMAGE_HOSTS)",
    )
    args = p.parse_args(argv)
    if args.phase == "after" and not args.category_page:
        p.error("--phase after needs --category-page")
    if args.category_page and not args.category_page.startswith("/app/en/"):
        p.error("--category-page must start with /app/en/")
    return args


def main(
    argv: list[str] | None = None, runner: Callable[[argparse.Namespace], Report] = run
) -> int:
    args = parse_args(argv)
    rep = runner(args)
    result: dict[str, Any] = {
        "phase": args.phase,
        "browser": args.browser,
        "viewport": args.viewport,
        "verdict": rep.verdict(),
        "problems": rep.problems,
        "notes": rep.notes,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"pages-{args.phase}-{args.browser}-{args.viewport}.json"
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False))
    print(
        f"PROD PAGE SMOKE {rep.verdict()} ({len(rep.problems)} problems, "
        f"{len(rep.notes)} notes) → {path}"
    )
    return 0 if rep.verdict() == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
