"""Guards the UAT suite's traceability to docs/requirements/traceability.csv."""

from __future__ import annotations

from pathlib import Path

import pytest

from uat import report
from uat.registry import (
    MILESTONES,
    PENDING_REASON,
    Requirement,
    UatCase,
    check_traceability,
    discover_cases,
    load_requirements,
    pending,
    uat,
)


def _req(req_id: str, scope: str = "pilot") -> Requirement:
    return Requirement(req_id, "Mod", "P0", "Foundation", "Title. Body.", "Accept.", scope)


def _case(req_id: str, milestone: str = "m0", *, implemented: bool = False) -> UatCase:
    return UatCase(req_id, milestone, implemented, "test_x", Path(__file__), 1)


def test_every_pilot_requirement_has_a_case_and_no_case_cites_an_unknown_id() -> None:
    problems = check_traceability(load_requirements(), discover_cases())
    assert problems == [], "\n".join(problems)


def test_register_matches_blueprint_counts() -> None:
    # Blueprint §17: 162 requirements, 127 pilot scope, 2 owner deviations.
    reqs = load_requirements()
    scopes = [r.pilot_scope for r in reqs.values()]
    assert len(reqs) == 162
    assert scopes.count("pilot") == 127
    assert sorted(r.id for r in reqs.values() if r.pilot_scope == "deviation") == [
        "SEC-05",
        "SRC-08",
    ]


def test_every_case_uses_a_known_milestone_and_unique_name() -> None:
    cases = discover_cases()
    assert {c.milestone for c in cases} <= set(MILESTONES)
    assert len({c.nodeid for c in cases}) == len(cases)


def test_status_report_is_up_to_date() -> None:
    assert report.main(["--check"]) == 0, "run `make uat-status` and commit the result"


def test_checker_flags_unknown_id_bad_milestone_and_missing_case() -> None:
    reqs = {"AAA-01": _req("AAA-01"), "AAA-02": _req("AAA-02"), "BBB-01": _req("BBB-01", "later")}
    problems = check_traceability(reqs, [_case("AAA-01"), _case("ZZZ-99", "m9")])
    assert len(problems) == 3
    assert "cites unknown requirement id 'ZZZ-99'" in problems[0]
    assert "unknown milestone 'm9'" in problems[1]
    assert problems[2] == "AAA-02: pilot-scope requirement has no UAT case"


def test_load_requirements_rejects_duplicate_ids(tmp_path: Path) -> None:
    csv_path = tmp_path / "t.csv"
    header = "id,module,priority,gate,requirement,acceptance_criterion,pilot_scope\n"
    csv_path.write_text(header + "A-1,m,P0,F,r,a,pilot\n" * 2, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate requirement id 'A-1'"):
        load_requirements(csv_path)


def test_discover_cases_reads_positional_keyword_and_attribute_forms(tmp_path: Path) -> None:
    (tmp_path / "test_x.py").write_text(
        "import pytest\n"
        "from uat import registry\n"
        "@uat('A-1', 'm1')\n"
        "def test_a() -> None: ...\n"
        "@registry.uat(req_id='A-2', milestone='m2', implemented=True)\n"
        "async def test_b() -> None: ...\n"
        "@pytest.mark.slow\n"
        "@helper()\n"
        "def test_c() -> None: ...\n",
        encoding="utf-8",
    )
    got = [(c.req_id, c.milestone, c.implemented, c.name) for c in discover_cases(tmp_path)]
    assert got == [("A-1", "m1", False, "test_a"), ("A-2", "m2", True, "test_b")]


@pytest.mark.parametrize(
    ("decorator", "message"),
    [
        ("@uat(REQ, 'm1')", "must be literals"),
        ("@uat('A-1')", "needs string req_id and milestone"),
        ("@uat('A-1', 'm1', implemented=1)", "must be a bool"),
    ],
)
def test_discover_cases_rejects_malformed_decorators(
    tmp_path: Path, decorator: str, message: str
) -> None:
    (tmp_path / "test_bad.py").write_text(f"{decorator}\ndef test_a() -> None: ...\n")
    with pytest.raises(ValueError, match=message):
        discover_cases(tmp_path)


def test_uat_decorator_marks_pending_cases_as_strict_xfail() -> None:
    def case() -> None: ...

    marks = {m.name: m for m in uat("A-1", "m3")(case).pytestmark}  # type: ignore[attr-defined]
    assert set(marks) == {"uat", "req", "m3", "xfail"}
    assert marks["req"].args == ("A-1",)
    assert marks["xfail"].kwargs["strict"] is True
    assert marks["xfail"].kwargs["raises"] is NotImplementedError

    def done() -> None: ...

    names = {m.name for m in uat("A-1", "m3", implemented=True)(done).pytestmark}  # type: ignore[attr-defined]
    assert "xfail" not in names


def test_uat_decorator_rejects_unknown_milestone() -> None:
    with pytest.raises(ValueError, match="unknown milestone"):
        uat("A-1", "m9")  # type: ignore[arg-type]


def test_pending_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match=PENDING_REASON):
        pending()


def test_render_reports_status_per_requirement() -> None:
    reqs = {
        "A-1": _req("A-1"),
        "A-2": _req("A-2"),
        "A-3": _req("A-3"),
        "B-1": _req("B-1", "later"),
    }
    cases = [_case("A-1", "m1", implemented=True), _case("A-2", "m2"), _case("B-1")]
    text = report.render(reqs, cases)
    assert "| A-1 | Mod | P0 | Foundation | Title | M1 | implemented |" in text
    assert "| A-2 | Mod | P0 | Foundation | Title | M2 | pending |" in text
    assert "| A-3 | Mod | P0 | Foundation | Title | — | missing | — |" in text
    assert "implemented 1, pending 1, missing 1" in text
    assert "Cases also exist for non-pilot (later or deviation) requirements: B-1." in text


def test_report_main_writes_then_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "uat_status.md"
    monkeypatch.setattr(report, "STATUS_MD", target)
    assert report.main(["--check"]) == 1
    assert "is stale" in capsys.readouterr().err
    assert report.main([]) == 0
    assert report.main(["--check"]) == 0
