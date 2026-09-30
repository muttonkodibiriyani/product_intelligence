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


def check_anonymous_denied(project: str) -> list[str]:
    bucket = f"{project}.firebasestorage.app"
    url = f"https://firebasestorage.googleapis.com/v0/b/{bucket}/o/{DATASET}?alt=media"
    status = requests.get(url, timeout=30).status_code
    return [] if status in (401, 403) else [f"anonymous dataset read returned {status}"]


def visit_all(page: Page, base: str, engine: str, out: Path) -> list[str]:
    problems: list[str] = []
    routes = sorted(
        set(
            page.eval_on_selector_all(
                "a[href^='#/']", "els => els.map(e => e.getAttribute('href'))"
            )
        )
        - NOT_SCREENS
    )
    # The landing screen after sign-in counts too, even when nothing links to it.
    landing = "#" + page.url.partition("#")[2]
    if landing != "#" and landing not in NOT_SCREENS and landing not in routes:
        routes.insert(0, landing)
    if not routes:
        problems.append(f"{engine}: no #/ navigation links found after sign-in")
    for route in routes:
        page.goto(f"{base}/{route}")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500)
        text = page.inner_text("body")
        print(f"{engine} {route}: {' '.join(text.split())[:160]}")
        name = route.strip("#/").replace("/", "_") or "root"
        page.screenshot(path=str(out / f"{engine}-{name}.png"), full_page=True)
        if len(text.strip()) < 40:
            problems.append(f"{engine} {route}: near-empty screen ({len(text.strip())} chars)")
        if m := BAD_TEXT.search(text):
            problems.append(f"{engine} {route}: bad text {m.group(0)!r}")
        if page.locator("[data-state='error']").count():
            problems.append(f"{engine} {route}: error state shown")
    print(f"{engine}: visited {len(routes)} routes: {' '.join(routes)}")
    return problems


def run_engine(engine: str, base: str, email: str, password: str, out: Path) -> list[str]:
    problems: list[str] = []
    with sync_playwright() as p:
        browser = getattr(p, engine).launch()
        page = browser.new_context(viewport={"width": 1366, "height": 900}).new_page()
        page.on(
            "console",
            lambda m: (
                problems.append(f"{engine} console.{m.type}: {m.text[:200]}")
                if m.type == "error"
                else None
            ),
        )
        page.on("pageerror", lambda e: problems.append(f"{engine} pageerror: {str(e)[:200]}"))
        page.on(
            "requestfailed",
            lambda r: problems.append(f"{engine} request failed: {r.url[:120]} {r.failure}"),
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
            problems += visit_all(page, base, engine, out)
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
