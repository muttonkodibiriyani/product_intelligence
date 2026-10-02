"""Picture pass helpers and the IMAGES/RAW/FULL/COUNTRY options, with a stubbed client."""

import gzip
import json
import random
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sephora_snapshot import extract, images, run
from sephora_synth import details, pdp_html

HOST = "img-product.example"
CDN = f"https://{HOST}/dw/image/v2/X/on/demandware.static/-/Sites-x/default/dw1/p"


def _details_with_pictures(pid: str) -> dict[str, Any]:
    d = details(pid)
    d["images"] = [{"disBaseLink": f"{CDN}/{pid}_1.jpg?sw=1248", "link": "https://origin/x.jpg"}]
    d["c_variantsInfo"][0]["images"] = [
        {"disBaseLink": f"{CDN}/{pid}_1.jpg?sw=1248"},  # same as the product picture
        {"link": f"{CDN}/{pid}_2.jpg"},  # no CDN link: the origin link is used
    ]
    d["c_variantsInfo"][0]["swatchImage"] = f"{CDN}/{pid}_sw.jpg?sw=53"
    d["setProducts"] = [{"images": [{"disBaseLink": f"{CDN}/set.jpg"}]}]
    return d


def test_image_urls_are_distinct_and_in_page_order() -> None:
    got = images.image_urls(_details_with_pictures("P100"))
    assert got == [
        f"{CDN}/P100_1.jpg?sw=1248",
        f"{CDN}/P100_2.jpg",
        f"{CDN}/P100_sw.jpg?sw=53",
        f"{CDN}/set.jpg",
    ]


def test_image_urls_ignore_malformed_entries() -> None:
    bad = {"images": ["x", {"disBaseLink": "ftp://no"}], "c_variantsInfo": [1]}
    assert images.image_urls(bad) == []


def test_object_name_uses_content_type() -> None:
    assert images.object_name("ab", "image/jpeg; charset=binary") == "images/ab.jpg"
    assert images.object_name("ab", "image/webp") == "images/ab.webp"
    assert images.object_name("ab", "application/octet-stream") == "images/ab.bin"


ROBOTS = """
User-agent: *
Disallow: /*Product-Variation?pid=
Disallow: /*?sz=
Disallow: /private/
Allow: /private/open$

User-agent: pi-snapshot
Disallow: /only-for-us/
"""


@pytest.mark.parametrize(
    ("status", "url", "allowed"),
    [
        (200, "https://h/only-for-us/x.jpg", False),  # our own group wins over *
        (200, "https://h/private/x.jpg", True),  # our group has no rule for it
        (404, "https://h/anything", True),
        (410, "https://h/anything", True),
        (403, "https://h/anything", False),  # unreadable: fail closed
        (None, "https://h/anything", False),
    ],
)
def test_robots_group_selection_and_status(status: int | None, url: str, allowed: bool) -> None:
    assert images.Robots(ROBOTS, status).allows(url) is allowed


def test_robots_star_group_wildcards_and_allow_tiebreak() -> None:
    r = images.Robots(ROBOTS, 200, agent_name="other-bot")
    assert r.allows("https://h/dw/image/v2/a.jpg?sw=10") is True
    assert r.allows("https://h/dw/Product-Variation?pid=1") is False
    assert r.allows("https://h/img.jpg?sz=2") is False
    assert r.allows("https://h/private/x.jpg") is False
    assert r.allows("https://h/private/open") is True  # longer Allow wins


