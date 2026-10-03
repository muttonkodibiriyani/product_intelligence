"""Product lines across retailers: URL slugs, forms, flankers, line numbers and the related level.

Cases come from the adjudicated gold set (sample-v1) and from Insights' review of the first
three-retailer run.
"""

import pytest

from pi_core.enums import MatchClass
from pi_match.incremental import ALGO_VERSION, hard_conflicts, run
from pi_match.match import concentration_relation, prepare, related_pair, score_pair
from pi_match.model import Bucket, ProductRecord
from pi_match.normalise import (
    Concentration,
    Form,
    ItemKind,
    form,
    is_set_url,
    item_kind,
    line_numbers,
    name_tokens,
    url_words,
)

U, S, F = "ulta_ae", "sephora_me", "faces_ae"


def rec(retailer: str, token: str, name: str, **kw: object) -> ProductRecord:
    fields: dict[str, object] = {
        "source": retailer,
        "source_key": token,
        "brand": kw.pop("brand", "Chanel"),
        "name": name,
        "category": "fragrance",
    }
    fields.update(kw)
    return ProductRecord.model_validate(fields)


def classes(*records: ProductRecord) -> dict[tuple[str, str], MatchClass]:
    by: dict[str, list[ProductRecord]] = {}
    for r in records:
        by.setdefault(r.source, []).append(r)
    m = run(
        by,
        None,
        (),
        scope="ae",
        vertical="beauty",
        algo_version=ALGO_VERSION,
        generated_at="2026-10-03T18:00:00Z",
    )
    return {(e.a.token, e.b.token): e.match_class for e in m.edges}


@pytest.mark.parametrize(
    ("url", "words"),
    [
        ("https://faces.ae/p/gucci-bloom-eaudetoilette-p1.html", "gucci bloom eau de toilette p1"),
        ("https://www.faces.ae/en/p/PM_YSL_Libre_Le_Parfum_EDP.html", "PM YSL Libre Le Parfum EDP"),
        ("https://www.sephora.me/ae-en/p/sauvage-perfume/P1", "P1"),
        (None, ""),
    ],
)  # fmt: skip
def test_url_words(url: str | None, words: str) -> None:
    assert " ".join(url_words(url).split()) == words


def test_set_urls_and_bundle_names() -> None:
    assert is_set_url("https://www.faces.ae/en/p/dior-sauvage-pset0123.html")
    assert is_set_url("https://www.faces.ae/en/p/dior-sauvage-psetPM_Dior_X.html")
    assert is_set_url("https://www.faces.ae/en/p/x-p2set99.html")
    assert is_set_url("https://www.faces.ae/en/p/sauvage-100ml-x-10ml.html")
    assert not is_set_url("https://www.faces.ae/en/p/sauvage-preset-spray.html")
    assert not is_set_url(None)
    assert item_kind("Sauvage EDP 100ml + 10ml") is ItemKind.SET


@pytest.mark.parametrize(
    ("text", "shape"),
    [
        ("Hair and Body Mist", Form.BODY_MIST),
        ("Bloom Hair Mist", Form.HAIR_MIST),
        ("Sauvage Deodorant Stick", Form.DEODORANT),
        ("Coco Shower Gel", Form.SHOWER),
        ("Sauvage After Shave Lotion", Form.AFTERSHAVE),
        ("Sauvage Eau de Parfum", Form.FRAGRANCE),
        ("Rouge Lipstick", None),
    ],
)
def test_form(text: str, shape: Form | None) -> None:
    assert form(text) is shape


def test_line_numbers_ignore_sizes_spf_and_the_shade() -> None:
    assert line_numbers("N°5 Eau de Parfum 100 ml") == {"5"}
    assert line_numbers("212 VIP Men") == {"212"}
    assert line_numbers("Sun Fluid SPF 50+ 50 ml") == frozenset()
    assert line_numbers("Foundation 120 Ivory", "120") == frozenset()
    assert name_tokens("UV Fluid SPF 50+") >= {"spf50plus"}


def test_different_line_numbers_are_different_products() -> None:
    a = prepare(rec(S, "s-1", "N°5 Eau de Parfum", size="100 ml"))
    b = prepare(rec(U, "u-1", "N°19 Eau de Parfum", size="100 ml"))
    assert score_pair(a, b) is None
    assert related_pair(a, b) is None
    # a number on one side only is another product of the line: related at most
    c = prepare(rec(S, "s-2", "The Only One 2 Eau de Parfum", size="50 ml", brand="Dolce"))
    d = prepare(rec(U, "u-2", "The Only One Eau de Parfum", size="50 ml", brand="Dolce"))
    assert score_pair(c, d) is None
    assert "number_differs" in hard_conflicts(c, d)
    related = related_pair(c, d)
    assert related is not None
    assert "related_only" in related[1]


def test_slug_fills_the_concentration_and_flags_a_contradiction() -> None:
    url = "https://www.faces.ae/en/p/chanel-allure-homme-sport-eau-de-toilette-pm1.html"
    faces = prepare(rec(F, "f-1", "Allure Homme Sport", size="100 ml", url=url))
    assert faces.concentration is Concentration.EDT
    assert faces.concentration_from_url
    clash = prepare(rec(F, "f-2", "Allure Homme Sport Eau de Parfum", size="100 ml", url=url))
    assert clash.concentration is Concentration.EDP
    assert clash.flags == ("name_url_concentration_conflict",)
    sephora = prepare(rec(S, "s-1", "Allure Homme Sport Eau de Parfum", size="100 ml"))
    result = score_pair(clash, sephora)
    assert result is not None
    assert result[0] is Bucket.PROBABLE  # never exact while flagged


