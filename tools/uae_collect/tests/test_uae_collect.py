"""The incremental collector against a stubbed HTTP client and a local bucket.

Synthetic pages only; no real retailer page is used here.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from capture_read.run import LocalBucket
from page_capture import run as page_capture
from uae_collect import run
from uae_collect.shops import AR, DAILY, FULL, SHOPS
from uae_collect.sitemap import MAX_CHILDREN, parse
from uae_collect.state import IN, OUT, Entry, State

FACES = SHOPS["faces_ae"]
WED = datetime(2026, 10, 7, 20, 0, tzinfo=UTC)  # daily
MON = datetime(2026, 10, 5, 20, 0, tzinfo=UTC)  # full
FIRST = datetime(2026, 11, 1, 20, 0, tzinfo=UTC)  # ar
BASE = "https://www.faces.ae"
INDEX = f"{BASE}/en/sitemap_index.xml"
CHILD = f"{BASE}/en/sitemap_0.xml"
EN = [f"{BASE}/en/p/balm-{n}.html" for n in (1, 2, 3)]
AR_URL = f"{BASE}/ar/p/balm-1.html"
NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def _index(*children: str) -> str:
    locs = "".join(f"<sitemap><loc>{c}</loc></sitemap>" for c in children)
    return f'<?xml version="1.0"?><sitemapindex {NS}>{locs}</sitemapindex>'


def _urlset(urls: Mapping[str, str | None]) -> str:
    body = "".join(
        f"<url><loc>{u}</loc>{f'<lastmod>{m}</lastmod>' if m else ''}</url>"
        for u, m in urls.items()
    )
    return f'<?xml version="1.0"?><urlset {NS}>{body}</urlset>'


def _page(url: str, sku: str) -> str:
    lang = "ar" if "/ar/" in url else "en"
    layer = {
        "event": "view_item",
        "ecommerce": {
            "currency": "AED",
            "value": 215,
            "items": [
                {
                    "item_id": f"PM_{sku}",
                    "item_name": f"Balm {sku}",
                    "item_brand": "Glow",
                    "item_variant": f"20000000000{sku}",
                    "currency": "AED",
                    "price": 215,
                    "item_in_stock": True,
                    "item_category": "Makeup",
                }
            ],
        },
    }
    ld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": f"Balm {sku}",
        "brand": {"@type": "Brand", "name": "Glow"},
        "image": f"https://img.example/{sku}.jpg",
        "sku": sku,
        "offers": {"@type": "Offer", "price": "215.00", "priceCurrency": "AED"},
    }
    return f"""<!doctype html><html lang="{lang}" data-locale="{lang}_AE"><head>
