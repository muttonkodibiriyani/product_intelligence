"""Old product ids find the product they name now (owner requirement, task 01a0f907, tests 6-9).

Ids are shaped as the export makes them: ``<u|s>-<family>-<size>-<unit>`` alone, ``m-<u>-<s>``
paired. Test 8 (the product page rewrites its link) is the web app's.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from api_fixture import Client, bearer, make_client, write
from pi_api.ids import halves, product_id, product_ids, resolve
from v3_fixture import doc, load

API = "/api/v1"
U1, S1 = "u-fam1-50-ml", "s-fam2-50-ml"
PAIRED = f"m-{U1}-{S1}"  # p01 at A and B, paired since the old links were shared
U2, S2 = "u-fam3-30-ml", "s-fam4-30-ml"  # p15 at C (partial) and p12 at A: a pair, split since
U3, S3, S4 = "u-fam5-10-ml", "s-fam6-10-ml", "s-fam7-10-ml"
REPAIRED = f"m-{U3}-{S4}"  # p02: U3 was paired with S3, now with S4

#: (token, the export's id), from ``scripts/demo_export/v2.py`` at 5aea3eb (``product_id`` line
#: 104, ``pair_token`` line 289; tokens from ``export.py`` ``GroupKey.stable_token`` line 137).
#: The API never imports the export; if either side changes, regenerate these from it.
#: A family long enough that its token, and any pair holding it, is hashed.
LONG = "x" * 120
EXPORT_IDS = (
    (
        "u-1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed-50-ml",
        "u-1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed-50-ml",
    ),
    (
        "s-7f3e0b2a-55aa-4c1e-8d2b-0f6b8e9c1a77-50-ml",
        "s-7f3e0b2a-55aa-4c1e-8d2b-0f6b8e9c1a77-50-ml",
    ),
    ("s-P123:45 B/C-12.5-g", "p-43eafd40d5060941d6cda448"),
    ("u-s-u-9-1-unknown-oz", "u-s-u-9-1-unknown-oz"),
    (
        f"u-{LONG}-30-ml",
        f"u-{LONG}-30-ml",
    ),
    ("s-12345-0.75-unknown", "s-12345-0.75-unknown"),
    (
        "m-u-1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed-50-ml-s-7f3e0b2a-55aa-4c1e-8d2b-0f6b8e9c1a77-50-ml",
        "m-u-1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed-50-ml-s-7f3e0b2a-55aa-4c1e-8d2b-0f6b8e9c1a77-50-ml",
    ),
    (
        "m-u-1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed-50-ml-s-P123:45 B/C-12.5-g",
        "p-b6725c9e9e350fc2db4b2307",
    ),
    (
        "m-u-1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed-50-ml-s-12345-0.75-unknown",
        "m-u-1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed-50-ml-s-12345-0.75-unknown",
    ),
    (
        "m-u-s-u-9-1-unknown-oz-s-7f3e0b2a-55aa-4c1e-8d2b-0f6b8e9c1a77-50-ml",
        "m-u-s-u-9-1-unknown-oz-s-7f3e0b2a-55aa-4c1e-8d2b-0f6b8e9c1a77-50-ml",
    ),
    ("m-u-s-u-9-1-unknown-oz-s-P123:45 B/C-12.5-g", "p-036a2238d727f031415efd6b"),
    ("m-u-s-u-9-1-unknown-oz-s-12345-0.75-unknown", "m-u-s-u-9-1-unknown-oz-s-12345-0.75-unknown"),
    (
        f"m-u-{LONG}-30-ml-s-7f3e0b2a-55aa-4c1e-8d2b-0f6b8e9c1a77-50-ml",
        "p-beaab05a85f2a12afdf00173",
    ),
    (
        f"m-u-{LONG}-30-ml-s-P123:45 B/C-12.5-g",
        "p-8a5eee2cb23b8b6664f66915",
    ),
    (
        f"m-u-{LONG}-30-ml-s-12345-0.75-unknown",
        "p-a6859bcf86fc35aea236e95e",
    ),
)


def renamed(**ids: str) -> dict[str, Any]:
    d = doc()
    d["meta"]["test"] = False
    for product in d["products"]:
        product["id"] = ids.get(product["id"], product["id"])
    return d


def current() -> dict[str, Any]:
    return renamed(p01=PAIRED, p15=U2, p12=S2, p02=REPAIRED)


@pytest.fixture
def client(tmp_path: Path) -> Client:
    write(tmp_path, load(current()))
    return make_client(tmp_path)[0]


def get(client: Client, path: str, status: int = 200, **claims: Any) -> Any:
    response = client.get(f"{API}{path}", headers=bearer(**claims))
    assert response.status_code == status, response.text
    return response.json()


def served_id(answer: Any) -> str:
    """A product detail's id is its card's; a history's is its own."""
    data = answer["data"]
    return str(data["card"]["id"] if "card" in data else data["id"])


