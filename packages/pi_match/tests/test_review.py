"""``pi-match-review``: the owner's review packet and its answers as decisions."""

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from pi_core.enums import ReviewState
from pi_match import review
from pi_match.matchfile import Decision, ListingRef, MatchFile, Verdict
from pi_match.review import AnswersError, Side, decisions, merged, price_outliers
from pi_match.run_cli import main as run_main

F, U = "faces_ae", "ulta_ae"
FACES_IMG = "https://www.faces.ae/dw/image/{}.jpg"


def offer(price: str, image: str | None, url: str | None, **kw: Any) -> dict[str, Any]:
    return {
        "currency": "AED",
        "sku": "1",
        "url": url,
        "image": image,
        "size": {"value": "100", "unit": "ml"},
        "early": False,
        "series": {"price": [{"amount": price, "currency": "AED"}], "regular": None},
        **kw,
    }


def dataset(retailer: str, products: list[dict[str, Any]]) -> dict[str, Any]:
    meta = {"scope": "ae", "vertical": "beauty", "retailers": [{"id": retailer}]}
    return {"meta": meta, "products": products}


def product(pid: str, retailer: str, name: str, o: dict[str, Any]) -> dict[str, Any]:
    return {"id": pid, "brand": "Dior", "name": name, "category": ["fragrance"],
            "offers": {retailer: o}}  # fmt: skip


FACES = dataset(F, [
    product("f-1-100-ml", F, "Sauvage Eau de Parfum",
            offer("400.00", FACES_IMG.format(1), "https://www.faces.ae/en/p/sauvage-edp.html")),
    product("f-2-100-ml", F, "Fahrenheit Eau de Toilette <script>alert(1)</script>",
            offer("300.00", "https://evil.example/x.jpg", "javascript:alert(1)")),
])  # fmt: skip
ULTA = dataset(U, [
    product("u-1-100-ml", U, "Sauvage Eau de Parfum",
            offer("410.00", "https://media.alshaya.com/u1.jpg", "https://www.ulta.ae/p/u1",
                  series={"price": [{"amount": "410.00"}], "regular": [{"amount": "450.00"}]})),
    product("u-2-100-ml", U, "Fahrenheit Eau de Toilette <script>alert(1)</script>",
            offer("300.00", None, None)),
])  # fmt: skip


def run(tmp: Path, decisions_file: Path | None = None) -> MatchFile:
    faces, ulta = tmp / "faces.json", tmp / "ulta.json"
    faces.write_text(json.dumps(FACES))
    ulta.write_text(json.dumps(ULTA))
    out = tmp / "matches.json"
    argv = [f"--source={F}={faces}", f"--source={U}={ulta}", "--generated-at=2026-10-06T00:00:00Z"]
    if decisions_file is not None:
        argv.append(f"--decisions={decisions_file}")
    assert run_main([*argv, f"--out={out}"]) == 0
    return MatchFile.model_validate_json(out.read_text())


def export(
    tmp: Path, batch: int = 50, name: str = "packet"
) -> tuple[dict[str, Any], dict[str, str]]:
    packet = tmp / name
    argv = ["export", f"--matches={tmp / 'matches.json'}", f"--source={F}={tmp / 'faces.json'}",
            f"--source={U}={tmp / 'ulta.json'}", f"--batch={batch}", f"--out={packet}"]  # fmt: skip
    assert review.main(argv) == 0
    meta = json.loads((packet / "pairs.json").read_text())
    pages = {p.name: p.read_text() for p in packet.glob("*.html")}
    return meta, pages


