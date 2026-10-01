"""prod_smoke_pages: the pure logic and the no-credential guarantees (no browser, no network)."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import prod_smoke_pages as pages
import pytest

SOURCE = Path(pages.__file__).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "text",
    [
        "AED 0.01",
        "AED0.00",
        "0.01 AED",
        "AED\u00a00.01",
        "د.إ 0.01",
        "\u0660\u066b\u0660\u0661 د.إ",
        "د.إ \u0660\u066b\u0660\u0660",
        "AED \u0660.\u0660\u0661",
        "\u200fAED 0,01",
    ],
)
def test_a_rendered_floor_price_is_found(text: str) -> None:
    assert len(pages.low_prices(f"Price {text} today")) == 1


@pytest.mark.parametrize(
    "text",
    [
        "AED 10.01",
        "AED 0.015",
        "AED 100.00",
        "AED 1.01",
        "0.01",
        "AED 0.10",
        "AED \u0661\u0660\u066b\u0660\u0661",
    ],
)
def test_a_real_price_is_not_flagged(text: str) -> None:
    assert pages.low_prices(text) == []


def test_off_host_keeps_only_foreign_urls() -> None:
    urls = [
        "https://media.alshaya.com/a.jpg",
        "https://media.alshaya.com.evil.test/b.jpg",
        "http://media.alshaya.com/c",
    ]
    assert pages.off_host(urls, "media.alshaya.com") == urls[1:]


def test_shot_names_are_flat_and_distinct() -> None:
    assert (
        pages.shot_name("after", "webkit", "mobile", "/app/ar/compare/")
        == "after-webkit-mobile-app-ar-compare.png"
    )
    assert pages.shot_name("before", "firefox", "desktop", "/") == "before-firefox-desktop-root.png"


def test_before_records_info_and_after_fails() -> None:
    before = pages.Report("before")
    before.check("P5 x", ["rendered AED 0.01"], enforced=False)
    before.check("P2 y", [])
    assert before.verdict() == "PASS"
    assert before.notes == ["P5 x: rendered AED 0.01"]
    after = pages.Report("after")
    after.check("P5 x", ["rendered AED 0.01"])
    assert after.verdict() == "FAIL"
    assert after.problems == ["P5 x: rendered AED 0.01"]


def test_after_needs_an_app_category_page() -> None:
    base = ["--out", "x", "--browser", "firefox", "--viewport", "desktop"]
    with pytest.raises(SystemExit):
        pages.parse_args(["--phase", "after", *base])
    with pytest.raises(SystemExit):
        pages.parse_args(["--phase", "after", *base, "--category-page", "/categories/"])
    assert pages.parse_args(["--phase", "before", *base]).category_page is None
    with pytest.raises(SystemExit):
        pages.parse_args(["--phase", "before", *base[:4], "--viewport", "tablet"])


@pytest.mark.parametrize(("problems", "code"), [([], 0), (["P2 /app/en/: document 500"], 1)])
def test_main_writes_one_verdict_file(tmp_path: Path, problems: list[str], code: int) -> None:
    def runner(args: argparse.Namespace) -> pages.Report:
        return pages.Report(
            args.phase, problems=list(problems), notes=["P6 category en: no --category-page given"]
        )

    argv = [
        "--phase",
        "before",
        "--out",
        str(tmp_path),
        "--browser",
        "webkit",
        "--viewport",
        "mobile",
    ]
    assert pages.main(argv, runner) == code
    assert [p.name for p in tmp_path.iterdir()] == ["pages-before-webkit-mobile.json"]
    result = json.loads((tmp_path / "pages-before-webkit-mobile.json").read_text())
    assert result["verdict"] == ("PASS" if code == 0 else "FAIL")
    assert result["problems"] == problems


def test_it_never_handles_a_credential_or_records_the_session() -> None:
    code = re.sub(r'"""[\s\S]*?"""', "", SOURCE, count=1)  # the docstring lists what it never does
    for banned in (
        "environ",
        "getenv",
        "PI_TOKEN",
        "password",
        "storage_state",
        "record_har",
        "tracing",
        "record_video",
        "create_user",
        "delete_user",
        "firebase_admin",
        "sign-up",
        "signUp",
        "headers",
        "cookies",
        "launch_persistent_context",
        "fill(",
    ):
        assert banned not in code, banned


def test_the_browser_runs_headed_and_deps_are_pinned() -> None:
    assert "launch(headless=False)" in SOURCE
    assert '# dependencies = ["playwright==1.63.0"]' in SOURCE


def test_the_lockfile_pins_every_dependency_with_hashes() -> None:
    lock = Path(pages.__file__).with_name("prod_smoke_pages.py.lock").read_text(encoding="utf-8")
    assert 'name = "playwright"\nversion = "1.63.0"' in lock
    assert lock.count('hash = "sha256:') >= lock.count("[[package]]") > 1