def test_locales_and_sitemap_filter_by_country() -> None:
    assert extract.locales("SA") == ("en-SA", "ar-SA")
    with pytest.raises(ValueError, match="country"):
        extract.locales("QA")
    sm = "http://www.sitemaps.org/schemas/sitemap/0.9"
    xml = (
        f'<urlset xmlns="{sm}">'
        "<url><loc>https://www.sephora.me/sa-en/p/serum/P100</loc></url>"
        "<url><loc>https://www.sephora.me/sa-ar/p/serum/P100/</loc></url>"
        "<url><loc>https://www.sephora.me/ae-en/p/serum/P100</loc></url>"
        "</urlset>"
    ).encode()
    assert [(lang, pid) for lang, pid, _ in extract.parse_sitemap(xml, "SA")] == [
        ("en", "P100"),
        ("ar", "P100"),
    ]
    assert extract.sitemap_urls("en-SA")[0].endswith("/sitemap/en-SA/catalog/productSlugsCO-0.xml")


def test_extract_pdp_full_keeps_long_text() -> None:
    out = extract.extract_pdp(pdp_html(details("P100")), full=True)
    assert out["productDetails"]["longDescription"] == "dropped"


def test_headers_follow_the_storefront_country() -> None:
    assert run.headers("ar-SA", "html")["Accept-Language"].startswith("ar-SA,")
    assert run.headers("en-SA", "image")["Accept"].startswith("image/")


class _Resp:
    """What ``httpx.Client.send(..., stream=True)`` hands back, streamed in small chunks."""

    def __init__(self, status: int, body: bytes, ct: str, location: str | None = None) -> None:
        self.status_code = status
        self.headers = {"content-type": ct} | ({"location": location} if location else {})
        self._body = body
        self.closed = False

    def iter_bytes(self, chunk: int = 4096) -> Any:
        for i in range(0, len(self._body), chunk):
            yield self._body[i : i + chunk]

    def close(self) -> None:
        self.closed = True


Getter = Callable[[str, dict[str, str]], _Resp]


def _sender(get: Getter) -> Callable[..., _Resp]:
    def send(request: httpx.Request, *, stream: bool = False) -> _Resp:
        assert stream is True  # bodies are always read under a byte cap
        return get(str(request.url), {k.title(): v for k, v in request.headers.items()})

    return send


def _stub(monkeypatch: pytest.MonkeyPatch, j: run.Job, get: Getter) -> None:
    monkeypatch.setattr(j.client, "send", _sender(get))


def _job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **env: str) -> run.Job:
    monkeypatch.setenv("BUCKET", f"file:{tmp_path}")
    monkeypatch.setenv("PREFIX", "out")
    monkeypatch.setenv("CUTOFF", "2099-01-01T00:00:00+00:00")
    monkeypatch.setenv("IMAGE_HOSTS", HOST)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    j = run.Job()
    monkeypatch.setattr(j, "pace", lambda: None)
    monkeypatch.setattr(j, "image_pace", lambda host=None: None)
    return j


def _rows(tmp_path: Path, stream: str) -> list[dict[str, Any]]:
    part = tmp_path / "out" / stream / "part-0000.jsonl.gz"
    return [json.loads(line) for line in gzip.decompress(part.read_bytes()).decode().splitlines()]


