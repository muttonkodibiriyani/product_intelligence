"""Plan builders: KSA radar CSV and downloaded sitemaps."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from page_capture import plans

EN_AR = [
    (
        "victorias_secret",
        "https://www.victoriassecret.com.sa/en/x/buy-a",
        "https://www.victoriassecret.com.sa/ar/x/buy-a",
    ),
    (
        "centrepoint",
        "https://www.centrepointstores.com/sa/en/buy-a/p/1",
        "https://www.centrepointstores.com/sa/ar/buy-a/p/1",
    ),
    (
        "max_fashion",
        "https://www.maxfashion.com/sa/en/buy-a/p/C1",
        "https://www.maxfashion.com/sa/ar/buy-a/p/C1",
    ),
    (
        "zara",
        "https://www.zara.com/sa/en/a-p07093320.html?v1=1",
        "https://www.zara.com/sa/ar/a-p07093320.html?v1=1",
    ),
    (
        "charles_keith",
        "https://www.charleskeith.sa/sa-en/CK1.html",
        "https://www.charleskeith.sa/sa/CK1.html",
    ),
    ("nike", "https://www.nike.sa/en/a/NK1.html", "https://www.nike.sa/ar/a/NK1.html"),
    (
        "marks_spencer",
        "https://www.marksandspencer.sa/en/fashion/products/a/t1",
        "https://www.marksandspencer.sa/ar/fashion/products/a/t1",
    ),
    ("nayomi", "https://sa.nayomi.com/en/products/a-1", "https://sa.nayomi.com/products/a-1"),
    ("milano", "https://ksa.milanomena.com/products/a", "https://ksa.milanomena.com/ar/products/a"),
    (
        "steve_madden",
        "https://www.stevemadden.sa/products/a",
        "https://www.stevemadden.sa/ar/products/a",
    ),
    ("cos", "https://sa.cos.com/en/buy-a", "https://sa.cos.com/ar/buy-a"),
]


@pytest.mark.parametrize(("retailer", "en", "ar"), EN_AR)
def test_arabic_twin(retailer: str, en: str, ar: str) -> None:
    assert plans.arabic_twin(retailer, en) == ar


def test_arabic_twin_absent() -> None:
    assert plans.arabic_twin("unknown_shop", "https://x.example/en/a") is None
    assert plans.arabic_twin("aldo", "https://aldo.com.sa/en/products/a-1") is None
    assert plans.arabic_twin("mamas_papas", "https://en.mamasandpapas.com.sa/a.html") is None
    assert plans.arabic_twin("nike", "https://www.nike.sa/launch") is None


def _row(**kw: str) -> dict[str, str]:
    base = {
        "id": "p1",
        "retailer": "nike",
        "item": "shoe",
        "item_label": "Shoe",
        "name": "Air",
        "source_product_id": "NK1",
        "url": "https://www.nike.sa/en/a/NK1.html",
        "image_url": "https://www.nike.sa/i/1.jpg",
        "images": json.dumps(["https://www.nike.sa/i/1.jpg", "https://www.nike.sa/i/2.jpg"]),
    }
    return {**base, **kw}


def test_ksa_radar_builds_en_and_ar_items_and_dedupes() -> None:
    rows = [
        _row(),
        _row(id="p2", image_url="https://www.nike.sa/i/3.jpg"),  # same url: merged
        _row(
            id="p3",
            retailer="milano",
            url="https://ksa.milanomena.com/products/a",
            images="",
            image_url="",
        ),
    ]
    out = plans.ksa_radar(rows)
    assert sorted(out) == ["milano", "nike"]
    nike = out["nike"]
    assert nike.source == "ksa_radar"
    assert [it.locale for it in nike.items] == ["en-SA", "ar-SA"]
    en, ar = nike.items
    assert en.images == ("https://www.nike.sa/i/1.jpg", "https://www.nike.sa/i/2.jpg")
    assert en.ref["radar_row_id"] == "p1"
    assert en.ref["radar_row_ids"] == ["p1", "p2"]
    assert en.ref["source_product_id"] == "NK1"
    assert ar.url == "https://www.nike.sa/ar/a/NK1.html"
    assert ar.images == ()
    assert ar.ref["derived_from"] == en.id
    assert en.id != ar.id
    milano = out["milano"]
    assert [it.url for it in milano.items] == [
        "https://ksa.milanomena.com/products/a",
        "https://ksa.milanomena.com/ar/products/a",
    ]
    assert milano.items[0].images == ()


def test_row_images_union_and_errors() -> None:
    assert plans.row_images({"images": "", "image_url": " https://a.example/x.jpg "}) == (
        "https://a.example/x.jpg",
    )
    assert plans.row_images(
        {"images": '["https://a.example/1.jpg"]', "image_url": "https://a.example/2.jpg"}
    ) == (
        "https://a.example/1.jpg",
        "https://a.example/2.jpg",
    )
    assert plans.row_images({"images": '["//cdn/relative.jpg"]'}) == ()
    with pytest.raises(ValueError, match="not JSON"):
        plans.row_images({"id": "p9", "images": "[oops"})
    with pytest.raises(ValueError, match="list of strings"):
        plans.row_images({"id": "p9", "images": '{"a": 1}'})
    with pytest.raises(ValueError, match="required"):
        plans.ksa_radar([{"id": "p1", "retailer": "", "url": "https://x.example/"}])


SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.faces.ae/en/p/lipstick.html</loc><lastmod>2026-09-01</lastmod></url>
  <url><loc>https://www.faces.ae/ar/p/lipstick.html</loc></url>
  <url><loc>https://www.faces.ae/en/makeup/</loc></url>
  <url><loc>https://www.faces.ae/en/p/lipstick.html</loc></url>
</urlset>
"""