@pytest.mark.parametrize(("token", "expected"), EXPORT_IDS)
def test_ids_are_the_exports(token: str, expected: str) -> None:
    assert product_id(token) == expected


def test_an_unhashed_pair_reads_as_its_two_tokens() -> None:
    assert list(halves(PAIRED)) == [(U1, S1)]
    assert list(halves(U1)) == []
    # A family may hold "s-" and "u-": only a Sephora token can follow the split.
    assert list(halves("m-u-s-u-9-1-unknown-oz-s-12345-0.75-unknown")) == [
        ("u-s-u-9-1-unknown-oz", "s-12345-0.75-unknown")
    ]


def test_an_exact_id_is_answered_as_today(client: Client) -> None:
    doc_ = get(client, f"/products/{PAIRED}")
    assert (served_id(doc_), doc_["resolvedFrom"]) == (PAIRED, None)


@pytest.mark.parametrize("old", [U1, S1])
@pytest.mark.parametrize("route", ["/products/{}", "/products/{}/history", "/admin/products/{}"])
def test_6_a_product_paired_since_is_found_by_its_old_id(
    client: Client, route: str, old: str
) -> None:
    answer = get(client, route.format(old), role="admin")
    assert answer["resolvedFrom"] == {"requestedId": old, "currentIds": [PAIRED]}
    assert served_id(answer) == PAIRED
    assert answer["data"] == get(client, route.format(PAIRED), role="admin")["data"]


def test_7_a_split_pair_answers_both_halves_supported_first(client: Client) -> None:
    old = f"m-{U2}-{S2}"
    answer = get(client, f"/products/{old}")
    # The old order is U2 (shop_c, partial) then S2 (shop_a, supported): supported comes first.
    assert answer["resolvedFrom"] == {"requestedId": old, "currentIds": [S2, U2]}
    assert served_id(answer) == S2
    history = get(client, f"/products/{old}/history")
    assert history["resolvedFrom"] == answer["resolvedFrom"]


def test_a_pair_with_a_new_partner_is_found_by_the_old_pair_id(client: Client) -> None:
    old = f"m-{U3}-{S3}"
    answer = get(client, f"/products/{old}")
    assert answer["resolvedFrom"] == {"requestedId": old, "currentIds": [REPAIRED]}


@pytest.mark.parametrize(
    "gone",
    [
        "u-gone-50-ml",
        "u-fam1-30-ml",  # the paired product's family at another size is another product
        "u-fam1",
        f"m-{U1}",
        "m-u-gone-1-ml-s-gone-1-ml",
        "p-0123456789abcdef01234567",
    ],
)
def test_9_a_product_no_shop_sells_is_not_found_and_never_swapped(
    client: Client, gone: str
) -> None:
    assert get(client, f"/products/{gone}", 404)["error"]["code"] == "not_found"
    assert get(client, f"/products/{gone}/history", 404)["error"]["code"] == "not_found"


def test_an_alias_two_products_claim_finds_nothing() -> None:
    ids = product_ids(load(renamed(p01=PAIRED, p02=f"m-{U1}-{S3}")))
    assert ids.dropped == 1
    assert U1 not in ids.aliases
    assert resolve(ids, U1) == ()
    assert [p.id for p in resolve(ids, S1)] == [PAIRED]