def test_ksa_page_with_raw_full_and_pictures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    j = _job(tmp_path, monkeypatch, COUNTRY="SA", FULL="1", RAW="1", IMAGES="1")
    page = pdp_html(_details_with_pictures("P100")).encode()
    calls: list[str] = []

    def get(url: str, headers: dict[str, str]) -> _Resp:
        calls.append(url)
        if url.endswith("/robots.txt"):
            return _Resp(200, b"User-agent: *\nDisallow: /blocked/\n", "text/plain")
        if url.startswith("https://www.sephora.me/sa-en/p/"):
            assert headers["Accept-Language"].startswith("en-SA")
            return _Resp(200, page, "text/html")
        assert headers["Accept"].startswith("image/") or url.endswith("/robots.txt")
        if url.endswith("_2.jpg"):
            return _Resp(404, b"", "text/html")
        return _Resp(200, b"\xff\xd8pic" + url.encode(), "image/jpeg")

    _stub(monkeypatch, j, get)
    j.pdp("P100", "en", "https://www.sephora.me/sa-en/p/x/P100")
    for stream in ("pdp_en", "images", "images_robots"):
        j.flush(stream)
    out = tmp_path / "out"
    rec = _rows(tmp_path, "pdp_en")[0]
    assert rec["locale"] == "en-SA"
    assert rec["final_url"] == "https://www.sephora.me/sa-en/p/x/P100"
    assert "redirects" not in rec  # no hop, no hop list
    assert rec["raw"] == "raw/en-P100.html.gz"
    assert gzip.decompress((out / rec["raw"]).read_bytes()) == page
    assert rec["extract"]["productDetails"]["longDescription"] == "dropped"
    pics = _rows(tmp_path, "images")
    states = [p["state"] for p in pics]
    assert states == ["ok", "http_error", "ok", "ok"]
    assert all(p["final_url"] == p["url"] for p in pics)
    stored = sorted(p.name for p in (out / "images").iterdir() if p.suffix == ".jpg")
    assert len(stored) == 3
    assert all(p["object"].startswith("images/") for p in pics if p["state"] == "ok")
    assert calls[1].endswith("/robots.txt")  # read once, before the first picture
    assert calls.count(f"https://{HOST}/robots.txt") == 1
    robots_rows = _rows(tmp_path, "images_robots")
    assert [(r["host"], r["status"], r["for"]) for r in robots_rows] == [(HOST, 200, "image")]
    assert j.counts["image_ok"] == 3
    assert j.counts["image_http_404"] == 1
    assert j.counts["pdp_en_ok"] == 1
    # a second product with the same pictures downloads nothing new
    j.pdp("P100", "en", "https://www.sephora.me/sa-en/p/x/P100")
    assert j.counts["image_ok"] == 3


def test_unreadable_image_robots_refuses_pictures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    j = _job(tmp_path, monkeypatch, IMAGES="1")

    def get(url: str, headers: dict[str, str]) -> _Resp:
        if url.endswith("/robots.txt"):
            return _Resp(200, b"<html>viewer</html>", "text/html")
        pytest.fail("no picture may be fetched when robots.txt is unreadable")

    _stub(monkeypatch, j, get)
    j.pictures("P100", _details_with_pictures("P100"))
    assert j.counts == {"image_robots_refused": 4}


def test_blocked_image_host_ends_the_picture_pass_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    j = _job(tmp_path, monkeypatch, IMAGES="1")

    def get(url: str, headers: dict[str, str]) -> _Resp:
        if url.endswith("/robots.txt"):
            return _Resp(404, b"", "text/html")
        return _Resp(403, b"Access Denied", "text/html")

    _stub(monkeypatch, j, get)
    j.pictures("P100", _details_with_pictures("P100"))
    assert j.images_on is False
    assert j.counts == {"images_stopped_blocked": 1}
    j.flush("images")
    pics = _rows(tmp_path, "images")
    assert pics[0]["state"] == "blocked"
    assert pics[0]["head"] == "Access Denied"


@pytest.mark.parametrize("pace", ["0.1", "0.5", "0.99"])
def test_image_pace_floor_is_one_second(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pace: str
) -> None:
    monkeypatch.setenv("BUCKET", f"file:{tmp_path}")
    monkeypatch.setenv("PREFIX", "out")
    monkeypatch.setenv("CUTOFF", "2099-01-01T00:00:00+00:00")
    monkeypatch.setenv("IMAGE_PACE", pace)
    assert run.MIN_IMAGE_PACE_S == 1.0
    with pytest.raises(ValueError, match="IMAGE_PACE"):
        run.Job()


def test_progress_records_capture_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    j = _job(tmp_path, monkeypatch, COUNTRY="SA", RAW="1")
    j.progress()
    got = json.loads((tmp_path / "out" / "progress.json").read_text())
    assert (got["country"], got["full"], got["raw"], got["images"]) == ("SA", False, True, False)
    assert (got["image_hosts"], got["image_pace_s"]) == ([HOST], 1.0)