def test_sitemap_plan_from_xml_and_url_list() -> None:
    plan = plans.sitemap_plan(
        "faces",
        "faces",
        [SITEMAP, "https://www.faces.ae/en/p/mascara.html\nnot a url\n"],
        r"/(?P<lang>en|ar)/p/[^/]+\.html$",
    )
    urls = [it.url for it in plan.items]
    assert urls == [
        "https://www.faces.ae/en/p/lipstick.html",
        "https://www.faces.ae/ar/p/lipstick.html",
        "https://www.faces.ae/en/p/mascara.html",
    ]
    assert [it.locale for it in plan.items] == ["en-AE", "ar-AE", "en-AE"]
    assert plan.items[0].ref == {"retailer": "faces", "source": "faces"}
    with pytest.raises(ValueError, match="no <loc>"):
        plans.sitemap_plan("faces", "faces", [SITEMAP], r"/never/")


def test_cli_ksa_radar_and_sitemap(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv_path = tmp_path / "products.csv"
    row = _row()
    header = ",".join(row)
    values = ",".join('"' + v.replace('"', '""') + '"' for v in row.values())
    csv_path.write_text(f"{header}\n{values}\n")
    out_dir = tmp_path / "plans"
    assert plans.main(["ksa-radar", str(csv_path), str(out_dir)]) == 0
    doc = json.loads((out_dir / "nike.json").read_text())
    assert doc["retailer"] == "nike"
    assert len(doc["items"]) == 2
    assert "nike\t2\tar,en" in capsys.readouterr().out

    gz = tmp_path / "sitemap_0.xml.gz"
    gz.write_bytes(gzip.compress(SITEMAP.encode()))
    lst = tmp_path / "list.txt"
    lst.write_text(f"# downloaded sitemaps\n{gz}\n")
    out = tmp_path / "faces.json"
    assert (
        plans.main(["sitemap", "faces", "faces", str(lst), r"/p/[^/]+\.html$", str(out), "AE"]) == 0
    )
    doc = json.loads(out.read_text())
    assert len(doc["items"]) == 2
    assert doc["items"][0]["locale"] == "en-AE"

    assert plans.main(["bogus"]) == 2
