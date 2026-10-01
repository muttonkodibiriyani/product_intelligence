# /// script
# requires-python = ">=3.12"
# dependencies = ["firebase-admin>=6.5", "playwright==1.63.0", "requests>=2.32"]
# ///
"""Smoke-test the Next app at /app on live Hosting, next to the legacy dashboard at /.

1. Without a user: / is still the legacy dashboard (asset names, optional byte check); /app/ is
   the Next app with exactly the CSP in infra/firebase.json; an unknown /app page is the Next 404;
   /api answers a missing token with a JSON 401.
2. Creates a temporary viewer (random password kept in memory, never printed), then in one engine:
   legacy / signed out, sign in at /app/en/, explorer, a product and back, CSV and JSONL exports
   (name, type, body), the Content-Type guard (a forced text/html answer is not saved), and the
   Arabic explorer (rtl, Latin digits). Any CSP violation, console error, page error or failed
   request is a problem. Screenshots go to --out; downloads are read in memory and never kept.
3. Always deletes the temporary user.

Run in mcr.microsoft.com/playwright/python:v1.63.0-noble from the repo root, SA key mounted :ro.
The image has the browsers but not the Python package, so install all three dependencies:
    pip install "firebase-admin>=6.5" "playwright==1.63.0" "requests>=2.32"
    python infra/scripts/smoke_app.py --project productintelligence-beeb3 \
        --engine firefox --out <dir>
"""

import argparse
import hashlib
import json
import re
import secrets
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import requests
from playwright.sync_api import Page, Response, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

REPO = Path(__file__).resolve().parents[2]
LEGACY_ASSET = re.compile(r"\b(?:app|styles)\.[0-9a-f]{10}\.(?:js|css)\b")
EXPORT_NAME = {
    "csv": re.compile(r"^pi-products-\d{8}T\d{4}Z\.csv$"),
    "jsonl": re.compile(r"^pi-products-\d{8}T\d{4}Z\.jsonl$"),
}
EXPORT_TYPE = {"csv": "text/csv", "jsonl": "application/x-ndjson"}
EXPORT_BUTTON = {"csv": re.compile(r"as CSV$"), "jsonl": re.compile(r"as JSONL$")}
UNREADABLE = "The server sent a response this app can't read."
ARABIC_DIGITS = re.compile("[\u0660-\u0669\u06f0-\u06f9]")
# Turns every CSP block into a console error, which is then reported like any other.
CSP_LISTENER = """
document.addEventListener('securitypolicyviolation', (e) =>
  console.error(`CSP blocked ${e.violatedDirective}: ${e.blockedURI || 'inline'}`));
"""
TIMEOUT = 20_000


def expected_csp() -> str:
    hosting = json.loads((REPO / "infra" / "firebase.json").read_text(encoding="utf-8"))["hosting"]
    for block in hosting["headers"]:
        if block["source"] == "**":
            for h in block["headers"]:
                if h["key"].lower() == "content-security-policy":
                    return str(h["value"])
    raise SystemExit("infra/firebase.json has no CSP on '**'")


def check_public(base: str, legacy_sha256: str | None) -> list[str]:
    problems: list[str] = []
    root = requests.get(f"{base}/", timeout=30)
    assets = sorted(set(LEGACY_ASSET.findall(root.text)))
    print(f"/: {root.status_code}, legacy assets {assets}")
    if root.status_code != 200 or len(assets) != 2:
        problems.append(f"/: status {root.status_code}, legacy assets {assets}")
    if "/app/_next/" in root.text:
        problems.append("/: serves the Next app, not the legacy dashboard")
    if legacy_sha256:
        got = hashlib.sha256(root.content).hexdigest()
        if got != legacy_sha256:
            problems.append(f"/: index.html sha256 {got[:16]}…, expected {legacy_sha256[:16]}…")
    for a in assets:
        if (s := requests.get(f"{base}/{a}", timeout=30).status_code) != 200:
            problems.append(f"/{a}: {s}")

    shell = requests.get(f"{base}/app/en/", timeout=30)
    csp = shell.headers.get("Content-Security-Policy", "")
    hashes = len(re.findall(r"'sha256-", csp))
    print(f"/app/en/: {shell.status_code}, CSP with {hashes} script hashes")
    if shell.status_code != 200 or "/app/_next/" not in shell.text:
        problems.append(f"/app/en/: status {shell.status_code}, Next app not served")
    if csp.strip().rstrip(";") != expected_csp().strip().rstrip(";"):
        problems.append("/app/en/: CSP header differs from infra/firebase.json")

    missing = requests.get(f"{base}/app/en/no-such-page/", timeout=30)
    if 'name="robots" content="noindex"' not in missing.text or "/app/_next/" not in missing.text:
        problems.append(f"/app/en/no-such-page/: not the Next 404 (status {missing.status_code})")

    api = requests.get(f"{base}/api/v1/meta", timeout=30)
    kind = api.headers.get("Content-Type", "")
    print(f"/api/v1/meta without a token: {api.status_code} {kind}")
    if api.status_code != 401 or not kind.startswith("application/json"):
        problems.append(f"/api/v1/meta without a token: {api.status_code} {kind}")
    return problems


