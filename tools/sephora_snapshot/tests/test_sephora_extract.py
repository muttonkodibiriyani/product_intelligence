import pytest
from sephora_snapshot import extract
from sephora_synth import details, pdp_html

SM = "http://www.sitemaps.org/schemas/sitemap/0.9"


def test_parse_sitemap_keeps_uae_pdps_only() -> None:
    xml = (
        f'<urlset xmlns="{SM}">'
        "<url><loc>https://www.sephora.me/ae-en/p/serum/P100</loc></url>"
        "<url><loc>https://www.sephora.me/ae-ar/p/serum/P100/</loc></url>"
        "<url><loc>https://www.sephora.me/sa-en/p/serum/P100</loc></url>"
        "<url><loc>https://www.sephora.me/ae-en/brands/acme</loc></url>"
        "</urlset>"
    ).encode()
    got = extract.parse_sitemap(xml)
    assert [(lang, pid) for lang, pid, _ in got] == [("en", "P100"), ("ar", "P100")]


def test_parse_sitemap_rejects_non_xml() -> None:
    with pytest.raises(ValueError, match="not XML"):
        extract.parse_sitemap(b"<html>challenge")


def test_extract_pdp_drops_long_text_and_reads_jsonld() -> None:
    out = extract.extract_pdp(pdp_html(details("P100")))
    assert out["productDetails"]["id"] == "P100"
    assert "longDescription" not in out["productDetails"]
    assert out["jsonld"][0]["description"] == "A synthetic serum."


def test_extract_pdp_without_details_raises() -> None:
    with pytest.raises(ValueError, match="not found"):
        extract.extract_pdp("<html></html>")


@pytest.mark.parametrize(
    ("status", "text", "kind"),
    [
        (403, "<html>/cdn-cgi/challenge-platform/</html>", "challenge"),
        (200, "short page with px-captcha", "challenge"),
        (429, "slow down", "rate_limited"),
        (403, "forbidden", "blocked"),
        (401, "", "blocked"),
    ],
)
def test_detect_block(status: int, text: str, kind: str) -> None:
    verdict = extract.detect_block(status, text)
    assert verdict is not None
    assert verdict.kind == kind


def test_detect_block_ignores_marker_in_large_normal_page() -> None:
    assert extract.detect_block(200, "captcha " + "x" * 70000) is None
    assert extract.detect_block(200, "ok") is None