# ------------------------------------------------------ B2: scraped URLs never pick a host


@pytest.mark.parametrize(
    ("url", "why"),
    [
        (f"http://{HOST}/a.jpg", "not https"),
        ("https://203.0.113.9/a.jpg", "not an allowed image host"),
        ("https://[2001:db8::1]/a.jpg", "not an allowed image host"),
        (f"https://{HOST}.evil.example/a.jpg", "not an allowed image host"),  # lookalike suffix
        (f"https://evil.example/{HOST}/a.jpg", "not an allowed image host"),  # host in the path
        (f"https://{HOST}@evil.example/a.jpg", "userinfo"),
        (f"https://user:pw@{HOST}/a.jpg", "userinfo"),
        (f"https://{HOST}:8443/a.jpg", "explicit port"),
        ("https:///a.jpg", "empty host"),
        ("ftp://img-product.example/a.jpg", "not https"),
        ("//img-product.example/a.jpg", "not https"),
    ],
)
def test_host_refusal_names_the_reason(url: str, why: str) -> None:
    got = images.host_refusal(url, {HOST})
    assert got is not None
    assert why in got


def test_host_refusal_accepts_only_the_exact_https_host() -> None:
    assert images.host_refusal(f"https://{HOST}/a.jpg?sw=1", {HOST}) is None
    assert (
        images.host_refusal(f"https://{HOST.upper()}/a.jpg", {HOST}) is None
    )  # hosts are not case-sensitive
    assert images.host_refusal(f"https://{HOST}/a.jpg", {"other.example"}) is not None
    assert images.host_refusal(f"https://{HOST}/a.jpg", set()) is not None
    assert "img-product.sephora.me" in images.DEFAULT_IMAGE_HOSTS


def test_pictures_off_the_allowlist_are_recorded_and_never_fetched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    j = _job(tmp_path, monkeypatch, IMAGES="1")
    d = details("P1")
    d["images"] = [
        {"disBaseLink": f"http://{HOST}/p.jpg"},
        {"disBaseLink": f"https://{HOST}.evil.example/p.jpg"},
        {"disBaseLink": f"https://{HOST}@evil.example/p.jpg"},
        {"disBaseLink": "https://203.0.113.9/p.jpg"},
        {"disBaseLink": f"https://{HOST}/ok.jpg"},
    ]
    calls: list[str] = []

    def get(url: str, headers: dict[str, str]) -> _Resp:
        calls.append(url)
        if url == f"https://{HOST}/robots.txt":
            return _Resp(404, b"", "text/plain")
        return _Resp(200, b"\xff\xd8pic", "image/jpeg")

    _stub(monkeypatch, j, get)
    j.pictures("P1", d)
    # not even the robots.txt of a refused host is read: the only requests go to the allowed host
    assert calls == [f"https://{HOST}/robots.txt", f"https://{HOST}/ok.jpg"]
    assert j.counts == {"image_host_refused": 4, "image_ok": 1}
    j.flush("images")
    rows = _rows(tmp_path, "images")
    assert [r["state"] for r in rows] == ["host_refused"] * 4 + ["ok"]
    assert all("reason" in r and "object" not in r for r in rows[:4])


def test_image_hosts_env_replaces_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    j = _job(tmp_path, monkeypatch, IMAGE_HOSTS=" a.example , B.Example ")
    assert j.image_hosts == frozenset({"a.example", "b.example"})
    monkeypatch.delenv("IMAGE_HOSTS")
    assert run.Job().image_hosts == images.DEFAULT_IMAGE_HOSTS


# ------------------------------------------------- redirects: every hop checked, final_url recorded


