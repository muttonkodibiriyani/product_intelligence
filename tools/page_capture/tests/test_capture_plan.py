"""Plan parsing, validation and sharding."""

from __future__ import annotations

import gzip
import json

import pytest

from page_capture import plan

DOC = {
    "source": "faces",
    "retailer": "faces",
    "version": 1,
    "default_headers": {"X-A": "1"},
    "items": [
        {"id": "a", "url": "https://x.example/en/p/a.html", "locale": "en-AE"},
        {
            "id": "b",
            "url": "https://x.example/api/b",
            "locale": "ar-AE",
            "kind": "json",
            "ref": {"sku": "B"},
            "images": ["https://img.example/b.jpg"],
            "headers": {"X-B": "2"},
        },
    ],
}


def test_parse_plain_and_gzip() -> None:
    raw = json.dumps(DOC).encode()
    for data in (raw, gzip.compress(raw)):
        p = plan.parse_plan(data)
        assert p.source == "faces"
        assert p.default_headers == {"X-A": "1"}
        assert p.items[0].kind == "html"
        assert p.items[0].images == ()
        assert p.items[1].kind == "json"
        assert p.items[1].images == ("https://img.example/b.jpg",)
        assert p.items[1].headers == {"X-B": "2"}
        assert p.to_json()["items"][1]["ref"] == {"sku": "B"}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(source=""),
        lambda d: d.update(version=2),
        lambda d: d.update(items=[]),
        lambda d: d.update(items="nope"),
        lambda d: d["items"].append(dict(d["items"][0])),  # duplicate id
        lambda d: d["items"][0].update(id=""),
        lambda d: d["items"][0].update(locale="en"),
        lambda d: d["items"][0].update(kind="pdf"),
        lambda d: d["items"][0].update(url="ftp://x.example/a"),
        lambda d: d["items"][0].update(url=None),
        lambda d: d["items"][0].update(ref=[]),
        lambda d: d["items"][0].update(images="x"),
        lambda d: d["items"][0].update(images=["not a url"]),
        lambda d: d["items"][0].update(headers={"a": 1}),
        lambda d: d.update(default_headers=["x"]),
    ],
)
def test_validation_errors(mutate: object) -> None:
    doc = json.loads(json.dumps(DOC))
    mutate(doc)  # type: ignore[operator]
    with pytest.raises(ValueError, match=r".+"):
        plan.plan_from_json(doc)


def test_top_level_must_be_object() -> None:
    with pytest.raises(ValueError, match="top level"):
        plan.parse_plan(b"[]")


def test_shard() -> None:
    items = plan.plan_from_json(DOC).items
    assert [i.id for i in plan.shard(items, 0, 2)] == ["a"]
    assert [i.id for i in plan.shard(items, 1, 2)] == ["b"]
    assert [i.id for i in plan.shard(items, 0, 1)] == ["a", "b"]
    assert plan.shard(items, 2, 3) == []
    with pytest.raises(ValueError, match="task index"):
        plan.shard(items, 2, 2)