def test_an_old_pair_whose_split_is_ambiguous_finds_nothing() -> None:
    # "m-u-a-1-ml-s-b-1-ml-s-c-1-ml" reads as (u-a-1-ml, s-b-1-ml-s-c-1-ml) or
    # (u-a-1-ml-s-b-1-ml, s-c-1-ml): two splits, each naming a different current product.
    ids = product_ids(load(renamed(p12="s-b-1-ml-s-c-1-ml", p15="s-c-1-ml")))
    assert len(list(halves("m-u-a-1-ml-s-b-1-ml-s-c-1-ml"))) == 2
    assert resolve(ids, "m-u-a-1-ml-s-b-1-ml-s-c-1-ml") == ()


def test_pairs_with_hashed_ids_are_counted_for_the_load_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="pi_api.source")
    d = current()
    write(tmp_path, load(d))
    make_client(tmp_path)
    ids = product_ids(load(d))
    at_two = sum(len(p["offers"]) > 1 for p in d["products"])
    # Every product at two retailers except the two ids that read as pairs.
    assert ids.opaque_pairs == at_two - 2
    assert ids.aliases == {U1: PAIRED, S1: PAIRED, U3: REPAIRED, S4: REPAIRED}
    (line,) = [r.getMessage() for r in caplog.records if "old product ids" in r.getMessage()]
    assert (
        f"4 old product ids, 0 dropped as ambiguous, {ids.opaque_pairs} pairs with hashed or "
        "ambiguous ids" in line
    )


#: Reviewer N1 probe: reads as (u-kit-2-pc, s-set-1-unknown-s-P9-1-unknown) and as
#: (u-kit-2-pc-s-set-1-unknown, s-P9-1-unknown), so which members it holds is a guess.
AMBIGUOUS_PAIR = "m-u-kit-2-pc-s-set-1-unknown-s-P9-1-unknown"


def test_a_current_pair_id_with_two_readings_registers_no_aliases() -> None:
    assert len(list(halves(AMBIGUOUS_PAIR))) == 2
    plain = product_ids(load(current()))
    ids = product_ids(load(renamed(p01=PAIRED, p15=U2, p12=S2, p02=AMBIGUOUS_PAIR)))
    assert ids.aliases == {U1: PAIRED, S1: PAIRED}
    for member in ("u-kit-2-pc", "s-P9-1-unknown", "u-kit-2-pc-s-set-1-unknown"):
        assert resolve(ids, member) == ()
    # p02 is at two retailers and no longer reads as one pair: counted for the load log.
    assert ids.opaque_pairs == plain.opaque_pairs + 1
    assert [p.id for p in resolve(ids, AMBIGUOUS_PAIR)] == [AMBIGUOUS_PAIR]


FAMILY = st.text(alphabet="ab-su:9", min_size=1, max_size=8).filter(lambda f: f[0] != "-")


@settings(max_examples=200, deadline=None)
@given(u=FAMILY, s=FAMILY, other=FAMILY)
def test_a_resolved_id_always_holds_the_requested_token(u: str, s: str, other: str) -> None:
    """Whatever the families hold, an answer for an old id is a product holding that id's token
    (or both of an old pair's tokens' products), never a lookalike."""
    tu, ts, to = f"u-{u}-1-ml", f"s-{s}-1-ml", f"s-{other}-1-ml"
    if len({tu, ts, to}) < 3:
        return
    ids = product_ids(load(renamed(p01=f"m-{tu}-{ts}", p12=to)))
    for old in (tu, ts, to, f"m-{tu}-{to}", f"m-{tu}-{ts}"):
        for found in resolve(ids, old):
            held = {found.id, *(t for pair in halves(found.id) for t in pair)}
            named = {old, *(t for pair in halves(old) for t in pair)}
            assert held & named, (old, found.id)


def test_an_exact_id_wins_over_a_pair_naming_it() -> None:
    ids = product_ids(load(renamed(p01=PAIRED, p12=U1)))
    assert U1 not in ids.aliases
    assert [p.id for p in resolve(ids, U1)] == [U1]
    assert [p.id for p in resolve(ids, S1)] == [PAIRED]