def test_redirect_hops_are_recorded_and_checked_against_robots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    j = _job(tmp_path, monkeypatch, IMAGES="1")
    d = details("P1")
    d["images"] = [
        {"disBaseLink": f"https://{HOST}/old.jpg"},
        {"disBaseLink": f"https://{HOST}/to-private.jpg"},
    ]
    calls: list[str] = []

    def get(url: str, headers: dict[str, str]) -> _Resp:
        calls.append(url)
        if url == f"https://{HOST}/robots.txt":
            return _Resp(200, b"User-agent: *\nDisallow: /private/\n", "text/plain")
        if url == f"https://{HOST}/old.jpg":
            return _Resp(301, b"", "text/html", location="/new.jpg")  # relative Location
        if url == f"https://{HOST}/new.jpg":
            return _Resp(302, b"", "text/html", location=f"https://{HOST}/final.jpg")
        if url == f"https://{HOST}/final.jpg":
            return _Resp(200, b"\xff\xd8final", "image/jpeg")
        if url == f"https://{HOST}/to-private.jpg":
            return _Resp(302, b"", "text/html", location=f"https://{HOST}/private/x.jpg")
        pytest.fail(f"unexpected request {url}")

    _stub(monkeypatch, j, get)
    j.pictures("P1", d)
    j.flush("images")
    ok, refused = _rows(tmp_path, "images")
    assert ok["state"] == "ok"
    assert ok["url"] == f"https://{HOST}/old.jpg"
    assert ok["final_url"] == f"https://{HOST}/final.jpg"
    assert ok["redirects"] == [f"https://{HOST}/new.jpg", f"https://{HOST}/final.jpg"]
    assert refused["state"] == "robots_refused"
    assert refused["final_url"] == f"https://{HOST}/private/x.jpg"
    assert refused["redirects"] == [f"https://{HOST}/private/x.jpg"]
    assert f"https://{HOST}/private/x.jpg" not in calls  # the disallowed hop is never requested
    assert j.counts == {"redirects": 3, "image_ok": 1, "image_robots_refused": 1}


def test_redirect_to_another_host_is_refused_for_pictures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    j = _job(tmp_path, monkeypatch, IMAGES="1")
    d = details("P1")
    d["images"] = [{"disBaseLink": f"https://{HOST}/p.jpg"}]
    calls: list[str] = []

    def get(url: str, headers: dict[str, str]) -> _Resp:
        calls.append(url)
        if url == f"https://{HOST}/robots.txt":
            return _Resp(404, b"", "text/plain")
        if url == f"https://{HOST}/p.jpg":
            return _Resp(302, b"", "text/html", location="https://cdn-elsewhere.example/p.jpg")
        pytest.fail(f"unexpected request {url}")

    _stub(monkeypatch, j, get)
    j.pictures("P1", d)
    j.flush("images")
    (row,) = _rows(tmp_path, "images")
    assert row["state"] == "host_refused"
    assert row["final_url"] == "https://cdn-elsewhere.example/p.jpg"
    assert "cdn-elsewhere.example" not in " ".join(calls[1:]) or calls == calls[:2]
    assert all(not c.startswith("https://cdn-elsewhere") for c in calls)
    assert j.counts == {"redirects": 1, "image_host_refused": 1}