def watch(page: Page, problems: list[str], where: list[str]) -> None:
    page.add_init_script(CSP_LISTENER)
    page.on(
        "console",
        lambda m: (
            problems.append(f"{where[0]} console.error: {m.text[:200]}")
            if m.type == "error"
            else None
        ),
    )
    page.on("pageerror", lambda e: problems.append(f"{where[0]} pageerror: {str(e)[:200]}"))
    page.on(
        "requestfailed",
        lambda r: (
            None
            # Navigation and superseded queries cancel in-flight requests; that is not a failure.
            if re.search(r"cancel|abort", str(r.failure), re.I)
            else problems.append(f"{where[0]} request failed: {r.url[:120]} {r.failure}")
        ),
    )


def export(page: Page, fmt: str, problems: list[str]) -> None:
    """One export: the right name, type and body, and a Bearer token on the request."""
    seen: dict[str, Any] = {}

    def on_response(r: Response) -> None:
        if "/api/v1/export/products" in r.url:
            seen["type"] = (r.headers.get("content-type") or "").split(";")[0].strip()
            seen["bearer"] = (r.request.all_headers().get("authorization") or "").startswith(
                "Bearer "
            )

    page.on("response", on_response)
    with page.expect_download(timeout=60_000) as info:
        page.get_by_role("button", name=EXPORT_BUTTON[fmt]).click()
    download = info.value
    name = download.suggested_filename
    body = Path(download.path()).read_bytes()
    download.delete()
    page.remove_listener("response", on_response)
    lines = body.decode("utf-8-sig").splitlines()
    print(f"export {fmt}: {name}, {len(body)} bytes, {len(lines)} lines, type {seen.get('type')}")
    if not EXPORT_NAME[fmt].match(name):
        problems.append(f"export {fmt}: file name {name!r}")
    if seen.get("type") != EXPORT_TYPE[fmt]:
        problems.append(f"export {fmt}: Content-Type {seen.get('type')!r}")
    if not seen.get("bearer"):
        problems.append(f"export {fmt}: request had no Bearer token")
    if body.lstrip(b"\xef\xbb\xbf").lower().startswith((b"<!doctype", b"<html")):
        problems.append(f"export {fmt}: body is HTML")
    if len(lines) < 2:
        problems.append(f"export {fmt}: {len(lines)} lines")
    if fmt == "jsonl":
        for i, line in enumerate(lines[:20]):
            try:
                json.loads(line)
            except ValueError:
                problems.append(f"export jsonl: line {i + 1} is not JSON")
                break
    page.get_by_text(f"Saved {name}.").wait_for(timeout=TIMEOUT)


def sign_in(page: Page, base: str, email: str, password: str) -> None:
    page.goto(f"{base}/")  # the legacy dashboard, signed out
    page.wait_for_url(re.compile(r"#/signin"), timeout=TIMEOUT)
    page.wait_for_load_state("networkidle")
    page.goto(f"{base}/app/en/")
    page.wait_for_url(re.compile(r"/app/en/sign-in/$"), timeout=TIMEOUT)
    page.fill("input[name=email]", email)
    page.fill("input[name=password]", password)
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/app/en/$"), timeout=TIMEOUT)
    page.get_by_role("navigation").wait_for(timeout=TIMEOUT)
    page.wait_for_load_state("networkidle")


def explore_and_product(page: Page, base: str, problems: list[str]) -> None:
    page.goto(f"{base}/app/en/explore/")
    page.get_by_role("table").wait_for(timeout=TIMEOUT)
    if page.get_by_text("Exports stop at 50,000 rows").count():
        # Narrow to the first row's brand so the export stays small.
        brand = page.locator("table tbody tr th span[dir=auto]").first.inner_text()
        page.goto(f"{base}/app/en/explore/?{urlencode({'brand': brand})}")
        page.get_by_role("table").wait_for(timeout=TIMEOUT)
    page.wait_for_load_state("networkidle")
    explore_url = page.url
    page.locator("table tbody tr th a[href*='/product/']").first.click()
    page.wait_for_url(re.compile(r"/app/en/product/\?"), timeout=TIMEOUT)
    page.get_by_role("heading", level=1).wait_for(timeout=TIMEOUT)
    page.wait_for_load_state("networkidle")
    page.get_by_role("link", name="Back to products").click()
    # Wait for the URL, not a table: the product page has one too (its offers).
    try:
        page.wait_for_url(lambda u: same_view(u, explore_url), timeout=TIMEOUT)
    except PlaywrightTimeout:
        problems.append(f"back to products: {page.url} is not {explore_url}")
    page.get_by_role("table").wait_for(timeout=TIMEOUT)


