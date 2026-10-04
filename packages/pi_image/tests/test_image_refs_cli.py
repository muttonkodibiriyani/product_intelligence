import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from image_fixtures import GridEmbedder, as_bytes, packshot
from pi_fetch.transports.base import RawResponse
from pi_fetch.types import FetchRequest
from pi_image import cli
from pi_image.fetch import Fetched, ImageCache
from pi_image.model import FetchStatus, ImageRef
from pi_image.refs import refs_from_dataset

S = "https://img-product.sephora.me/dw/"
U = "https://media.alshaya.com/adobe/"
F = "https://www.faces.ae/dw/"


def dataset() -> dict[str, Any]:
    return {
        "schema": "pi.dataset/v3",
        "products": [
            {
                "id": "p1",
                "brand": "Dior",
                "offers": {
                    "sephora_me": {"image": f"{S}1.png"},  # v2 field
                    "ulta_ae": {"content": {"images": [f"{U}1.png", f"{U}1b.png"]}},  # v3
                    "faces_ae": {"content": {"images": []}},
                    "broken": "not an offer",
                },
            },
            {"id": "p2", "brand": " ", "offers": {"faces_ae": {"image": f"{F}2.png"}}},
            {"id": "", "brand": "Dior", "offers": {"faces_ae": {}}},
            {"id": "p3", "offers": None},
        ],
    }


def test_refs_from_dataset() -> None:
    refs = refs_from_dataset(dataset(), str.lower)
    assert refs == (
        ImageRef(source="faces_ae", source_key="p1", brand_key="dior", image_url=None),
        ImageRef(source="faces_ae", source_key="p2", brand_key=None, image_url=f"{F}2.png"),
        ImageRef(source="sephora_me", source_key="p1", brand_key="dior", image_url=f"{S}1.png"),
        ImageRef(source="ulta_ae", source_key="p1", brand_key="dior", image_url=f"{U}1.png"),
    )
    assert refs_from_dataset({}, str.lower) == ()


def test_cli_refs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = tmp_path / "d.json"
    data.write_text(json.dumps(dataset()), encoding="utf-8")
    out = tmp_path / "refs.jsonl"
    assert (
        cli.main(["refs", "--dataset", str(data), "--dataset", str(data), "--out", str(out)]) == 0
    )
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    assert json.loads(capsys.readouterr().out) == {
        "refs": 4,
        "by_source": {"faces_ae": 2, "sephora_me": 1, "ulta_ae": 1},
    }


def write_refs(path: Path, refs: list[ImageRef]) -> None:
    path.write_text("".join(r.model_dump_json() + "\n" for r in refs), encoding="utf-8")


def test_cli_run_offline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cache = ImageCache(tmp_path / "cache" / "images")
    for url, seed in [(f"{S}1.png", 1), (f"{U}1.png", 1), (f"{F}9.png", 5), (f"{U}x.png", 1)]:
        cache.put(Fetched(url, FetchStatus.OK, "image/png", as_bytes(packshot(seed))))
    refs = tmp_path / "refs.jsonl"
    write_refs(
        refs,
        [
            ImageRef(source="sephora_me", source_key="p1", brand_key="dior", image_url=f"{S}1.png"),
            ImageRef(source="ulta_ae", source_key="p1", brand_key="dior", image_url=f"{U}1.png"),
            ImageRef(source="ulta_ae", source_key="p9", brand_key="ysl", image_url=f"{U}x.png"),
            ImageRef(source="faces_ae", source_key="p9", brand_key="dior", image_url=f"{F}9.png"),
            ImageRef(source="faces_ae", source_key="p0", brand_key="dior", image_url=None),
        ],
    )
    out = tmp_path / "out"
    argv = ["run", "--refs", str(refs), "--cache", str(tmp_path / "cache"), "--out", str(out)]
    assert cli.main([*argv, "--offline", "--k", "1"], embedder=GridEmbedder()) == 0
    summary = json.loads(capsys.readouterr().out)
    signals = [json.loads(x) for x in (out / "image_signals.jsonl").read_text().splitlines()]
    aliases = [json.loads(x) for x in (out / "alias_suggestions.jsonl").read_text().splitlines()]
    assert summary == {"pairs": len(signals), "alias_suggestions": len(aliases), "stopped": {}}
    same = [s for s in signals if (s["left_key"], s["right_key"]) == ("p1", "p1")]
    assert [s["via"] for s in same] == ["both"]
    assert [(a["left_source"], a["right_key"], a["right_brand"]) for a in aliases] == [
        ("faces_ae", "p9", "ysl"),  # the ysl listing shows the dior packshot
        ("sephora_me", "p9", "ysl"),
    ]
    meta = json.loads((out / "image_meta.json").read_text())
    assert meta["embedder"] == "test/grid@1"
    assert meta["model"] is None
    assert meta["status"]["faces_ae|missing_image"] == 1
    assert meta["stopped_hosts"] == {}
    status = (out / "image_status.jsonl").read_text()
    assert len(status.splitlines()) == 5
    # same inputs and cache, same outputs
    assert cli.main([*argv, "--offline", "--k", "1"], embedder=GridEmbedder()) == 0
    assert (out / "image_status.jsonl").read_text() == status


class BlockingTransport:
    def __init__(self, *_: object, **__: object) -> None:
        pass

    def send(self, request: FetchRequest, headers: Mapping[str, str]) -> RawResponse:
        url = str(request.url)
        return RawResponse(
            final_url=url, status=429, headers=(), body=b"", content_type=None, elapsed_ms=1
        )

    def close(self) -> None:
        pass


def test_cli_run_stops_on_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "HttpTransport", BlockingTransport)
    refs = tmp_path / "refs.jsonl"
    write_refs(
        refs,
        [
            ImageRef(
                source="sephora_me", source_key=f"p{i}", brand_key="d", image_url=f"{S}{i}.png"
            )
            for i in range(3)
        ],
    )
    out = tmp_path / "out"
    code = cli.main(["run", "--refs", str(refs), "--cache", str(tmp_path / "c"), "--out", str(out)])
    assert code == 1
    meta = json.loads((out / "image_meta.json").read_text())
    assert meta["stopped_hosts"] == {"img-product.sephora.me": "HTTP 429 rate_limited"}
    assert meta["fetch"] == {"not_fetched": 3}  # after the block, nothing more is requested
    assert '"prefetch"' in capsys.readouterr().err


def test_cli_rejects_a_bad_ref(tmp_path: Path) -> None:
    refs = tmp_path / "refs.jsonl"
    refs.write_text('{"source": ""}\n', encoding="utf-8")
    with pytest.raises(SystemExit, match=r"refs\.jsonl:1: invalid ref"):
        cli.main(["run", "--refs", str(refs), "--cache", str(tmp_path), "--out", str(tmp_path)])