def test_page_redirects_are_checked_per_hop_and_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    j = _job(tmp_path, monkeypatch)
    page = pdp_html(details("P1")).encode()
    calls: list[str] = []

    def get(url: str, headers: dict[str, str]) -> _Resp:
        calls.append(url)
        if url.endswith("/robots.txt"):
            return _Resp(200, b"User-agent: *\nDisallow: /sa-en/private/\n", "text/plain")
        if url == "https://www.sephora.me/sa-en/p/old/P1":
            return _Resp(301, b"", "text/html", location="/sa-en/p/new/P1")
        if url == "https://www.sephora.me/sa-en/p/new/P1":
            return _Resp(200, page, "text/html")
        if url == "https://www.sephora.me/sa-en/p/hidden/P1":
            return _Resp(302, b"", "text/html", location="/sa-en/private/P1")
        if url.startswith("https://www.sephora.me/sa-en/p/loop"):
            n = int(url.rsplit("/", 1)[1])
            return _Resp(302, b"", "text/html", location=f"/sa-en/p/loop/{n + 1}")
        pytest.fail(f"unexpected request {url}")

    _stub(monkeypatch, j, get)
    got = j.get("https://www.sephora.me/sa-en/p/old/P1", "en-SA", "html")
    assert got is not None
    status, body, meta = got
    assert (status, body) == (200, page)
    assert meta["final_url"] == "https://www.sephora.me/sa-en/p/new/P1"
    assert meta["redirects"] == ["https://www.sephora.me/sa-en/p/new/P1"]
    assert calls.count("https://www.sephora.me/robots.txt") == 1  # read once for the page host
    assert j.get("https://www.sephora.me/sa-en/p/hidden/P1", "en-SA", "html") is None
    assert "https://www.sephora.me/sa-en/private/P1" not in calls
    assert j.get("https://www.sephora.me/sa-en/p/loop/0", "en-SA", "html") is None
    assert "https://www.sephora.me/sa-en/p/loop/7" not in calls  # stops after MAX_REDIRECTS hops
    j.flush("errors")
    states = [r["state"] for r in _rows(tmp_path, "errors")]
    assert states == ["robots_refused", "too_many_redirects"]
    assert j.counts["hop_robots_refused"] == 1
    assert j.counts["hop_too_many_redirects"] == 1


def test_redirect_without_location_is_just_an_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    j = _job(tmp_path, monkeypatch)
    _stub(monkeypatch, j, lambda url, headers: _Resp(304, b"", "text/html"))
    got = j.get("https://www.sephora.me/sa-en/p/x/P1", "en-SA", "html")
    assert got is not None
    assert got[0] == 304
    assert got[2]["final_url"] == "https://www.sephora.me/sa-en/p/x/P1"


# ------------------------------------------------------------------------- B3: byte caps


def test_oversized_picture_is_recorded_as_too_large_and_not_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    j = _job(tmp_path, monkeypatch, IMAGES="1")
    d = details("P1")
    d["images"] = [
        {"disBaseLink": f"https://{HOST}/huge.jpg"},
        {"disBaseLink": f"https://{HOST}/edge.jpg"},
    ]
    resp: dict[str, _Resp] = {}

    def get(url: str, headers: dict[str, str]) -> _Resp:
        if url.endswith("/robots.txt"):
            return _Resp(404, b"", "text/plain")
        size = run.MAX_IMAGE_BYTES + 1 if url.endswith("huge.jpg") else run.MAX_IMAGE_BYTES
        resp[url] = _Resp(200, b"\xff" * size, "image/jpeg")
        return resp[url]

    _stub(monkeypatch, j, get)
    j.pictures("P1", d)
    j.flush("images")
    huge, edge = _rows(tmp_path, "images")
    assert huge["state"] == "too_large"
    assert huge["cap"] == run.MAX_IMAGE_BYTES
    assert "object" not in huge
    assert edge["state"] == "ok"  # exactly the cap is still accepted
    stored = [p for p in (tmp_path / "out" / "images").iterdir() if p.suffix == ".jpg"]
    assert len(stored) == 1
    assert all(r.closed for r in resp.values())  # the connection is released either way
    assert j.counts == {"image_too_large": 1, "image_ok": 1}
    assert j.images_on is True  # too large is not a block


