"""Listing positions: plans, paging, and the reader, on synthetic pages only."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from page_capture import listings, robots
from page_capture.plan import parse_plan

FACES = "https://www.faces.ae"
ROBOTS_FACES = "User-agent: *\nDisallow: /*&sz=\nDisallow: /*?sz=\nDisallow: /*cgid=\n"


def spec_doc(**over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "retailer": "faces_ae",
        "source": "faces_ae_listings",
        "listings": [
            {
                "id": "faces-new",
                "url": f"{FACES}/en/new-beauty-products",
                "category": "new",
                "label": "New beauty",
                "paging": "start",
                "max_pages": 3,
            },
            {"id": "faces-best", "url": f"{FACES}/en/bestsellers", "category": "best_seller"},
        ],
    }
    doc.update(over)
    return doc


def tiles(ids: list[str], extra: str = "") -> str:
    links = "".join(
        f'<div class="tile"><a href="/en/p/brand-product-{i}.html?pos=1">x</a>'
        f'<a href="{FACES}/en/p/brand-product-{i}.html">again</a></div>'
        for i in ids
    )
    return f"<html><body><nav><a href='/en/bestsellers'>Best</a></nav>{links}{extra}</body></html>"


def ids(start: int, n: int) -> list[str]:
    return [f"{100000000000 + k}" for k in range(start, start + n)]


class Capture:
    """A page_capture output dir written by hand: pages parts plus raw bodies."""

    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "pages").mkdir(parents=True)
        (root / "raw").mkdir()
        self.recs: list[dict[str, Any]] = []

    def page(self, listing: str, page: int, state: str = "ok", html: str | None = None) -> None:
        rec: dict[str, Any] = {
            "id": f"{listing}-p{page:02d}",
            "url": f"{FACES}/en/x?start={page}",
            "ref": {"listing": listing, "page": page},
            "state": state,
            "at": f"2026-10-09T18:0{page}:00+00:00",
        }
        if html is not None:
            name = f"raw/{listing}-{page}.html.gz"
            (self.root / name).write_bytes(gzip.compress(html.encode()))
            rec |= {"raw": name, "final_url": f"{FACES}/en/x?start={page}", "status": 200}
        self.recs.append(rec)

    def write(self) -> Path:
        body = "".join(json.dumps(r) + "\n" for r in self.recs).encode()
        (self.root / "pages" / "part-0000.jsonl.gz").write_bytes(gzip.compress(body))
        return self.root


def rules(text: str = ROBOTS_FACES) -> dict[str, robots.Robots]:
    return {"www.faces.ae": robots.from_response(200, "text/plain", text, "UA")}


# ------------------------------------------------------------------ spec and plans
def test_spec_rejects_unknown_retailer_and_queried_paged_url() -> None:
    with pytest.raises(ValueError, match="retailer"):
        listings.spec_from_json(spec_doc(retailer="ulta_ae"))
    bad = spec_doc()
    bad["listings"][0]["url"] += "?start=0"
    with pytest.raises(ValueError, match="no query"):
        listings.spec_from_json(bad)
    over = spec_doc()
    over["listings"][0]["max_pages"] = 11
    with pytest.raises(ValueError, match="max_pages"):
        listings.spec_from_json(over)


def test_first_pages_plan_round_trips_through_page_capture() -> None:
    spec = listings.spec_from_json(spec_doc())
    plan = listings.checked_plan(spec, listings.first_pages(spec), rules())
    again = parse_plan(json.dumps(plan.to_json()).encode())
    assert [it.id for it in again.items] == ["faces-new-p01", "faces-best-p01"]
    assert again.items[0].ref == {"listing": "faces-new", "page": 1, "step": 0, "category": "new"}
    assert again.items[0].url == f"{FACES}/en/new-beauty-products"


def test_page_n_uses_start_only() -> None:
    spec = listings.spec_from_json(spec_doc())
    item = listings.page_item(spec, spec.listings[0], 3, 24)
    assert item.url == f"{FACES}/en/new-beauty-products?start=48"
    with pytest.raises(ValueError, match="start paging"):
        listings.page_url(spec.listings[1], 2, 24)  # page-1-only listing


def test_robots_refuses_disallowed_and_hosts_without_saved_robots() -> None:
    spec = listings.spec_from_json(spec_doc())
    strict = rules("User-agent: *\nDisallow: /en/bestsellers\n")
    with pytest.raises(ValueError, match="faces-best-p01"):
        listings.checked_plan(spec, listings.first_pages(spec), strict)
    with pytest.raises(ValueError, match="unavailable"):
        listings.checked_plan(spec, listings.first_pages(spec), {})


def test_cli_plan_writes_a_robots_checked_plan(tmp_path: Path) -> None:
    spec_path, out, rb = tmp_path / "spec.json", tmp_path / "plan.json", tmp_path / "robots.txt"
    spec_path.write_text(json.dumps(spec_doc()))
    rb.write_text(ROBOTS_FACES)
    assert listings.main(["plan", str(spec_path), str(out), f"www.faces.ae={rb}"]) == 0
    assert len(parse_plan(out.read_bytes()).items) == 2


# ------------------------------------------------------------------ extraction
def test_product_links_in_order_once_each_and_only_product_pages() -> None:
    html = tiles(["111111111111", "222222222222", "111111111111"]) + (
        '<a href="https://evil.example/en/p/x-333333333333.html">off-host</a>'
        "<a href='/en/p/no-id.html'>no id</a>"
        '<a href="/en/p/brand-a-&amp;-b-444444444444.html">escaped</a>'
    )
    got = listings.product_links("faces_ae", f"{FACES}/en/new", html)
    assert [pid for pid, _ in got] == ["111111111111", "222222222222", "444444444444"]
    assert got[0][1] == f"{FACES}/en/p/brand-product-111111111111.html"  # query dropped


@pytest.mark.parametrize(
    ("retailer", "base", "href", "pid"),
    [
        (
            "bloomingdales_ae",
            "https://bloomingdales.ae/new/",
            "/brand-cream-50ml-123456.html",
            "123456",
        ),
        (
            "ounass_ae",
            "https://www.ounass.ae/beauty/",
            "/shop-brand-serum-30ml-217000123_45.html",
            "217000123_45",
        ),
        ("sephora_me", "https://www.sephora.me/ae-en", "/ae-en/p/some-serum/P1000123", "P1000123"),
    ],
)
def test_product_links_per_retailer(retailer: str, base: str, href: str, pid: str) -> None:
    html = f'<a href="/beauty/">nav</a><a href="{href}">tile</a>'
    assert [p for p, _ in listings.product_links(retailer, base, html)] == [pid]


# ------------------------------------------------------------------ paging and summaries
def test_paged_listing_ends_on_a_short_page(tmp_path: Path) -> None:
    spec = listings.spec_from_json(spec_doc())
    cap = Capture(tmp_path / "c1")
    cap.page("faces-new", 1, html=tiles(ids(0, 4)))
    cap.page("faces-best", 1, html=tiles(ids(100, 3)))
    reads = listings.page_reads(spec, [cap.write()])
    nxt = listings.next_pages(spec, reads)
    assert [(it.id, it.url) for it in nxt] == [
        ("faces-new-p02", f"{FACES}/en/new-beauty-products?start=4")
    ]

    cap2 = Capture(tmp_path / "c2")
    cap2.page("faces-new", 2, html=tiles(ids(4, 2)))
    reads = listings.page_reads(spec, [tmp_path / "c1", cap2.write()])
    assert listings.next_pages(spec, reads) == []
    rows, summary = listings.summarise(spec, reads)
    new = [r for r in rows if r["listing"] == "faces-new"]
    assert [r["position"] for r in new] == [1, 2, 3, 4, 5, 6]
    assert [r["page"] for r in new] == [1, 1, 1, 1, 2, 2]
    by = {s["listing"]: s for s in summary}
    assert by["faces-new"] | {"page_states": None} == by["faces-new"] | {
        "status": "observed",
        "pages_read": 2,
        "positions_captured": 6,
        "end_reached": True,
        "stop_reason": "end",
        "page_size": 4,
        "page_states": None,
    }
    assert by["faces-best"]["stop_reason"] == "robots_page1"
    assert by["faces-best"]["end_reached"] is False


def test_paged_listing_stops_at_cap_without_end(tmp_path: Path) -> None:
    spec = listings.spec_from_json(spec_doc())
    cap = Capture(tmp_path / "c")
    for p in (1, 2, 3):
        cap.page("faces-new", p, html=tiles(ids(3 * (p - 1), 3)))
    reads = listings.page_reads(spec, [cap.write()])
    assert listings.next_pages(spec, reads) == []  # max_pages 3
    _, summary = listings.summarise(spec, reads)
    s = summary[0]
    assert (s["pages_read"], s["positions_captured"], s["end_reached"], s["stop_reason"]) == (
        3,
        9,
        False,
        "cap",
    )


def test_repeated_page_is_not_the_end_and_positions_stay_unique(tmp_path: Path) -> None:
    spec = listings.spec_from_json(spec_doc())
    cap = Capture(tmp_path / "c")
    cap.page("faces-new", 1, html=tiles(ids(0, 3)))
    cap.page("faces-new", 2, html=tiles(ids(0, 3)))  # ``start`` ignored: page 1 served again
    reads = listings.page_reads(spec, [cap.write()])
    rows, summary = listings.summarise(spec, reads)
    assert (summary[0]["positions_captured"], summary[0]["pages_read"]) == (3, 2)
    assert (summary[0]["stop_reason"], summary[0]["end_reached"]) == ("repeat", False)
    assert len({r["product_id"] for r in rows}) == len(rows)
    assert listings.next_pages(spec, reads) == []


def test_short_page_of_only_seen_products_is_a_repeat_not_the_end(tmp_path: Path) -> None:
    spec = listings.spec_from_json(spec_doc())
    cap = Capture(tmp_path / "c")
    cap.page("faces-new", 1, html=tiles(ids(0, 3)))
    cap.page("faces-new", 2, html=tiles(ids(1, 2)))
    _, summary = listings.summarise(spec, listings.page_reads(spec, [cap.write()]))
    assert (summary[0]["stop_reason"], summary[0]["end_reached"]) == ("repeat", False)


def test_paged_page_one_with_no_products_is_not_an_empty_list(tmp_path: Path) -> None:
    spec = listings.spec_from_json(spec_doc())
    cap = Capture(tmp_path / "c")
    cap.page("faces-new", 1, html="<html><body>rendered client side</body></html>")
    reads = listings.page_reads(spec, [cap.write()])
    _, summary = listings.summarise(spec, reads)
    new = next(s for s in summary if s["listing"] == "faces-new")
    assert (new["stop_reason"], new["end_reached"]) == ("no_products", False)
    assert (new["positions_captured"], new["page_size"]) == (0, None)
    assert new["warnings"] == ["page 1 read but no product link matched"]
    assert [it.id for it in listings.next_pages(spec, reads)] == []


def test_empty_page_after_a_full_page_is_not_the_end(tmp_path: Path) -> None:
    spec = listings.spec_from_json(spec_doc())
    cap = Capture(tmp_path / "c")
    cap.page("faces-new", 1, html=tiles(ids(0, 3)))
    cap.page("faces-new", 2, html="<html><body>no tiles</body></html>")
    _, summary = listings.summarise(spec, listings.page_reads(spec, [cap.write()]))
    assert (summary[0]["stop_reason"], summary[0]["end_reached"]) == ("empty_page", False)
    assert (summary[0]["positions_captured"], summary[0]["pages_read"]) == (3, 2)


def test_block_on_page_two_keeps_page_one_but_never_ends(tmp_path: Path) -> None:
    spec = listings.spec_from_json(spec_doc())
    cap = Capture(tmp_path / "c")
    cap.page("faces-new", 1, html=tiles(ids(0, 3)))
    cap.page("faces-new", 2, state="blocked", html="<html>challenge</html>")
    cap.page("faces-best", 1, state="skipped_host_stopped")
    _, summary = listings.summarise(spec, listings.page_reads(spec, [cap.write()]))
    by = {s["listing"]: s for s in summary}
    assert by["faces-new"]["status"] == "observed"
    assert (by["faces-new"]["end_reached"], by["faces-new"]["stop_reason"]) == (False, "block")
    assert by["faces-new"]["positions_captured"] == 3
    assert by["faces-best"]["status"] == "not_observed"
    assert by["faces-best"]["stop_reason"] == "block"
    assert by["faces-best"]["pages_read"] == 0


def test_http_error_and_missing_pages(tmp_path: Path) -> None:
    spec = listings.spec_from_json(spec_doc())
    cap = Capture(tmp_path / "c")
    cap.page("faces-new", 1, state="http_error", html="<html>500</html>")
    _, summary = listings.summarise(spec, listings.page_reads(spec, [cap.write()]))
    by = {s["listing"]: s for s in summary}
    assert (by["faces-new"]["status"], by["faces-new"]["stop_reason"]) == ("not_observed", "error")
    assert (by["faces-best"]["status"], by["faces-best"]["stop_reason"]) == (
        "not_observed",
        "pending",
    )


def test_zero_tiles_on_page_one_is_flagged(tmp_path: Path) -> None:
    spec = listings.spec_from_json(spec_doc())
    cap = Capture(tmp_path / "c")
    cap.page("faces-best", 1, html="<html><body>rendered client side</body></html>")
    _, summary = listings.summarise(spec, listings.page_reads(spec, [cap.write()]))
    best = next(s for s in summary if s["listing"] == "faces-best")
    assert best["positions_captured"] == 0
    assert best["warnings"] == ["page 1 read but no product link matched"]


def test_cli_read_and_next(tmp_path: Path) -> None:
    spec_path, rb = tmp_path / "spec.json", tmp_path / "robots.txt.gz"
    spec_path.write_text(json.dumps(spec_doc()))
    rb.write_bytes(gzip.compress(ROBOTS_FACES.encode()))
    cap = Capture(tmp_path / "c")
    cap.page("faces-new", 1, html=tiles(ids(0, 2)))
    cap.page("faces-best", 1, html=tiles(ids(9, 1)))
    d = str(cap.write())
    nxt = tmp_path / "next.json"
    args = ["next", str(spec_path), str(nxt), d, "--", f"www.faces.ae={rb}"]
    assert listings.main(args) == 0
    assert [it.id for it in parse_plan(nxt.read_bytes()).items] == ["faces-new-p02"]
    out = tmp_path / "read"
    assert listings.main(["read", str(spec_path), str(out), d]) == 0
    rows = [json.loads(x) for x in (out / "positions.jsonl").read_text().splitlines()]
    assert {r["listing"] for r in rows} == {"faces-new", "faces-best"}
    assert set(rows[0]) == {
        "retailer",
        "listing",
        "listing_url",
        "category",
        "label",
        "page",
        "position",
        "product_id",
        "product_url",
        "page_url",
        "captured_at",
    }
    assert len(json.loads((out / "summary.json").read_text())) == 2


def test_cli_next_exits_3_when_nothing_to_plan(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec_doc()))
    cap = Capture(tmp_path / "c")
    cap.page("faces-new", 1, html=tiles(ids(0, 0)))
    cap.page("faces-best", 1, html=tiles(ids(9, 1)))
    d = str(cap.write())
    args = ["next", str(spec_path), str(tmp_path / "n.json"), d, "--", "www.faces.ae=/nonexistent"]
    assert listings.main(args) == listings.NOTHING_TO_PLAN
    assert not (tmp_path / "n.json").exists()


def test_links_lists_same_host_listing_anchors(tmp_path: Path, capsys: Any) -> None:
    page = tmp_path / "home.html"
    page.write_text(
        '<a href="/ae-en/new">New</a><a href="/ae-en/best-sellers">B</a>'
        '<a href="https://other.example/new">x</a><a href="/ae-en/new">dup</a>'
        '<a href="/ae-en/p/serum/P12345">tile</a>'
    )
    assert listings.main(["links", "sephora_me", "https://www.sephora.me/ae-en", str(page)]) == 0
    out = capsys.readouterr()
    assert out.out.splitlines() == [
        "https://www.sephora.me/ae-en/new",
        "https://www.sephora.me/ae-en/best-sellers",
    ]
    assert "products linked: 1" in out.err