def test_packet_lists_proposed_exact_pairs_most_confident_first(tmp_path: Path) -> None:
    m = run(tmp_path)
    exact = [e for e in m.edges if e.match_class.value == "exact"]
    assert len(exact) == 2
    assert all(e.review_state is ReviewState.PROPOSED for e in exact)
    meta, pages = export(tmp_path, batch=1)
    assert sorted(pages) == ["batch-01.html", "batch-02.html", "index.html"]
    assert len(meta["pairs"]) == 2
    assert meta["batch"] == 1
    confidences = [
        next(e.confidence or Decimal(0) for e in exact if e.a.token == p["a"]["token"])
        for _, p in sorted(meta["pairs"].items(), key=lambda kv: int(kv[0]))
    ]
    assert confidences == sorted(confidences, reverse=True)
    first = meta["pairs"]["1"]
    assert first["fingerprintA"] == m.listings[F][first["a"]["token"]]
    page = pages["batch-01.html"] + pages["batch-02.html"]
    assert "Yes, same product" in page
    assert "No, different" in page
    assert "Export my decisions" in page
    assert 'data-a="faces_ae:' in page
    assert "Not sure" in page
    assert "(was 450.00)" in page
    assert "410.00 AED" in page


def test_scraped_text_is_escaped_and_only_retailer_hosts_are_shown(tmp_path: Path) -> None:
    run(tmp_path)
    _, pages = export(tmp_path)
    page = "".join(pages.values())
    assert "<script>alert" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "evil.example" not in page
    assert "javascript:" not in page
    assert FACES_IMG.format(1) in page
    assert "https://media.alshaya.com/u1.jpg" in page
    assert "Faces: no photo" in page
    assert "Ulta: no photo" in page


def test_csp_allows_only_the_inline_code_it_ships(tmp_path: Path) -> None:
    run(tmp_path)
    _, pages = export(tmp_path)
    page = pages["batch-01.html"]
    csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', page)
    assert csp is not None
    policy = csp.group(1).replace("&#x27;", "'")
    assert "default-src 'none'" in policy
    assert "unsafe-inline" not in policy
    assert review._hash(review._SCRIPT) in policy
    assert review._hash(review._STYLE) in policy
    assert f"<script>{review._SCRIPT}</script>" in page
    assert f"<script>{review._SCRIPT}</script>" in pages["index.html"]


def answers(meta: dict[str, Any], chosen: dict[str, str]) -> dict[str, Any]:
    return {"packet": meta["packet"], "batch": 1, "answers": chosen}


def test_answers_become_decisions_and_the_next_run_uses_them(tmp_path: Path) -> None:
    run(tmp_path)
    meta, _ = export(tmp_path)
    (tmp_path / "a1.json").write_text(json.dumps(answers(meta, {"1": "yes"})))
    (tmp_path / "a2.json").write_text(json.dumps(answers(meta, {"2": "no"})))
    out = tmp_path / "decisions.jsonl"
    argv = ["import", f"--packet={tmp_path / 'packet' / 'pairs.json'}",
            f"--answers={tmp_path / 'a1.json'}", f"--answers={tmp_path / 'a2.json'}",
            f"--out={out}"]  # fmt: skip
    assert review.main(argv) == 0
    lines = out.read_text().splitlines()
    verdicts = [Decision.model_validate_json(x).verdict for x in lines]
    assert sorted(verdicts) == [Verdict.APPROVE, Verdict.REJECT]
    assert "owner" not in out.read_text()  # the reviewer is never named (SEC-06)
    m = run(tmp_path, out)
    approved = [e for e in m.edges if e.review_state is ReviewState.APPROVED]
    assert len(approved) == 1
    assert approved[0].decided_by == "human"
    yes = meta["pairs"]["1"]
    assert (approved[0].a.token, approved[0].b.token) == (yes["a"]["token"], yes["b"]["token"])
    no = meta["pairs"]["2"]
    assert all(e.a.token != no["a"]["token"] for e in m.edges)  # a rejected pair is gone
    # the packet of the next run leaves out what is decided
    meta2, _ = export(tmp_path, name="packet2")
    assert meta2["pairs"] == {}
    # importing the same answers again changes nothing; a changed mind is refused
    assert review.main([*argv[:-1], f"--decisions={out}", f"--out={out}"]) == 0
    assert out.read_text().splitlines() == lines
    (tmp_path / "a3.json").write_text(json.dumps(answers(meta, {"1": "no"})))
    flip = ["import", f"--packet={tmp_path / 'packet' / 'pairs.json'}",
            f"--answers={tmp_path / 'a3.json'}", f"--decisions={out}", f"--out={out}"]  # fmt: skip
    with pytest.raises(SystemExit, match="already decided the other way"):
        review.main(flip)