def test_oversized_robots_txt_is_unreadable_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    j = _job(tmp_path, monkeypatch, IMAGES="1")

    def get(url: str, headers: dict[str, str]) -> _Resp:
        if url.endswith("/robots.txt"):
            return _Resp(200, b"Allow: /\n" * (run.MAX_ROBOTS_BYTES // 8 + 1), "text/plain")
        pytest.fail("no picture may be fetched when robots.txt is unreadable")

    _stub(monkeypatch, j, get)
    j.pictures("P1", _details_with_pictures("P1"))
    assert j.counts == {"image_robots_refused": 4}
    j.flush("images_robots")
    (row,) = _rows(tmp_path, "images_robots")
    assert row["status"] is None


def test_oversized_page_is_recorded_and_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    j = _job(tmp_path, monkeypatch)
    _stub(
        monkeypatch,
        j,
        lambda url, headers: _Resp(200, b"<html>" * (run.MAX_PAGE_BYTES // 6 + 1), "text/html"),
    )
    assert j.get("https://www.sephora.me/sa-en/p/x/P1", "en-SA", "html") is None
    j.flush("errors")
    (row,) = _rows(tmp_path, "errors")
    assert (row["state"], row["cap"]) == ("too_large", run.MAX_PAGE_BYTES)
    assert j.counts == {"too_large": 1}


# -------------------------------------- N1: Crawl-delay, N2: cutoff-bounded backoff


def test_crawl_delay_is_parsed_per_group() -> None:
    text = (
        "User-agent: *\nCrawl-delay: 2\nDisallow: /x\n\nUser-agent: pi-snapshot\nCrawl-delay: 7.5\n"
    )
    assert images.Robots(text, 200).crawl_delay == 7.5
    assert images.Robots(text, 200, agent_name="other").crawl_delay == 2.0
    assert images.Robots("User-agent: *\nDisallow: /x\n", 200).crawl_delay is None
    assert images.Robots("User-agent: *\nCrawl-delay: soon\n", 200).crawl_delay is None
    assert images.Robots("User-agent: *\nCrawl-delay: -1\n", 200).crawl_delay is None
    assert images.Robots("User-agent: *\nCrawl-delay: 99999\n", 200).crawl_delay is None


def test_image_pace_honours_the_hosts_crawl_delay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BUCKET", f"file:{tmp_path}")
    monkeypatch.setenv("PREFIX", "out")
    monkeypatch.setenv("CUTOFF", "2099-01-01T00:00:00+00:00")
    monkeypatch.setenv("IMAGE_HOSTS", HOST)
    j = run.Job()
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    monkeypatch.setattr(random, "uniform", lambda a, b: 0.0)
    j.host_robots[HOST] = images.Robots("User-agent: *\nCrawl-delay: 4\n", 200)
    j.image_last = time.monotonic()
    j.image_pace(HOST)
    j.image_pace("other.example")
    assert 3.9 < slept[0] <= 4.0  # the host's delay wins over IMAGE_PACE=1.0
    assert 0.9 < slept[1] <= 1.0  # a host without a delay keeps the configured pace


def test_backoff_never_sleeps_past_the_cutoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BUCKET", f"file:{tmp_path}")
    monkeypatch.setenv("PREFIX", "out")
    monkeypatch.setenv("CUTOFF", (datetime.now(UTC) + timedelta(seconds=30)).isoformat())
    j = run.Job()
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    with pytest.raises(run.Stop, match="cutoff"):
        j.backoff(900, "https://www.sephora.me/x")
    assert len(slept) == 1
    assert slept[0] <= 30.0
    j.backoff(5, "https://www.sephora.me/x")  # a short wait inside the window just sleeps
    assert slept[1] == 5


def test_429_on_a_picture_backs_off_inside_the_cutoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    j = _job(tmp_path, monkeypatch, IMAGES="1")
    waits: list[int] = []
    monkeypatch.setattr(j, "backoff", lambda delay, url: waits.append(delay))

    def get(url: str, headers: dict[str, str]) -> _Resp:
        if url.endswith("/robots.txt"):
            return _Resp(404, b"", "text/plain")
        return _Resp(429, b"", "text/plain")

    _stub(monkeypatch, j, get)
    j.pictures("P1", _details_with_pictures("P1"))
    assert waits == [60, 120]
    assert j.images_on is False
    assert j.counts == {"image_http_429": 3, "images_stopped_rate_limited": 1}
