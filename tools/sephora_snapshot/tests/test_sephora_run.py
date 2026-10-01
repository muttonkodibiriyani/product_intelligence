"""Runner phases with a stubbed fetch: no network, output to a local folder."""

import gzip
import json
from pathlib import Path
from typing import Any

import pytest
from sephora_snapshot import run
from sephora_synth import details, pdp_html, trpc_json

PLAN = {
    "order": ["P100", "P101"],
    "seed": {"P100": {"ar": "https://www.sephora.me/ae-ar/p/x/P100"}, "P101": {"en": "e"}},
}


@pytest.fixture
def job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[run.Job, list[str]]:
    (tmp_path / "plan.json.gz").write_bytes(gzip.compress(json.dumps(PLAN).encode()))
    monkeypatch.setenv("BUCKET", f"file:{tmp_path}")
    monkeypatch.setenv("PREFIX", "out")
    monkeypatch.setenv("CUTOFF", "2099-01-01T00:00:00+00:00")
    j = run.Job()
    calls: list[str] = []

    def get(url: str, locale: str, kind: str) -> tuple[int, bytes, dict[str, Any]]:
        calls.append(kind)
        meta = {"url": url, "locale": locale, "at": "2026-09-30T22:00:00+00:00", "status": 200}
        if kind == "json":
            return 200, json.dumps(trpc_json("P100")).encode(), meta
        return 200, pdp_html(details("P100")).encode(), meta

    monkeypatch.setattr(j, "get", get)
    return j, calls


def test_plan_trpc0_fetches_only_ar_pages(job: tuple[run.Job, list[str]]) -> None:
    j, calls = job
    j.trpc_on = False  # as with TRPC=0 in the environment
    j.run_stock("plan.json.gz")
    assert calls == ["html"]  # P100 AR only; P101 has no AR seed
    assert j.counts == {"plan_pids": 2, "pdp_ar_attempted": 1, "pdp_ar_ok": 1}


def test_plan_default_reads_stock_then_ar(job: tuple[run.Job, list[str]]) -> None:
    j, calls = job
    j.run_stock("plan.json.gz")
    assert calls == ["json", "json", "html"]
    j.flush("pdp_ar")
    out = Path(j.local or "") / "out"
    assert sorted(p.name for p in (out / "trpc").iterdir()) == ["part-0000.jsonl.gz"]
    progress = json.loads((out / "progress.json").read_text())
    assert progress["counts"]["trpc_http_200"] == 2


def test_price_plan_rereads_en_pages_then_only_the_listed_stock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, job: tuple[run.Job, list[str]]
) -> None:
    j, calls = job
    price = {
        "order": ["P100", "P101"],
        "seed": {"P100": {"en": "https://www.sephora.me/ae-en/p/x/P100"}, "P101": {"en": "e"}},
        "trpc": ["P101"],
        "meta": {"phase": "price"},
    }
    (tmp_path / "price.json.gz").write_bytes(gzip.compress(json.dumps(price).encode()))
    j.run_stock("price.json.gz")
    assert calls == ["html", "html", "json"]
    assert j.counts["pdp_en_ok"] == 2
    assert j.counts["trpc_http_200"] == 1
    out = Path(j.local or "") / "out"
    assert sorted(p.name for p in (out / "pdp_en").iterdir()) == ["part-0000.jsonl.gz"]


class _Resp:
    def __init__(self, status: int, text: str) -> None:
        self.status_code = status
        self.text = text
        self.content = text.encode()


def test_challenge_stops_the_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BUCKET", f"file:{tmp_path}")
    monkeypatch.setenv("PREFIX", "out")
    monkeypatch.setenv("CUTOFF", "2099-01-01T00:00:00+00:00")
    j = run.Job()
    monkeypatch.setattr(j, "pace", lambda: None)
    monkeypatch.setattr(j.client, "get", lambda *a, **k: _Resp(403, "/cdn-cgi/challenge-platform/"))
    with pytest.raises(run.Stop, match="challenge"):
        j.get("https://www.sephora.me/ae-en/p/x/P1", "en-AE", "html")
    assert j.counts == {"block_challenge": 1}


def test_cutoff_stops_before_any_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BUCKET", f"file:{tmp_path}")
    monkeypatch.setenv("PREFIX", "out")
    monkeypatch.setenv("CUTOFF", "2020-01-01T00:00:00+00:00")
    j = run.Job()
    monkeypatch.setattr(j.client, "get", lambda *a, **k: pytest.fail("no request after cutoff"))
    with pytest.raises(run.Stop, match="cutoff"):
        j.get("https://www.sephora.me/", "en-AE", "html")


def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BUCKET", f"file:{tmp_path}")
    monkeypatch.setenv("PREFIX", "out")
    monkeypatch.setenv("CUTOFF", "2099-01-01T00:00:00+00:00")


def test_pace_below_one_second_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _env(tmp_path, monkeypatch)
    monkeypatch.setenv("PACE", "0.5")
    with pytest.raises(ValueError, match="PACE"):
        run.Job()


def test_progress_records_mode_limit_and_trpc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(tmp_path, monkeypatch)
    monkeypatch.setenv("LIMIT", "50")
    monkeypatch.setenv("TRPC", "0")
    run.Job().progress()
    got = json.loads((tmp_path / "out" / "progress.json").read_text())
    assert (got["mode"], got["limit"], got["trpc"]) == ("full", 50, False)
