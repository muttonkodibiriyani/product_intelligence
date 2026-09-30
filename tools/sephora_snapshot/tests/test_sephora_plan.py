import gzip
import json
from pathlib import Path

from sephora_snapshot import plan
from sephora_synth import details, pdp_rec, trpc_rec, write_part

PIDS = [f"P{i}" for i in range(100, 110)]


def _snapshot(root: Path) -> Path:
    seed = {p: {"en": f"https://e/{p}", "ar": f"https://a/{p}"} for p in PIDS}
    seed["P999"] = {"en": "https://e/P999"}  # no AR page
    root.mkdir()
    (root / "seed.json").write_bytes(gzip.compress(json.dumps(seed).encode()))
    brands = {"P103": "Brand Ümlaut", "P107": "Other"}
    write_part(root, "pdp_en", [pdp_rec(p, "en", details(p, brands.get(p, "Acme"))) for p in PIDS])
    write_part(root, "trpc", [trpc_rec("P100"), trpc_rec("P101", status=500)])
    write_part(root, "pdp_ar", [pdp_rec("P102", "ar")])
    return root


def test_stock_phase_skips_read_stock_and_has_no_ar(tmp_path: Path) -> None:
    root = _snapshot(tmp_path / "snap")
    out = plan.build(root, "stock", plan.done_pids([root], "stock"))
    assert "P100" not in out["order"]  # stock already read
    assert "P101" in out["order"]  # HTTP 500 is not a read: planned again
    assert "P999" in out["order"]
    assert all(set(v) == {"en"} for v in out["seed"].values())
    assert out["meta"]["already_done"] == 1


def test_ar_phase_skips_fetched_ar_and_en_only(tmp_path: Path) -> None:
    root = _snapshot(tmp_path / "snap")
    out = plan.build(root, "ar", plan.done_pids([root], "ar"))
    assert "P102" not in out["order"]
    assert "P999" not in out["order"]
    assert all(set(v) == {"ar"} for v in out["seed"].values())


def test_order_matched_then_brand_then_rest_and_stable(tmp_path: Path) -> None:
    root = _snapshot(tmp_path / "snap")
    out = plan.build(root, "stock", set(), brands={"brand umlaut"}, matched=["P105", "P404"])
    assert out["order"][:2] == ["P105", "P103"]
    assert sorted(out["order"]) == sorted([*PIDS, "P999"])
    again = plan.build(root, "stock", set(), brands={"brand umlaut"}, matched=["P105"])
    assert again["order"] == out["order"]


def test_main_with_extra_done_folder(tmp_path: Path) -> None:
    root = _snapshot(tmp_path / "snap")
    prior = tmp_path / "stock1"
    write_part(prior, "trpc", [trpc_rec("P104")])
    dest = tmp_path / "plan.json.gz"
    assert plan.main([str(root), str(dest), "--phase", "stock", "--done", str(prior)]) == 0
    got = json.loads(gzip.decompress(dest.read_bytes()))
    assert {"P100", "P104"}.isdisjoint(got["order"])
