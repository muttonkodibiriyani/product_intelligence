"""prod_smoke_api: the owner's read-only deploy smoke, run here on fixtures only (no network).

Two harnesses: the real pi_api app in-process (main's routes and shapes), and a fake API that
serves #146's price-floor shapes (price null + priceFlag invalid_low + the invalid_price_excluded
caveat), so S4's withheld-not-dropped rule is tested before #146 is on main.
"""

from __future__ import annotations

import copy
import http.server
import json
import threading
import urllib.parse
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar, cast

import prod_smoke_api as smoke
import pytest
from prod_smoke_api import Response

from api_fixture import make_client, served_dataset, token, write

SECRET = "tok-" + "x" * 40  # stands in for the owner's ID token; must never be printed or written


# ------------------------------------------------------------------ the real app (main)


def in_process(client: Any) -> smoke.Transport:
    def transport(url: str, headers: Mapping[str, str]) -> Response:
        parts = urllib.parse.urlsplit(url)
        r = client.get(
            parts.path + ("?" + parts.query if parts.query else ""), headers=dict(headers)
        )
        ctype = r.headers.get("content-type", "")
        return Response(r.status_code, r.json() if "json" in ctype else None, len(r.content), ctype)

    return transport


@pytest.fixture
def real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[smoke.Transport, dict[str, int]]:
    write(tmp_path / "data", served_dataset())
    client = make_client(tmp_path / "data")[0]
    transport = in_process(client)
    api = smoke.Api(transport, token(), "http://api/api/v1")
    counts = smoke.coverage(api)
    monkeypatch.setattr(smoke, "EXPECTED", counts)
    monkeypatch.setattr(smoke, "IMAGE_HOSTS", dict.fromkeys(counts, "img.invalid"))
    monkeypatch.setenv(smoke.TOKEN_ENV, token())
    return transport, counts


def test_save_and_counts_check_run_against_the_real_api(
    real: tuple[smoke.Transport, dict[str, int]], tmp_path: Path
) -> None:
    transport, counts = real
    out = tmp_path / "smoke"
    base = ["--out", str(out), "--base", "https://api/api/v1"]
    # The fixture has no prices <= 0.01 and no ulta_ae (EXPECTED is the fixture's own coverage).
    assert smoke.main(["save", *base, "--known-low-price", "0"], transport) == 0
    saved = json.loads((out / "baseline.json").read_text())
    assert saved["cursor"]
    assert saved["apiVersion"]
    assert saved["lowPrice"] == []
    assert saved["counts"] == counts
    rep = smoke.Report()
    api = smoke.Api(transport, token(), "http://api/api/v1")
    smoke.s8_cursor(api, rep, saved)
    rep.expect(smoke.contexts(api) != {}, "contexts")
    assert rep.problems == []


def test_the_real_api_refuses_the_no_token_call(
    real: tuple[smoke.Transport, dict[str, int]],
) -> None:
    transport, _ = real
    api = smoke.Api(transport, token(), "http://api/api/v1")
    assert api.get("/meta", auth=False).status == 401
    assert api.get("/meta").status == 200


# ------------------------------------------------------------------ #146 shapes (fake API)

ULTA_LOW = ("u1", "ulta_ae")


def money(value: str) -> dict[str, Any]:
    return {"amount": value, "currency": "AED", "minor": int(float(value) * 100)}


