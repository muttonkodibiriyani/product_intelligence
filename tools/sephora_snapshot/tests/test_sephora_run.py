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


def test_plan_trpc0_fetches_only_ar_pages(job: tuple[run.Job, list[str]], monkeypatch) -> None:  # type: ignore[no-untyped-def]
    j, calls = job
    monkeypatch.setenv("TRPC", "0")
    j.run_stock("plan.json.gz")
    assert calls == ["html"]  # P100 AR only; P101 has no AR seed
    assert j.counts == {"plan_pids": 2, "pdp_ar_ok": 1}


def test_plan_default_reads_stock_then_ar(job: tuple[run.Job, list[str]]) -> None:
    j, calls = job
    j.run_stock("plan.json.gz")
    assert calls == ["json", "json", "html"]
    j.flush("pdp_ar")
    out = Path(j.local or "") / "out"
    assert sorted(p.name for p in (out / "trpc").iterdir()) == ["part-0000.jsonl.gz"]
    progress = json.loads((out / "progress.json").read_text())
    assert progress["counts"]["trpc_http_200"] == 2


class _Resp:
    def __init__(self, status: int, text: str) -> None:
        self.status_code = status
        self.text = text
        self.content = text.encode()


def test_challenge_stops_the_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BUCKET", f"file:{tmp_path}")
    monkeypatch.setenv("PREFIX", "out")
    monkeypatch.setenv("CUTOFF", "2099-01-01T00:00:00+00:00")
    monkeypatch.setenv("PACE", "0")
    j = run.Job()
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
