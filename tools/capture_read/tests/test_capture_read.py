"""capture_read on a synthetic capture run in a local directory. No real retailer page is used."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from capture_read import run as cr
from pi_capture.model import loads

SRC = "groups/wave-test"
AT = "2026-10-03T08:00:00+00:00"


def _landmark_page(skus: list[str]) -> str:
    data = {
        "sku": "STYLE",
        "name": "Synthetic Sandal",
        "brand": {"displayValue": "Brandy"},
        "variants": [
            {
                "sku": s,
                "priceInfo": {
                    "price": {"amount": 87, "currency": "AED"},
                    "target": {
                        "priceableFields": {"basePrice": {"amount": 145, "currency": "AED"}}
                    },
                },
            }
            for s in skus
        ],
    }
    state = base64.b64encode(json.dumps({"productPageReducerBL": {"data": data}}).encode())
    nd = json.dumps({"props": {"initialState": state.decode()}})
    return f'<html><body><script id="__NEXT_DATA__">{nd}</script></body></html>'


_GENERIC_PAGE = (
    '<html><head><script type="application/ld+json">{"@type":"Product","name":"Mug",'
    '"sku":"M-1","offers":{"price":"20.00","priceCurrency":"AED"}}</script></head></html>'
)


def _rec(n: int, retailer: str, body: bytes, **over: Any) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "url": f"https://shop.example/p/{n}",
        "final_url": f"https://shop.example/p/{n}",
        "locale": "en-AE",
        "state": "ok",
        "at": AT,
        "sha256": hashlib.sha256(body).hexdigest(),
        "raw": f"raw/{n}.html.gz",
        "ref": {"retailer": retailer, "source": f"{retailer}_ae"},
    }
    rec.update(over)
    return rec


def _capture(root: Path, parts: dict[str, list[tuple[dict[str, Any], bytes]]]) -> cr.LocalBucket:
    bucket = cr.LocalBucket(root)
    for part, rows in parts.items():
        lines = "".join(json.dumps(rec) + "\n" for rec, _body in rows)
        bucket.put(f"{SRC}/pages/{part}", gzip.compress(lines.encode()))
        for rec, body in rows:
            bucket.put(f"{SRC}/{rec['raw']}", gzip.compress(body))
    return bucket


def _job(**over: Any) -> cr.Job:
    return cr.Job(**({"src_prefix": SRC, "locale": "en-AE", "egress": "test-egress"} | over))


def _out(bucket: cr.LocalBucket, name: str) -> list[str]:
    data = gzip.decompress(bucket.get(f"{SRC}/readings/{name}")).decode()
    return [line for line in data.splitlines() if line]


def _ounass_page(division: str) -> bytes:
    pdp = {
        "division": division,
        "department": "Makeup",
        "styleColorId": "900000001_242",
        "nameInEnglish": "Synthetic Lip Tint",
        "priceInAED": 95,
        "outOfStock": True,
    }
    return f"<html><body><script>var s={json.dumps({'pdp': pdp})}</script></body></html>".encode()


def test_a_non_beauty_ounass_page_is_out_of_scope_and_an_out_of_stock_one_is_read(
    tmp_path: Path,
) -> None:
    beauty, fashion = _ounass_page("Beauty"), _ounass_page("Fashion")
    rows = [(_rec(1, "ounass", beauty), beauty), (_rec(2, "ounass", fashion), fashion)]
    bucket = _capture(tmp_path, {"part-0000.jsonl.gz": rows})
    status = cr.run(bucket, _job())
    assert (status["pages_ok"], status["pages_out_of_scope"], status["rows"]) == (1, 1, 1)
    (cap,) = [loads(line) for line in _out(bucket, "part-0000.jsonl.gz")]
    assert next(r.value for r in cap.readings if r.key == "retailer_sku") == "900000001_242"
    assert {"item_in_stock": False} in [r.value for r in cap.readings]
    errors = gzip.decompress(bucket.get(f"{SRC}/readings/errors/part-0000.jsonl.gz")).decode()
    (err,) = [json.loads(line) for line in errors.splitlines()]
    assert (err["state"], err["reason"]) == ("out_of_scope", "division 'Fashion', not Beauty")


def test_landmark_page_gives_one_capture_per_variant(tmp_path: Path) -> None:
    lm = _landmark_page(["111", "222"]).encode()
    gen = _GENERIC_PAGE.encode()
    bucket = _capture(
        tmp_path,
        {"part-0000.jsonl.gz": [(_rec(1, "centrepoint", lm), lm), (_rec(2, "ikea", gen), gen)]},
    )
    status = cr.run(bucket, _job())
    assert status == {"pages": 2, "pages_ok": 2, "parts_read": 1, "rows": 3}
    caps = [loads(line) for line in _out(bucket, "part-0000.jsonl.gz")]
    assert [c.retailer for c in caps] == ["centrepoint", "centrepoint", "ikea"]
    skus = [next(r.value for r in c.readings if r.key == "retailer_sku") for c in caps]
    assert skus == ["111", "222", "M-1"]
    first = caps[0]
    assert first.source == "centrepoint_ae"
    assert first.egress == "test-egress"
    assert first.retrieved_at.isoformat() == AT
    assert "colour_name" in first.looked_for
    assert "colour_name" not in caps[2].looked_for
    assert json.loads(bucket.get(f"{SRC}/readings/status.t0.json")) == status
    assert not bucket.exists(f"{SRC}/readings/errors/part-0000.jsonl.gz")


def test_pages_without_readings_are_listed_with_their_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(html: str, locale: str, url: str | None) -> list[list[Any]]:
        raise RuntimeError("synthetic failure")

    def empty(html: str, locale: str, url: str | None) -> list[list[Any]]:
        return []

    readers = dict(cr.READERS) | {
        "broken": cr.Reader("broken", boom, frozenset()),
        "empty": cr.Reader("empty", empty, frozenset()),
    }
    monkeypatch.setattr(cr, "READERS", readers)
    page = b"<html></html>"
    rows = [
        (_rec(1, "splash", page, sha256="0" * 64), page),
        (_rec(2, "splash", page), page),
        (_rec(3, "broken", page), page),
        (_rec(4, "empty", page), page),
    ]
    bucket = _capture(tmp_path, {"part-0000.jsonl.gz": rows})
    status = cr.run(bucket, _job())
    assert status["pages_sha_mismatch"] == 1
    assert status["pages_not_product"] == 1
    assert status["pages_reader_error"] == 1
    assert status["pages_no_rows"] == 1
    assert _out(bucket, "part-0000.jsonl.gz") == []
    errors = gzip.decompress(bucket.get(f"{SRC}/readings/errors/part-0000.jsonl.gz")).decode()
    got = [json.loads(line) for line in errors.splitlines()]
    assert [e["state"] for e in got] == ["sha_mismatch", "not_product", "reader_error", "no_rows"]
    assert got[1]["reason"] == "no __NEXT_DATA__ script"
    assert got[2]["reason"] == "RuntimeError: synthetic failure"


def test_rows_outside_the_job_are_not_read(tmp_path: Path) -> None:
    gen = _GENERIC_PAGE.encode()
    rows = [
        (_rec(1, "ikea", gen, state="blocked"), gen),
        (_rec(2, "ikea", gen, locale="ar-AE"), gen),
        (_rec(3, "mns", gen), gen),
        (_rec(4, "ikea", gen), gen),
    ]
    bucket = _capture(tmp_path, {"part-0000.jsonl.gz": rows})
    bucket.put(f"{SRC}/pages/notes.txt", b"not a part")
    lines = "\n" + json.dumps(rows[3][0]) + "\n\n"
    bucket.put(f"{SRC}/pages/part-0001.jsonl.gz", gzip.compress(lines.encode()))
    status = cr.run(bucket, _job(retailers=frozenset({"ikea"})))
    assert status == {"pages": 2, "pages_ok": 2, "parts_read": 2, "rows": 2}


def test_a_second_run_skips_parts_already_read_and_reads_new_ones(tmp_path: Path) -> None:
    gen = _GENERIC_PAGE.encode()
    bucket = _capture(tmp_path, {"part-0000.jsonl.gz": [(_rec(1, "ikea", gen), gen)]})
    assert cr.run(bucket, _job())["parts_read"] == 1
    _capture(tmp_path, {"part-0001.jsonl.gz": [(_rec(2, "ikea", gen), gen)]})
    again = cr.run(bucket, _job())
    assert again == {"pages": 1, "pages_ok": 1, "parts_already_read": 1, "parts_read": 1, "rows": 1}


def test_tasks_split_parts_by_name_and_cover_them_all() -> None:
    names = [f"{SRC}/pages/part-t{t}-{n:04d}.jsonl.gz" for t in range(3) for n in range(40)]
    owners = [[i for i in range(4) if cr.mine(p, i, 4)] for p in names]
    assert all(len(o) == 1 for o in owners)
    assert {o[0] for o in owners} == {0, 1, 2, 3}
    # the owner depends on the part's own name only, not on which other parts exist
    assert cr.mine(names[5], owners[5][0], 4)
    assert cr.mine("other/prefix/" + names[5].rsplit("/", 1)[-1], owners[5][0], 4)


def test_readers_by_retailer() -> None:
    assert cr.reader_for("max_fashion") is cr.LANDMARK
    assert cr.reader_for("faces") is cr.FACES
    assert cr.reader_for("ounass") is cr.OUNASS
    assert cr.reader_for("bloomingdales") is cr.BLOOMINGDALES
    assert cr.reader_for("level_shoes") is cr.GENERIC
    faces = cr.FACES.read("<html></html>", "en-AE", None)
    assert len(faces) == 1


def test_job_from_env() -> None:
    bucket, job = cr.job_from_env(
        {
            "BUCKET": "b",
            "SRC_PREFIX": "/uae/wave1/",
            "LOCALE": "en-AE",
            "CAPTURE_EGRESS": "cloud-run-me-central1",
            "RETAILERS": " ikea, ,mns ",
            "CLOUD_RUN_TASK_INDEX": "2",
            "CLOUD_RUN_TASK_COUNT": "4",
            "OUT": "/",
        }
    )
    assert bucket == "b"
    assert job == cr.Job(
        "uae/wave1", "en-AE", "cloud-run-me-central1", "readings", frozenset({"ikea", "mns"}), 2, 4
    )
    _b, plain = cr.job_from_env(
        {"BUCKET": "b", "SRC_PREFIX": "p", "LOCALE": "x", "CAPTURE_EGRESS": "e"}
    )
    assert (plain.retailers, plain.index, plain.count, plain.out) == (None, 0, 1, "readings")
    with pytest.raises(KeyError):
        cr.job_from_env({"BUCKET": "b", "SRC_PREFIX": "p", "LOCALE": "x"})


def test_main_on_a_local_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    gen = _GENERIC_PAGE.encode()
    _capture(tmp_path, {"part-0000.jsonl.gz": [(_rec(1, "ikea", gen), gen)]})
    env = {
        "BUCKET": f"file:{tmp_path}",
        "SRC_PREFIX": SRC,
        "LOCALE": "en-AE",
        "CAPTURE_EGRESS": "e",
    }
    assert cr.main(env) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == 1
    assert cr.main(env, bucket=cr.LocalBucket(tmp_path)) == 0
    assert cr.LocalBucket(tmp_path / "missing").names("x/") == []