def test_slugs_that_file_parfum_under_eau_de_parfum() -> None:
    # The name says Parfum, the slug says eau-de-parfum: the name wins, with no flag.
    url = "https://www.faces.ae/en/p/scandal-elixir-parfum-eau-de-parfum-pm1.html"
    named = prepare(rec(F, "f-1", "Scandal Elixir Parfum", size="80 ml", url=url))
    assert named.concentration is Concentration.PARFUM
    assert named.flags == ()
    # Only the slug speaks (EDP) and the other side states Parfum: unknown, not a conflict,
    # so the pair is reviewed instead of exact, and never kept apart as related.
    url = "https://www.faces.ae/en/p/the-scent-elixir-intense-eau-de-parfum-pm2.html"
    slug_only = prepare(rec(F, "f-2", "The Scent Elixir Intense", size="50 ml", url=url))
    stated = prepare(rec(S, "s-2", "The Scent Elixir - Parfum Intense", size="50 ml"))
    assert concentration_relation(slug_only, stated) == "unknown"
    assert "concentration_differs" not in hard_conflicts(slug_only, stated)
    result = score_pair(slug_only, stated)
    assert result is not None
    assert result[0] is Bucket.PROBABLE
    # Two stated concentrations still differ.
    edp = prepare(rec(U, "u-3", "The Scent Elixir Eau de Parfum Intense", size="50 ml"))
    assert concentration_relation(edp, stated) == "differs"


def test_name_and_size_field_disagree() -> None:
    item = prepare(rec(U, "u-1", "Sauvage EDP 50 ml", size="100 ml"))
    assert item.flags == ("name_size_conflict",)


def test_forms_flankers_and_sets_are_related_never_exact() -> None:
    url = "https://www.faces.ae/en/p/chanel-chance-pset0123.html"
    got = classes(
        rec(U, "u-1-100-ml", "Chance Eau de Toilette", size="100 ml"),
        rec(S, "s-1-100-ml", "Chance Eau de Toilette Body Mist", size="100 ml"),
        rec(S, "s-2-100-ml", "Chance Eau de Toilette Intense", size="100 ml"),
        rec(F, "f-1-100-ml", "Chance Eau de Toilette", size="100 ml", url=url),
    )
    assert got[("s-1-100-ml", "u-1-100-ml")] is MatchClass.SUBSTITUTE  # form
    assert got[("s-2-100-ml", "u-1-100-ml")] is MatchClass.SUBSTITUTE  # flanker
    assert got[("f-1-100-ml", "u-1-100-ml")] is MatchClass.SUBSTITUTE  # a set by its URL
    assert MatchClass.EXACT not in got.values()
    # two different flankers of a line are other scents, not stand-ins for each other
    got = classes(
        rec(U, "u-1-50-ml", "Chance Eau Tendre Eau de Toilette", size="50 ml"),
        rec(S, "s-1-50-ml", "Chance Eau Vive Eau de Toilette", size="50 ml"),
    )
    assert got == {}


def test_a_listing_without_a_size_is_family_of_the_line() -> None:
    got = classes(
        rec(U, "u-1", "Browliner Blackstar", brand="By Terry", category="makeup"),
        rec(S, "s-1-0.3-g", "Browliner Blackstar", brand="By Terry", size="0.3 g"),
    )
    assert got == {("s-1-0.3-g", "u-1"): MatchClass.FAMILY}
    # not when a concentration is known on one side only: "Bloom" may be any of the line
    got = classes(
        rec(U, "u-2", "Bloom", brand="Gucci"),
        rec(S, "s-2-50-ml", "Bloom Eau de Parfum", brand="Gucci", size="50 ml"),
    )
    assert got == {}


def test_own_brands_never_match() -> None:
    a = prepare(rec(S, "s-1", "Cleansing Water", brand="Sephora Collection", size="200 ml"))
    b = prepare(rec(U, "u-1", "Cleansing Water", brand="Sephora Collection", size="200 ml"))
    assert score_pair(a, b) is None
    assert related_pair(a, b) is None


def test_related_needs_a_strong_name_and_no_gtin_disagreement() -> None:
    a = prepare(rec(S, "s-1", "Coco Mademoiselle Eau de Parfum", size="100 ml"))
    b = prepare(rec(U, "u-1", "Chance Eau de Toilette", size="100 ml"))
    assert related_pair(a, b) is None  # weak name
    c = prepare(rec(U, "u-2", "Coco Mademoiselle Eau de Parfum", size="100 ml"))
    assert related_pair(a, c) is None  # no rule keeps them apart: score_pair's business
    d = prepare(rec(U, "u-3", "Coco Mademoiselle Body Lotion", size="200 ml", gtin="0012345678905"))
    e = prepare(
        rec(S, "s-3", "Coco Mademoiselle Eau de Parfum", size="100 ml", gtin="4006381333931")
    )
    assert related_pair(d, e) is None
