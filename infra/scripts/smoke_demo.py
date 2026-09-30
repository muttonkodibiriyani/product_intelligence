# /// script
# requires-python = ">=3.12"
# dependencies = ["firebase-admin>=6.5", "playwright==1.63.0", "requests>=2.32"]
# ///
"""Smoke-test the live demo app in real browsers with a throwaway invited user.

1. Access control: anonymous reads of the dataset are refused.
2. Creates a temporary viewer (random password kept in memory, never printed), then per engine:
   signed-out redirect to #/signin, sign in, visit every #/ route, and fail on error states,
   empty screens, console errors or failed requests. Screenshots go to --out.
3. Always deletes the temporary user.

Run in mcr.microsoft.com/playwright/python:v1.63.0-noble with the SA key mounted read-only:
    python infra/scripts/smoke_demo.py --project productintelligence-beeb3 --out <dir>
"""

import argparse
import re
import secrets
import sys
from pathlib import Path

import firebase_admin
import requests
from firebase_admin import auth
from playwright.sync_api import Page, sync_playwright

BAD_TEXT = re.compile(r"\bundefined\b|\bNaN\b|\[object Object\]|Something went wrong", re.I)
DATASET = "datasets%2Fuae%2Flatest.json"
# Routes that are not data screens (visiting sign-out would end the session mid-test).
NOT_SCREENS = {"#/signin", "#/signout", "#/reset"}
# Screens the app documents (ROUTES.txt); one #/product/<id> is added from the explorer.
SCREENS = [
    "#/dashboard",
    "#/explorer",
    "#/pricing",
    "#/promotions",
    "#/assortment",
    "#/availability",
    "#/compare",
    "#/assistant",
    "#/coverage",
]
# Every data screen must carry the cutoff label; real data must never be labelled as mockup/test.
CUTOFF_LABEL = {
    "en": re.compile(r"Source: .+ · Data cutoff \S+"),
    "ar": re.compile(r"آخر تحديث للبيانات \S+"),
}
NOT_REAL = re.compile(
    r"mockup|sample data|TEST FIXTURE|نموذج توضيحي|بيانات تجريبية|بيانات اختبار", re.I
)
# App copy must not promise a daily run; lowercase only, because product names say "Daily".
DAILY = re.compile(r"\bdaily\b")


def check_anonymous_denied(project: str) -> list[str]:
    bucket = f"{project}.firebasestorage.app"
    url = f"https://firebasestorage.googleapis.com/v0/b/{bucket}/o/{DATASET}?alt=media"
    problems = []
    status = requests.get(url, timeout=30).status_code
    if status not in (401, 403):
        problems.append(f"anonymous dataset read returned {status}")
    doc = f"https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents"
    status = requests.get(f"{doc}/demo_meta/current", timeout=30).status_code
    if status not in (401, 403):
        problems.append(f"anonymous Firestore read returned {status}")
    return problems


def product_route(page: Page, base: str) -> str | None:
    page.goto(f"{base}/#/explorer")
    page.wait_for_load_state("networkidle")
    href = page.get_attribute("a[href^='#/product/']", "href", timeout=15_000)
    return href


def visit_all(page: Page, base: str, tag: str, out: Path, where: list[str]) -> list[str]:
    lang = tag.rsplit("-", 1)[1]
    problems: list[str] = []
    linked = page.eval_on_selector_all(
        "a[href^='#/']", "els => els.map(e => e.getAttribute('href'))"
    )
    routes = list(SCREENS)
    routes += sorted(
        {r for r in linked if not r.startswith("#/product/")} - NOT_SCREENS - set(SCREENS)
    )
    if product := product_route(page, base):
        routes.append(product)
    else:
        problems.append(f"{tag}: no #/product/<id> link on #/explorer")
    for route in routes:
        where[0] = f"{tag} {route}"
        page.goto(f"{base}/{route}")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(700)
        text = page.inner_text("body")
        print(f"{tag} {route}: {' '.join(text.split())[:120]}")
        name = route.strip("#/").replace("/", "_") or "root"
        page.screenshot(path=str(out / f"{tag}-{name}.png"), full_page=True)
        if len(text.strip()) < 40:
            problems.append(f"{tag} {route}: near-empty screen ({len(text.strip())} chars)")
        if m := BAD_TEXT.search(text):
            problems.append(f"{tag} {route}: bad text {m.group(0)!r}")
        if page.locator("[data-state='error']").count():
            problems.append(f"{tag} {route}: error state shown")
        if not CUTOFF_LABEL[lang].search(text):
            problems.append(f"{tag} {route}: cutoff label missing")
        if m := NOT_REAL.search(text):
            problems.append(f"{tag} {route}: mockup/test label on real data {m.group(0)!r}")
        if m := DAILY.search(text):
            problems.append(f"{tag} {route}: 'daily' wording {m.group(0)!r}")
    print(f"{tag}: visited {len(routes)} routes: {' '.join(routes)}")
    return problems


