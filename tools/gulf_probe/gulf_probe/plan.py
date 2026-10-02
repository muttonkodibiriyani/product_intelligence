"""What the probe requests. Pure: URL construction and selection only."""

import json
from dataclasses import dataclass
from typing import Final

SEPHORA: Final = "https://www.sephora.me"
ULTA: Final = "https://www.ulta.ae"
SEPHORA_AE_LOCALES: Final = ("en-AE", "ar-AE")
SEPHORA_PRODUCT_SITEMAPS_PER_LOCALE: Final = 40
MAX_PDPS: Final = 3

USER_AGENT: Final = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)


@dataclass(frozen=True, slots=True)
class Target:
    """One URL the probe fetches, with the reason it is in the plan."""

    site: str
    step: str
    url: str
    kind: str  # html | xml | json | image | text
    locale: str


def browser_headers(locale: str, kind: str) -> dict[str, str]:
    """Ordinary browser-like request headers (no cookies, no credentials, no impersonation)."""
    accept = {
        "html": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "xml": "application/xml,text/xml;q=0.9,*/*;q=0.8",
        "json": "application/json,text/plain,*/*",
        "image": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }.get(kind, "*/*")
    lang = "ar-AE,ar;q=0.9,en;q=0.8" if locale.startswith("ar") else "en-AE,en;q=0.9,ar;q=0.8"
    return {"User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": lang}


def sephora_product_sitemaps() -> list[Target]:
    """All UAE product slug sitemaps (en-AE and ar-AE, 40 files each)."""
    return [
        Target(
            "sephora",
            "sitemap_product",
            f"{SEPHORA}/sitemap/{loc}/catalog/productSlugsCO-{i}.xml",
            "xml",
            loc,
        )
        for loc in SEPHORA_AE_LOCALES
        for i in range(SEPHORA_PRODUCT_SITEMAPS_PER_LOCALE)
    ]


def sephora_fixed() -> list[Target]:
    """Robots, sitemap index, one category sitemap and the two locale home pages."""
    return [
        Target("sephora", "robots", f"{SEPHORA}/robots.txt", "text", "en-AE"),
        Target("sephora", "sitemap_index", f"{SEPHORA}/sitemap.xml", "xml", "en-AE"),
        Target(
            "sephora",
            "sitemap_category",
            f"{SEPHORA}/sitemap/en-AE/catalog/categorySlugsCO-0.xml",
            "xml",
            "en-AE",
        ),
        Target("sephora", "home", f"{SEPHORA}/ae-en/", "html", "en-AE"),
        Target("sephora", "home", f"{SEPHORA}/ae-ar/", "html", "ar-AE"),
    ]


def ulta_fixed() -> list[Target]:
    """Robots, sitemap index and the two locale home pages."""
    return [
        Target("ulta", "robots", f"{ULTA}/robots.txt", "text", "en-AE"),
        Target("ulta", "sitemap_index", f"{ULTA}/sitemap.xml", "xml", "en-AE"),
        Target("ulta", "home", f"{ULTA}/en/", "html", "en-AE"),
        Target("ulta", "home", f"{ULTA}/ar/", "html", "ar-AE"),
    ]


def pick(locs: list[str], n: int, *, contains: str = "") -> list[str]:
    """First ``n`` distinct locations containing ``contains``, spread across the list."""
    matching = list(dict.fromkeys(u for u in locs if contains in u))
    if len(matching) <= n:
        return matching
    step = len(matching) // n
    return [matching[i * step] for i in range(n)]


def is_json_api(url: str, content_type: str) -> bool:
    """A page-loaded JSON call worth recording (first-party BFF or search backend)."""
    return "json" in content_type.lower() and not url.endswith((".js", ".css"))


# ---------------------------------------------------------------------- v2: staged matrix
@dataclass(frozen=True, slots=True)
class Client:
    """One ordinary client: plain httpx, or a stock Playwright engine (no stealth patches)."""

    engine: str  # http | chromium | firefox | webkit
    headless: bool = True
    device: str = "desktop"  # desktop | mobile

    @property
    def label(self) -> str:
        if self.engine == "http":
            return "plain_http"
        mode = "headless" if self.headless else "headed"
        return f"{self.engine}-{mode}-{self.device}"


# Playwright built-in device descriptors used for the mobile variants (stock, not spoofed).
MOBILE_DEVICE: Final = {"chromium": "Pixel 7", "webkit": "iPhone 14"}
HTTP: Final = Client("http")
CHROMIUM_HEADLESS: Final = Client("chromium")
STAGE2_CLIENTS: Final = (
    Client("firefox"),
    Client("webkit"),
    Client("chromium", headless=False),
    Client("firefox", headless=False),
    Client("chromium", device="mobile"),
    Client("webkit", device="mobile"),
)


def parse_client(label: str) -> Client:
    """Inverse of :attr:`Client.label`; rejects anything outside the allowed engine set."""
    if label == "plain_http":
        return HTTP
    engine, mode, device = label.split("-")
    if engine not in ("chromium", "firefox", "webkit") or mode not in ("headless", "headed"):
        raise ValueError(label)
    if device not in ("desktop", "mobile") or (device == "mobile" and engine == "firefox"):
        raise ValueError(label)
    return Client(engine, headless=mode == "headless", device=device)


def parse_spec(raw: str) -> list[tuple[Target, Client]]:
    """Explicit stage plan: JSON list of {site, step, url, kind, locale, clients: [label]}."""
    rows: list[tuple[Target, Client]] = []
    for item in json.loads(raw):
        target = Target(item["site"], item["step"], item["url"], item["kind"], item["locale"])
        rows += [(target, parse_client(label)) for label in item["clients"]]
    return rows


def search_targets() -> list[Target]:
    """One search page per site (Sephora's search path is owner-approved despite robots)."""
    return [
        Target("sephora", "search", f"{SEPHORA}/ae-en/search?q=lipstick", "html", "en-AE"),
        Target("ulta", "search", f"{ULTA}/en/search?keywords=lipstick", "html", "en-AE"),
    ]


def usable(fields: dict[str, bool] | None, xhr_fields: list[dict[str, bool] | None]) -> bool:
    """Usable product data = a price came back, from JSON-LD/embedded HTML or a page JSON call."""
    if fields and fields.get("price"):
        return True
    return any(f and f.get("price") for f in xhr_fields)