def same_view(a: str, b: str) -> bool:
    """Same path and same decoded query: the app writes a space as + where quote() writes %20."""
    ua, ub = urlsplit(a), urlsplit(b)
    return (ua.path, parse_qs(ua.query)) == (ub.path, parse_qs(ub.query))


def export_guard(page: Page, problems: list[str]) -> None:
    """A 200 that is not the asked-for type (index.html from a mis-routed /api) is not saved."""
    page.route(
        "**/api/v1/export/**",
        lambda r: r.fulfill(status=200, content_type="text/html", body="<!doctype html>"),
    )
    downloads: list[str] = []
    page.on("download", lambda d: downloads.append(d.suggested_filename))
    page.get_by_role("button", name=EXPORT_BUTTON["csv"]).click()
    page.get_by_text(UNREADABLE).wait_for(timeout=TIMEOUT)
    page.wait_for_timeout(1000)
    if downloads:
        problems.append(f"export guard: a text/html answer was saved as {downloads}")
    page.unroute("**/api/v1/export/**")


def arabic(page: Page, base: str, problems: list[str]) -> None:
    page.goto(f"{base}/app/ar/explore/")
    page.get_by_role("table").wait_for(timeout=TIMEOUT)
    page.wait_for_load_state("networkidle")
    if (d := page.get_attribute("html", "dir")) != "rtl":
        problems.append(f"ar: html dir is {d!r}")
    if m := ARABIC_DIGITS.search(page.get_by_role("table").inner_text()):
        problems.append(f"ar: Arabic-Indic digit {m.group(0)!r} in the table")


def run(engine: str, base: str, email: str, password: str, out: Path) -> list[str]:
    problems: list[str] = []
    where = [engine]
    with sync_playwright() as p:
        browser = getattr(p, engine).launch()
        context = browser.new_context(
            viewport={"width": 1366, "height": 900}, accept_downloads=True
        )
        page = context.new_page()
        watch(page, problems, where)
        steps = [
            ("sign-in", lambda: sign_in(page, base, email, password)),
            ("explore-product", lambda: explore_and_product(page, base, problems)),
            ("export-csv", lambda: export(page, "csv", problems)),
            ("export-jsonl", lambda: export(page, "jsonl", problems)),
            ("export-guard", lambda: export_guard(page, problems)),
            ("explore-ar", lambda: arabic(page, base, problems)),
        ]
        try:
            for name, step in steps:
                where[0] = f"{engine} {name}"
                step()
                page.screenshot(path=str(out / f"{engine}-{name}.png"), full_page=True)
                print(f"{where[0]}: ok")
        except Exception as exc:  # record it; the user is still deleted
            page.screenshot(path=str(out / f"{engine}-FAILED.png"), full_page=True)
            problems.append(f"{where[0]}: {type(exc).__name__}: {str(exc).splitlines()[0][:200]}")
        finally:
            browser.close()
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--base", default="https://productintelligence-beeb3.web.app")
    parser.add_argument("--engine", choices=["firefox", "webkit", "chromium"], default="firefox")
    parser.add_argument("--legacy-sha256", help="expected sha256 of / (legacy index.html)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    problems = check_public(args.base, args.legacy_sha256)
    # Imported here so the module (and same_view's test) loads where firebase_admin isn't installed.
    import firebase_admin  # noqa: PLC0415
    from firebase_admin import auth  # noqa: PLC0415

    firebase_admin.initialize_app(options={"projectId": args.project})
    email = f"pi-smoke-{secrets.token_hex(4)}@example.com"
    password = secrets.token_urlsafe(24)
    user = auth.create_user(email=email, password=password, email_verified=True)
    try:
        auth.set_custom_user_claims(user.uid, {"role": "viewer"})
        problems += run(args.engine, args.base, email, password, args.out)
    finally:
        auth.delete_user(user.uid)
        print(f"deleted temporary user {user.uid}")

    for problem in problems:
        print(f"PROBLEM: {problem}")
    print("SMOKE", "FAIL" if problems else "PASS")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