<title>Balm {sku}</title><link rel="canonical" href="{url}">
<script>window.dataLayer=window.dataLayer||[];dataLayer.push({json.dumps(layer)});</script>
<script type="application/ld+json">{json.dumps(ld)}</script></head><body>
<div class="js-product-details product-detail" data-pid="{sku}" data-ready-to-order="true">
<div class="product-name"><span class="js-name">Balm {sku}</span></div></div></body></html>"""


class _Resp:
    def __init__(self, status: int, body: str | bytes, ct: str, url: str) -> None:
        self.status_code = status
        self.content = body if isinstance(body, bytes) else body.encode()
        self.text = self.content.decode("utf-8", "replace")
        self.headers = {"content-type": ct}
        self.url = url


class _Cookies:
    def clear(self) -> None:
        pass


class _Client:
    def __init__(self, routes: dict[str, tuple[int, str | bytes, str]]) -> None:
        self.routes = routes
        self.calls: list[str] = []
        self.cookies = _Cookies()

    def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> _Resp:
        self.calls.append(url)
        if url in self.routes:
            status, body, ct = self.routes[url]
            return _Resp(status, body, ct, url)
        if url.endswith("/robots.txt"):
            return _Resp(200, "User-agent: *\nDisallow: /cart\n", "text/plain", url)
        return _Resp(404, "nope", "text/html", url)


def _site(**over: tuple[int, str | bytes, str]) -> dict[str, tuple[int, str | bytes, str]]:
    xml = "application/xml"
    routes: dict[str, tuple[int, str | bytes, str]] = {
        INDEX: (200, _index(CHILD), xml),
        CHILD: (
            200,
            _urlset(
                {**dict.fromkeys(EN, "2026-10-06"), AR_URL: None, f"{BASE}/en/brands/glow": None}
            ),
            xml,
        ),
    }
    for n, url in enumerate([*EN, AR_URL], 1):
        routes[url] = (200, _page(url, f"00{n}"), "text/html; charset=utf-8")
    return routes | over


def _main(tmp_path: Path, client: _Client, now: datetime, **env: str) -> tuple[int, dict[str, Any]]:
    bucket = LocalBucket(tmp_path)

    def make_job(cfg: page_capture.Config) -> page_capture.Job:
        return page_capture.Job(cfg, client=client, clock=lambda: now, sleep=lambda _s: None)

    code = run.main(
        {"BUCKET": f"file:{tmp_path}", "SHOP": "faces_ae", **env},
        bucket=bucket,
        make_job=make_job,
        now=lambda: now,
    )
    runs = sorted((tmp_path / "runs" / "faces_ae").glob("*/collect.json"))
    return code, json.loads(runs[-1].read_text())


def _state(tmp_path: Path) -> State:
    return State.from_bytes((tmp_path / "state/faces_ae/urls.json.gz").read_bytes())


def _feed(tmp_path: Path, report: dict[str, Any]) -> list[dict[str, Any]]:
    doc: dict[str, Any] = json.loads((tmp_path / report["feed"]).read_text())
    items: list[dict[str, Any]] = doc["items"]
    return items


def _mapping(tmp_path: Path, report: dict[str, Any]) -> dict[str, Any]:
    path = tmp_path / str(report["feed"]).replace(".feed.json", ".mapping.json")
    doc: dict[str, Any] = json.loads(path.read_text())
    return doc


# ------------------------------------------------------------------ shops / sitemap / state


def test_pass_for_date() -> None:
    assert FACES.pass_for(date(2026, 10, 7)) == DAILY
    assert FACES.pass_for(date(2026, 10, 5)) == FULL
    assert FACES.pass_for(date(2026, 10, 8)) == FULL
    assert FACES.pass_for(date(2026, 11, 1)) == AR
    assert FACES.pass_for(date(2027, 2, 1)) == AR  # a Monday: Arabic wins


def test_lang_matches_product_pages_only() -> None:
    assert FACES.lang(EN[0]) == "en"
    assert FACES.lang(AR_URL) == "ar"
    for url in (
        f"{BASE}/en/brands/glow",
        f"{BASE}/en/p/x.html?y=1",
        "https://faces.ae/en/p/x.html",
    ):
        assert FACES.lang(url) is None


def test_parse_sitemaps() -> None:
    assert parse(_index(CHILD)).children == (CHILD,)
    doc = parse(_urlset({EN[0]: "2026-10-06", EN[1]: None}))
    assert doc.urls == {EN[0]: "2026-10-06", EN[1]: None}
    for bad in ("<html><body>challenge</body></html>", "not xml at all", ""):
        with pytest.raises(ValueError, match="not a sitemap"):
            parse(bad)
    with pytest.raises(ValueError, match="children"):
        parse(_index(*[f"{BASE}/s{n}.xml" for n in range(MAX_CHILDREN + 1)]))


def test_parse_refuses_entities() -> None:
    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><urlset>&a;</urlset>'
    with pytest.raises(Exception):  # noqa: B017, PT011 - defusedxml's own error type
        parse(bomb)


def test_state_select_and_record() -> None:
    listed = {EN[0]: "a", EN[1]: "b", EN[2]: None, AR_URL: None}
    state = State(
        {
            EN[0]: Entry(read="2026-10-01", lastmod="old", scope=IN),
            EN[2]: Entry(read="2026-10-01", scope=OUT),
        }
    )
    assert state.select(FACES, DAILY, listed) == [EN[1]]  # lastmod is not a signal for Faces
    assert state.select(FACES, FULL, listed) == [EN[0], EN[1]]  # never the out-of-scope one
    assert state.select(FACES, AR, listed) == [AR_URL]
    shop = type(FACES)(**{**vars(FACES), "use_lastmod": True})
    assert state.select(shop, DAILY, listed) == [EN[0], EN[1]]
    state.record("2026-10-07", listed, [EN[1]], [EN[0]])
    assert state.urls[EN[1]] == Entry(read="2026-10-07", lastmod="b", scope=IN, listed="2026-10-07")
    assert state.urls[EN[0]].scope == OUT
    gone = f"{BASE}/en/p/gone.html"
    state.urls[gone] = Entry(read="2026-09-01", scope=IN, listed="2026-09-01")
    state.record("2026-10-08", {EN[1]: "b"}, [], [])
    assert state.urls[EN[1]].listed == "2026-10-08"
    assert state.urls[EN[0]].listed == "2026-10-07"  # not listed today: keeps its last day
    assert state.known(FACES, "en", "2026-10-01") == {EN[1]}  # in scope and listed since
    assert state.known(FACES, "en", "2026-09-01") == {EN[1], gone}
    assert State.from_bytes(state.to_bytes()) == state


def test_state_rejects_unknown_version() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        State.from_bytes(gzip.compress(b'{"version": 9, "urls": {}}'))


def test_config_from_env() -> None:
    env = {"BUCKET": "b", "SHOP": "faces_ae"}
    assert run.config_from_env(env, WED).run_pass == DAILY
    assert run.config_from_env(env | {"PASS": "ar"}, WED).run_pass == AR
    cfg = run.config_from_env(env, MON)
    assert cfg.prefix == "runs/faces_ae/2026-10-05T200000Z-full"
    for bad in ({"SHOP": "nope"}, {"PASS": "weekly"}, {"HOURS": "0"}, {"MAX_ITEMS": "0"}):
        with pytest.raises(ValueError):  # noqa: PT011
            run.config_from_env(env | bad, WED)


# ----------------------------------------------------------------------------------- runs


def test_daily_run_reads_new_urls_and_feeds_them(tmp_path: Path) -> None:
    client = _Client(_site())
    code, report = _main(tmp_path, client, WED)
    assert code == 0
    assert report["outcome"] == run.OK
    assert report["counts"]["listed"] == 4  # product pages only, both languages
    assert report["counts"]["planned"] == 3
    assert report["counts"]["pages_read"] == 3
    assert AR_URL not in client.calls
    items = _feed(tmp_path, report)
    assert sorted(i["listing_key"] for i in items) == ["001", "002", "003"]
    assert _mapping(tmp_path, report)["complete_catalogue"] is False  # a daily pass never is
    assert {u: e.read for u, e in _state(tmp_path).urls.items()} == dict.fromkeys(EN, "2026-10-07")
    assert all(r.startswith("https://www.faces.ae/en/") for r in client.calls[3:])  # no images

    # the next day has nothing new: no page is fetched, nothing is fed
    nxt = datetime(2026, 10, 9, 20, 0, tzinfo=UTC)  # a Friday
    client2 = _Client(_site())
    code, report = _main(tmp_path, client2, nxt)
    assert (code, report["outcome"], report["feed"]) == (0, run.NOTHING, None)
    assert not [u for u in client2.calls if "/p/" in u]


def test_full_pass_with_no_gap_is_complete(tmp_path: Path) -> None:
    code, report = _main(tmp_path, _Client(_site()), MON)
    assert (code, report["outcome"], report["complete_catalogue"]) == (0, run.OK, True)
    assert _mapping(tmp_path, report)["complete_catalogue"] is True


def test_full_pass_on_a_shrunken_sitemap_is_not_complete(tmp_path: Path) -> None:
    code, report = _main(tmp_path, _Client(_site()), MON)
    assert report["complete_catalogue"] is True
    # a week on, the sitemap lists one of the three products and every page it lists reads ok
    short = _urlset({EN[0]: "2026-10-06", AR_URL: None})
    nxt = MON + timedelta(days=7)
    code, report = _main(tmp_path, _Client(_site(**{CHILD: (200, short, "application/xml")})), nxt)
    assert (code, report["outcome"]) == (0, run.OK)
    assert (report["counts"]["known_in_scope"], report["counts"]["known_unlisted"]) == (3, 2)
    assert report["complete_catalogue"] is False
    assert "no longer lists 2 of 3" in report["reason"]
    assert _mapping(tmp_path, report)["complete_catalogue"] is False


def test_full_pass_baseline_forgets_urls_unlisted_for_two_weeks(tmp_path: Path) -> None:
    _main(tmp_path, _Client(_site()), MON)
    short = _urlset({EN[0]: "2026-10-06", AR_URL: None})
    later = MON + timedelta(days=run.BASELINE_DAYS + 7)  # a Monday: full
    code, report = _main(
        tmp_path, _Client(_site(**{CHILD: (200, short, "application/xml")})), later
    )
    assert (code, report["counts"]["known_unlisted"], report["complete_catalogue"]) == (0, 0, True)


@pytest.mark.parametrize(
    "child", ["http://www.faces.ae/en/sitemap_1.xml", "https://evil.example/en/sitemap_1.xml"]
)
def test_sitemap_index_child_off_the_shop_host_is_refused(tmp_path: Path, child: str) -> None:
    client = _Client(_site(**{INDEX: (200, _index(CHILD, child), "application/xml")}))
    code, report = _main(tmp_path, client, WED)
    assert (code, report["outcome"]) == (run.EXIT_FAILED, run.ERROR)
    assert "off the shop's https host" in report["reason"]
    assert child not in client.calls
    assert not [u for u in client.calls if "/p/" in u]


def test_block_stops_the_run_and_leaves_unread_pages_unadvanced(tmp_path: Path) -> None:
    client = _Client(_site(**{EN[1]: (403, "Access Denied", "text/html")}))
    code, report = _main(tmp_path, client, MON)
    assert code == run.EXIT_FAILED
    assert report["outcome"] == run.BLOCKED
    assert report["complete_catalogue"] is False
    assert EN[2] not in client.calls  # the host stopped at the block
    assert [i["listing_key"] for i in _feed(tmp_path, report)] == ["001"]
    assert _mapping(tmp_path, report)["complete_catalogue"] is False
    assert set(_state(tmp_path).urls) == {EN[0]}  # the others stay due for the next run


def test_sitemap_block_plans_nothing(tmp_path: Path) -> None:
    client = _Client(_site(**{CHILD: (403, "Access Denied", "text/html")}))
    code, report = _main(tmp_path, client, WED)
    assert (code, report["outcome"]) == (run.EXIT_FAILED, run.BLOCKED)
    assert "sitemap_0.xml: blocked" in report["reason"]
    assert not [u for u in client.calls if "/p/" in u]
    assert not (tmp_path / "state").exists()
    assert not (tmp_path / "feeds").exists()


def test_sitemap_disallowed_by_robots_is_not_fetched(tmp_path: Path) -> None:
    routes = _site(**{f"{BASE}/robots.txt": (200, "User-agent: *\nDisallow: /en/\n", "text/plain")})
    client = _Client(routes)
    code, report = _main(tmp_path, client, WED)
    assert (code, report["outcome"]) == (run.EXIT_FAILED, run.ERROR)
    assert "robots disallowed" in report["reason"]
    assert client.calls == [f"{BASE}/robots.txt"]


def test_gzipped_sitemap(tmp_path: Path) -> None:
    child = _site()[CHILD]
    client = _Client(
        _site(**{CHILD: (200, gzip.compress(str(child[1]).encode()), "application/x-gzip")})
    )
    code, report = _main(tmp_path, client, WED)
    assert (code, report["counts"]["listed"]) == (0, 4)


def test_max_items_cuts_and_marks_the_run_partial(tmp_path: Path) -> None:
    code, report = _main(tmp_path, _Client(_site()), MON, MAX_ITEMS="2")
    assert code == 0
    assert report["outcome"] == run.CUTOFF
    assert (report["counts"]["selected"], report["counts"]["planned"]) == (3, 2)
    assert report["complete_catalogue"] is False


def test_arabic_pass_is_read_but_not_fed(tmp_path: Path) -> None:
    client = _Client(_site())
    code, report = _main(tmp_path, client, FIRST)
    assert (code, report["run_pass"], report["feed"]) == (0, AR, None)
    assert [u for u in client.calls if "/p/" in u] == [AR_URL]
    assert set(_state(tmp_path).urls) == {AR_URL}