class FakeProd:
    """The live API's shapes after the deploy: two Ulta offers of 0.01 withheld by #146."""

    def __init__(self, *, floor: bool = True) -> None:
        self.floor = floor
        self.unflagged: set[str] = set()  # withheld (null) without priceFlags invalid_low
        self.regular_low: set[str] = set()  # detail offer still serves regular 0.01
        self.version = "1.7.0"
        self.cards: dict[str, list[dict[str, Any]]] = {"sephora_me": [], "ulta_ae": []}
        for i in range(250):
            self.cards["sephora_me"].append(self._card(f"s{i}", "sephora_me", "12.00"))
        for i in range(120):
            low = i < 2
            self.cards["ulta_ae"].append(self._card(f"u{i}", "ulta_ae", "0.01" if low else "30.00"))
        self.caveat = {"ulta_ae": 2}

    def _card(self, pid: str, ctx: str, price: str) -> dict[str, Any]:
        host = smoke.IMAGE_HOSTS[ctx]
        return {
            "id": pid,
            "prices": {ctx: money(price)},
            "image": {"url": f"https://{host}/{pid}.jpg"},
        }

    def served(self, card: dict[str, Any]) -> dict[str, Any]:
        card = copy.deepcopy(card)
        card["priceFlags"] = {}
        if self.floor:
            for ctx, m in card["prices"].items():
                if smoke.low(m):
                    card["prices"][ctx] = None
                    if card["id"] not in self.unflagged:
                        card["priceFlags"][ctx] = "invalid_low"
        return card

    def all_cards(self) -> dict[str, dict[str, Any]]:
        return {c["id"]: c for cs in self.cards.values() for c in cs}

    def __call__(self, url: str, headers: Mapping[str, str]) -> Response:
        parts = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(parts.query))
        if parts.netloc in set(smoke.IMAGE_HOSTS.values()):
            return Response(200, None, 10, "image/jpeg")
        path = parts.path.removeprefix("/api/v1")
        if headers.get("Authorization") != f"Bearer {SECRET}":
            return Response(401, {"error": "unauthenticated"}, 20, "application/json")
        data = self.route(path, q)
        if data is None:
            return Response(404, {}, 2, "application/json")
        body = {
            "data": data,
            "meta": {"apiVersion": self.version, "cutoff": "2026-10-01T00:00:00Z"},
        }
        if path == "/summary" and self.floor and q["retailer"] in self.caveat:
            n = self.caveat[q["retailer"]]
            body["caveats"] = [
                {
                    "code": "invalid_price_excluded",
                    "params": {"retailer": q["retailer"], "count": str(n)},
                }
            ]
        return Response(200, body, len(json.dumps(body)), "application/json")

    def route(self, path: str, q: dict[str, str]) -> Any:  # noqa: PLR0911
        if path == "/meta":
            return {
                "retailers": [{"id": r} for r in self.cards],
                "contexts": [{"id": r, "retailer": r} for r in self.cards],
            }
        if path == "/coverage":
            return {"retailers": [{"id": r, "productCount": smoke.EXPECTED[r]} for r in self.cards]}
        if path == "/products":
            rows = (
                self.cards[q["retailer"]]
                if "retailer" in q
                else [c for cs in self.cards.values() for c in cs]
            )
            start = int(q.get("cursor") or 0)
            limit = int(q.get("limit", "100"))
            nxt = start + limit
            return {
                "items": [self.served(c) for c in rows[start:nxt]],
                "nextCursor": str(nxt) if nxt < len(rows) else None,
            }
        if path.startswith("/products/"):
            card = self.served(self.all_cards()[path.rsplit("/", 1)[1]])
            ((ctx, price),) = card["prices"].items()
            flag = card["priceFlags"].get(ctx)
            host = smoke.EVIDENCE_HOSTS[ctx]
            return {
                "offers": [
                    {
                        "retailer": ctx,
                        "context": ctx,
                        "price": price,
                        "priceFlag": flag,
                        "regular": money("0.01") if card["id"] in self.regular_low else None,
                        "sku": f"SKU-{card['id']}" if ctx == "ulta_ae" else None,
                        "evidence": {"url": f"https://{host}/p/{card['id']}"},
                    }
                ]
            }
        if path == "/summary":
            return {"retailer": q["retailer"], "topDiscounts": []}
        if path == "/catalogues/ulta_ae":
            return {"generation": "1790852220300614"}
        if path.startswith("/catalogues/ulta_ae/skus/"):
            return {
                "record": {"sku": path.rsplit("/", 1)[-1], "imageIds": ["a1"]},
                "images": [{"assetId": "a1", "url": "https://media.alshaya.com/g/1.jpg"}],
            }
        if path == "/category-compare":
            return {"rows": []}
        return None


def run(fake: FakeProd, tmp_path: Path, mode: str, *extra: str) -> int:
    return smoke.main(
        [mode, "--out", str(tmp_path), "--base", "https://pi.invalid/api/v1", *extra], fake
    )


@pytest.fixture
def owner_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(smoke.TOKEN_ENV, SECRET)
    monkeypatch.setattr(smoke, "EXPECTED", {"sephora_me": 250, "ulta_ae": 120})


def baseline(tmp_path: Path) -> None:
    """Before the deploy: no floor, the two 0.01 prices are served."""
    assert run(FakeProd(floor=False), tmp_path, "save", "--known-low-price", "2") == 0


@pytest.mark.usefixtures("owner_token")
def test_withheld_not_dropped_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    baseline(tmp_path)
    saved = json.loads((tmp_path / "baseline.json").read_text())
    assert [(r["product"], r["context"]) for r in saved["lowPrice"]] == [
        ("u0", "ulta_ae"),
        ("u1", "ulta_ae"),
    ]
    assert run(FakeProd(), tmp_path, "check", "--expect-api", "1.7.0") == 0
    out = capsys.readouterr().out
    assert "PROD API SMOKE PASS" in out
    assert json.loads((tmp_path / "check.json").read_text())["verdict"] == "PASS"


