"""Challenge and block detection."""

from __future__ import annotations

from sephora_snapshot import extract

from page_capture import blocks


def test_markers_are_a_superset_of_sephora_snapshot() -> None:
    assert set(extract.CHALLENGE_MARKERS) <= set(blocks.CHALLENGE_MARKERS)
    for extra in ("bm-verify", "/_sec/verify", "validateCaptcha", "Pardon Our Interruption"):
        assert extra in blocks.CHALLENGE_MARKERS


def test_marker_in_short_200_page_is_a_challenge() -> None:
    v = blocks.detect(200, "<html>Pardon Our Interruption</html>")
    assert v is not None
    assert v.kind == blocks.CHALLENGE
    assert "Pardon Our Interruption" in v.reason


def test_marker_in_large_200_page_is_not_a_challenge() -> None:
    body = "<html>captcha" + "x" * blocks.SHORT_PAGE_CHARS
    assert blocks.detect(200, body) is None


def test_marker_beyond_head_is_ignored() -> None:
    body = "x" * blocks.HEAD_CHARS + "bm-verify"
    assert blocks.detect(403, body) is not None  # 403 itself is a block
    assert blocks.detect(200, body) is None


def test_status_blocks() -> None:
    assert blocks.detect(429, "").kind == blocks.RATE_LIMITED  # type: ignore[union-attr]
    assert blocks.detect(401, "").kind == blocks.BLOCKED  # type: ignore[union-attr]
    assert blocks.detect(403, "").kind == blocks.BLOCKED  # type: ignore[union-attr]
    assert blocks.detect(500, "server error") is None
    assert blocks.detect(200, "<html>fine</html>") is None