def run_engine(engine: str, base: str, email: str, password: str, out: Path) -> list[str]:
    problems: list[str] = []
    where = [engine]  # the screen being visited, so console errors name their route
    with sync_playwright() as p:
        # Chromium in a container needs /dev/shm-free, sandbox-free launch; other engines don't.
        args = (
            ["--no-sandbox", "--disable-dev-shm-usage", "--single-process"]
            if engine == "chromium"
            else []
        )
        browser = getattr(p, engine).launch(args=args)
        try:
            page = browser.new_context(viewport={"width": 1366, "height": 900}).new_page()
        except Exception as exc:
            browser.close()
            return [f"{engine}: could not open a page: {str(exc).splitlines()[0][:200]}"]
        page.on(
            "console",
            lambda m: (
                problems.append(f"{where[0]} console.{m.type}: {m.text[:200]}")
                if m.type == "error"
                else None
            ),
        )
        page.on("pageerror", lambda e: problems.append(f"{where[0]} pageerror: {str(e)[:200]}"))
        page.on(
            "requestfailed",
            lambda r: (
                None
                # A navigation (our language reload / route change) cancels in-flight requests.
                if re.search(r"cancel|abort", str(r.failure), re.I)
                else problems.append(f"{where[0]} request failed: {r.url[:120]} {r.failure}")
            ),
        )
        try:
            page.goto(base + "/")
            page.wait_for_url(re.compile(r"#/signin"), timeout=15_000)
            page.screenshot(path=str(out / f"{engine}-signin.png"))
            page.fill("input[type=email]", email)
            page.fill("input[type=password]", password)
            page.click("button[type=submit]")
            page.wait_for_url(lambda u: "#/signin" not in u, timeout=20_000)
            page.wait_for_load_state("networkidle")
            for lang in ("en", "ar"):
                page.evaluate("l => localStorage.setItem('pi.lang', l)", lang)
                page.goto(f"{base}/#/dashboard")
                page.reload()
                page.wait_for_load_state("networkidle")
                page_dir = page.get_attribute("html", "dir") or ""
                if lang == "ar" and page_dir != "rtl":
                    problems.append(f"{engine}-ar: html dir is {page_dir!r}, expected rtl")
                problems += visit_all(page, base, f"{engine}-{lang}", out, where)
        except Exception as exc:  # record it and keep testing other engines
            page.screenshot(path=str(out / f"{engine}-FAILED.png"), full_page=True)
            problems.append(f"{engine}: {type(exc).__name__}: {str(exc).splitlines()[0][:200]}")
        finally:
            browser.close()
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--base", default="https://productintelligence-beeb3.web.app")
    parser.add_argument("--engines", default="webkit,firefox,chromium")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    problems = check_anonymous_denied(args.project)
    firebase_admin.initialize_app(options={"projectId": args.project})
    email = f"pi-smoke-{secrets.token_hex(4)}@example.com"
    password = secrets.token_urlsafe(24)
    user = auth.create_user(email=email, password=password, email_verified=True)
    try:
        auth.set_custom_user_claims(user.uid, {"role": "viewer"})
        for engine in args.engines.split(","):
            problems += run_engine(engine, args.base, email, password, args.out)
    finally:
        auth.delete_user(user.uid)
        print(f"deleted temporary user {user.uid}")

    for problem in problems:
        print(f"PROBLEM: {problem}")
    print("SMOKE", "FAIL" if problems else "PASS")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