@pytest.mark.usefixtures("owner_token")
def test_a_baseline_low_price_count_other_than_the_recorded_one_stops(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(FakeProd(floor=False), tmp_path, "save", "--known-low-price", "3") == 1
    assert "unexplained data change" in capsys.readouterr().out


@pytest.mark.usefixtures("owner_token")
def test_dropped_rows_fail_even_though_no_low_price_is_served(tmp_path: Path) -> None:
    baseline(tmp_path)
    fake = FakeProd()
    fake.cards["ulta_ae"] = fake.cards["ulta_ae"][2:]  # the two rows vanished: a false removal
    assert run(fake, tmp_path, "check", "--expect-api", "1.7.0") == 1
    problems = json.loads((tmp_path / "check.json").read_text())["problems"]
    assert any(p.startswith("S4(i) u0") for p in problems)


@pytest.mark.usefixtures("owner_token")
def test_a_still_served_low_price_fails(tmp_path: Path) -> None:
    baseline(tmp_path)
    assert run(FakeProd(floor=False), tmp_path, "check", "--expect-api", "1.7.0") == 1
    problems = json.loads((tmp_path / "check.json").read_text())["problems"]
    assert any(p.startswith("S4(iv)") for p in problems)
    assert any(p.startswith("S4(ii)") for p in problems)


@pytest.mark.usefixtures("owner_token")
@pytest.mark.parametrize(("caveat", "code", "verdict"), [(3, 0, "REVIEW"), (1, 1, "FAIL")])
def test_the_caveat_count_is_compared_with_the_baseline(
    tmp_path: Path, caveat: int, code: int, verdict: str
) -> None:
    baseline(tmp_path)
    fake = FakeProd()
    fake.caveat["ulta_ae"] = caveat
    assert run(fake, tmp_path, "check", "--expect-api", "1.7.0") == code
    assert json.loads((tmp_path / "check.json").read_text())["verdict"] == verdict


@pytest.mark.usefixtures("owner_token")
def test_a_wrong_version_or_catalogue_generation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline(tmp_path)
    monkeypatch.setattr(smoke, "CATALOGUE_GENERATION", "1790000000000000")
    assert run(FakeProd(), tmp_path, "check", "--expect-api", "9.9.9") == 1
    problems = json.loads((tmp_path / "check.json").read_text())["problems"]
    assert any(p.startswith("S1 apiVersion") for p in problems)
    assert any(p.startswith("S5 served catalogue generation") for p in problems)


class NoGallery(FakeProd):
    """CatalogueDetail with no top-level images: the gallery lives there, not in record."""

    def route(self, path: str, q: dict[str, str]) -> Any:
        body = super().route(path, q)
        if path.startswith("/catalogues/ulta_ae/skus/"):
            return {"record": {**body["record"], "images": body["images"]}, "images": []}
        return body


@pytest.mark.usefixtures("owner_token")
def test_s5_reads_the_gallery_from_the_top_level_images(tmp_path: Path) -> None:
    baseline(tmp_path)
    assert run(NoGallery(), tmp_path, "check", "--expect-api", "1.7.0") == 1
    problems = json.loads((tmp_path / "check.json").read_text())["problems"]
    assert any("0 gallery images" in p for p in problems)


@pytest.mark.usefixtures("owner_token")
def test_an_expired_token_is_a_refresh_not_a_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline(tmp_path)
    monkeypatch.setenv(smoke.TOKEN_ENV, "expired")
    assert run(FakeProd(), tmp_path, "check", "--expect-api", "1.7.0") == smoke.EXPIRED
    assert "Refresh PI_TOKEN" in capsys.readouterr().out


def test_no_token_in_the_environment_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(smoke.TOKEN_ENV, raising=False)
    assert run(FakeProd(), tmp_path, "save") == 2


@pytest.mark.usefixtures("owner_token")
def test_the_token_is_never_printed_or_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline(tmp_path)
    run(FakeProd(), tmp_path, "check", "--expect-api", "1.7.0")
    assert SECRET not in capsys.readouterr().out
    for f in tmp_path.iterdir():
        text = f.read_text()
        assert SECRET not in text
        assert "Bearer" not in text


def test_the_token_has_no_command_line_option() -> None:
    with pytest.raises(SystemExit):
        smoke.parse_args(["save", "--out", "x", "--token", SECRET])
    source = Path(smoke.__file__).read_text()
    assert "create_user" not in source
    assert "delete_user" not in source
    assert "signInWith" not in source


def test_a_category_param_replaces_the_default() -> None:
    assert smoke.parse_args(["save", "--out", "x"]).category_param is None
    args = smoke.parse_args(["save", "--out", "x", "--category-param", "retailers=a,b"])
    assert args.category_param == ["retailers=a,b"]


# ------------------------------------------------------------------ Reviewer R1/R2/R4


class _Redirector(http.server.BaseHTTPRequestHandler):
    seen: ClassVar[list[tuple[str, bool]]] = []

    def do_GET(self) -> None:
        type(self).seen.append((self.path, "Authorization" in self.headers))
        self.send_response(302 if self.path.startswith("/api/") else 200)
        self.send_header(
            "Location",
            f"http://127.0.0.1:{cast(http.server.HTTPServer, self.server).server_port}/elsewhere",
        )
        self.end_headers()

    def log_message(self, *_: Any) -> None:
        pass


def test_a_redirect_is_refused_and_the_token_never_follows_it() -> None:
    _Redirector.seen.clear()
    server = http.server.HTTPServer(("127.0.0.1", 0), _Redirector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}/api/v1"
        r = smoke.urllib_transport(base + "/meta", {"Authorization": f"Bearer {SECRET}"})
        assert r.status == 302
        with pytest.raises(smoke.RedirectError):
            smoke.Api(smoke.urllib_transport, SECRET, base).get("/meta")
    finally:
        server.shutdown()
        server.server_close()
    assert _Redirector.seen == [("/api/v1/meta", True), ("/api/v1/meta", True)]  # never /elsewhere


@pytest.mark.usefixtures("owner_token")
def test_a_3xx_from_the_api_fails_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def moved(url: str, headers: Mapping[str, str]) -> Response:
        return Response(301, None, 0, "text/html")

    assert (
        smoke.main(["save", "--out", str(tmp_path), "--base", "https://pi.invalid/api/v1"], moved)
        == 1
    )
    assert "FAIL" in capsys.readouterr().out


def test_a_non_https_base_is_rejected() -> None:
    with pytest.raises(SystemExit):
        smoke.parse_args(["save", "--out", "x", "--base", "http://pi.invalid/api/v1"])


def test_a_product_at_both_retailers_is_counted_once_per_context() -> None:
    ctx = {"sephora_me": "sephora_me", "ulta_ae": "ulta_ae"}
    card = {"id": "p", "prices": {"ulta_ae": money("0.01"), "sephora_me": money("0.01")}}
    assert [r["context"] for r in smoke.low_rows(card, ctx, "ulta_ae")] == ["ulta_ae"]
    assert [r["context"] for r in smoke.low_rows(card, ctx, "sephora_me")] == ["sephora_me"]


@pytest.mark.usefixtures("owner_token")
def test_save_does_not_double_count_a_shared_product(tmp_path: Path) -> None:
    fake = FakeProd(floor=False)
    shared = fake.cards["ulta_ae"][0]
    shared["prices"]["sephora_me"] = money("20.00")
    fake.cards["sephora_me"][0] = shared  # u0 is walked under both retailers
    assert run(fake, tmp_path, "save", "--known-low-price", "2") == 0
    rows = json.loads((tmp_path / "baseline.json").read_text())["lowPrice"]
    assert sorted((r["product"], r["context"]) for r in rows) == [
        ("u0", "ulta_ae"),
        ("u1", "ulta_ae"),
    ]


@pytest.mark.usefixtures("owner_token")
def test_a_null_card_price_without_invalid_low_fails(tmp_path: Path) -> None:
    baseline(tmp_path)
    fake = FakeProd()
    fake.unflagged.add("u0")
    assert run(fake, tmp_path, "check", "--expect-api", "1.7.0") == 1
    problems = json.loads((tmp_path / "check.json").read_text())["problems"]
    assert any(p.startswith("S4(ii) card u0") for p in problems)


@pytest.mark.usefixtures("owner_token")
def test_a_detail_regular_at_the_floor_fails(tmp_path: Path) -> None:
    baseline(tmp_path)
    fake = FakeProd()
    fake.regular_low.add("u1")
    assert run(fake, tmp_path, "check", "--expect-api", "1.7.0") == 1
    problems = json.loads((tmp_path / "check.json").read_text())["problems"]
    assert problems == ["S4(iv) /products/u1: no regular <= 0.01"]