def test_answers_are_checked_against_the_packet() -> None:
    pair = {"a": {"retailer": F, "token": "f-1"}, "b": {"retailer": U, "token": "u-1"},
            "fingerprintA": "fa", "fingerprintB": "fb"}  # fmt: skip
    meta = {"packet": "abc", "pairs": {"1": pair, "2": pair}}
    assert decisions(meta, [{"packet": "abc", "answers": {"1": "unsure"}}]) == []
    got = decisions(meta, [{"packet": "abc", "answers": {"1": "yes"}}])
    assert got[0].verdict is Verdict.APPROVE
    assert (got[0].fingerprint_a, got[0].fingerprint_b) == ("fa", "fb")
    with pytest.raises(AnswersError, match="packet"):
        decisions(meta, [{"packet": "other", "answers": {}}])
    with pytest.raises(AnswersError, match="not in the packet"):
        decisions(meta, [{"packet": "abc", "answers": {"9": "yes"}}])
    with pytest.raises(AnswersError, match="unknown answer"):
        decisions(meta, [{"packet": "abc", "answers": {"1": "maybe"}}])
    both = [{"packet": "abc", "answers": {"1": "yes"}}, {"packet": "abc", "answers": {"1": "no"}}]
    with pytest.raises(AnswersError, match="both"):
        decisions(meta, both)
    listed = {"pair": 1, "a": "faces_ae:f-1", "b": "ulta_ae:u-1", "verdict": "yes"}
    got2 = decisions(meta, [{"packet": "abc", "decisions": [listed]}])
    assert got2 == got
    with pytest.raises(AnswersError, match="other listings"):
        decisions(meta, [{"packet": "abc", "decisions": [{**listed, "b": "ulta_ae:u-9"}]}])
    with pytest.raises(AnswersError, match="not in the packet"):
        decisions(meta, [{"packet": "abc", "decisions": [{**listed, "pair": 7}]}])
    with pytest.raises(AnswersError, match="both"):
        decisions(meta, [{"packet": "abc", "answers": {"1": "no"}, "decisions": [listed]}])
    a = ListingRef.model_validate(pair["a"])
    b = ListingRef.model_validate(pair["b"])
    old = Decision(a=a, b=b, verdict=Verdict.LOCK)
    with pytest.raises(AnswersError):
        merged([old], got)


def side(retailer: str, token: str, price: str | None, currency: str = "AED") -> Side:
    amount = None if price is None else Decimal(price)
    size = "100 ml"
    return Side(retailer, token, "Dior", "x", size, None, amount, None, currency, None, None, ())


def test_price_flag_needs_enough_pairs_and_a_real_gap() -> None:
    rows = [
        (side(F, f"f-{i}", "100"), side(U, f"u-{i}", "103" if i % 2 else "100")) for i in range(40)
    ]
    rows.append((side(F, "f-big", "100"), side(U, "u-big", "200")))
    rows.append((side(F, "f-none", None), side(U, "u-none", "100")))
    rows.append((side(F, "f-usd", "100", "USD"), side(U, "u-usd", "300")))
    flags = price_outliers(rows)
    assert list(flags) == [((F, "f-big"), (U, "u-big"))]  # 3% gaps are not flagged
    assert "200" in flags[((F, "f-big"), (U, "u-big"))]
    assert price_outliers(rows[:20] + rows[40:41]) == {}  # too few pairs to judge
