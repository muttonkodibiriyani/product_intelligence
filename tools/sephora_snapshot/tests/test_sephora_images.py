"""Picture pass helpers and the IMAGES/RAW/FULL/COUNTRY options, with a stubbed client."""

import gzip
import json
from pathlib import Path
from typing import Any

import pytest
from sephora_snapshot import extract, images, run
from sephora_synth import details, pdp_html

CDN = "https://img-product.example/dw/image/v2/X/on/demandware.static/-/Sites-x/default/dw1/p"


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
    def __init__(self, status: int, body: bytes, ct: str) -> None:
        self.status_code = status
        self.content = body
        self.text = body.decode("utf-8", "replace")
        self.headers = {"content-type": ct}


def _job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **env: str) -> run.Job:
    monkeypatch.setenv("BUCKET", f"file:{tmp_path}")
    monkeypatch.setenv("PREFIX", "out")
    monkeypatch.setenv("CUTOFF", "2099-01-01T00:00:00+00:00")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    j = run.Job()
    monkeypatch.setattr(j, "pace", lambda: None)
    monkeypatch.setattr(j, "image_pace", lambda: None)
    return j


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

    monkeypatch.setattr(j.client, "get", get)
    j.pdp("P100", "en", "https://www.sephora.me/sa-en/p/x/P100")
    for stream in ("pdp_en", "images", "images_robots"):
        j.flush(stream)
    out = tmp_path / "out"
    rec = json.loads(gzip.decompress((out / "pdp_en" / "part-0000.jsonl.gz").read_bytes()))
    assert rec["locale"] == "en-SA"
    assert rec["raw"] == "raw/en-P100.html.gz"
    assert gzip.decompress((out / rec["raw"]).read_bytes()) == page
    assert rec["extract"]["productDetails"]["longDescription"] == "dropped"
    pics = [
        json.loads(line)
        for line in gzip.decompress((out / "images" / "part-0000.jsonl.gz").read_bytes())
        .decode()
        .splitlines()
    ]
    states = [p["state"] for p in pics]
    assert states == ["ok", "http_error", "ok", "ok"]
    stored = sorted(p.name for p in (out / "images").iterdir() if p.suffix == ".jpg")
    assert len(stored) == 3
    assert all(p["object"].startswith("images/") for p in pics if p["state"] == "ok")
    assert calls[1].endswith("/robots.txt")  # read once, before the first picture
    assert calls.count("https://img-product.example/robots.txt") == 1
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

    monkeypatch.setattr(j.client, "get", get)
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

    monkeypatch.setattr(j.client, "get", get)
    j.pictures("P100", _details_with_pictures("P100"))
    assert j.images_on is False
    assert j.counts == {"images_stopped_blocked": 1}
    j.flush("images")
    part = tmp_path / "out" / "images" / "part-0000.jsonl.gz"
    pics = [json.loads(line) for line in gzip.decompress(part.read_bytes()).decode().splitlines()]
    assert pics[0]["state"] == "blocked"
    assert pics[0]["head"] == "Access Denied"


def test_image_pace_floor_is_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BUCKET", f"file:{tmp_path}")
    monkeypatch.setenv("PREFIX", "out")
    monkeypatch.setenv("CUTOFF", "2099-01-01T00:00:00+00:00")
    monkeypatch.setenv("IMAGE_PACE", "0.1")
    with pytest.raises(ValueError, match="IMAGE_PACE"):
        run.Job()


def test_progress_records_capture_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    j = _job(tmp_path, monkeypatch, COUNTRY="SA", RAW="1")
    j.progress()
    got = json.loads((tmp_path / "out" / "progress.json").read_text())
    assert (got["country"], got["full"], got["raw"], got["images"]) == ("SA", False, True, False)
