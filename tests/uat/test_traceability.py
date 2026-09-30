"""Guards the UAT suite's traceability to docs/requirements/traceability.csv."""

from __future__ import annotations

from pathlib import Path

import pytest

from uat import report
from uat.registry import (
    MILESTONES,
    PENDING_REASON,
    Requirement,
    Scenario,
    ScenarioCase,
    UatCase,
    check_scenarios,
    check_traceability,
    discover_cases,
    discover_scenarios,
    load_requirements,
    load_scenarios,
    pending,
    scenario,
    uat,
)


def _req(req_id: str, scope: str = "pilot") -> Requirement:
    return Requirement(req_id, "Mod", "P0", "Foundation", "Title. Body.", "Accept.", scope)


def _case(req_id: str, milestone: str = "m0", *, implemented: bool = False) -> UatCase:
    return UatCase(req_id, milestone, implemented, "test_x", Path(__file__), 1, "T. Body.\nAccept.")


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


def test_checker_flags_docstrings_that_drift_from_the_register() -> None:
    reqs = {"A-1": _req("A-1"), "B-1": _req("B-1", "deviation")}
    rewrapped = UatCase("A-1", "m0", False, "t", Path(__file__), 1, "Title.\n  Body.\n Accept.")
    stale = UatCase("A-1", "m0", False, "t", Path(__file__), 2, "Title. Old body. Accept.")
    custom = UatCase("B-1", "m0", False, "t", Path(__file__), 3, "Replacement control.")
    assert check_traceability(reqs, [rewrapped, custom]) == []
    problems = check_traceability(reqs, [stale])
    assert problems == [
        f"{stale.nodeid} (line 2): docstring requirement drifted from traceability.csv"
    ]


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


# ------------------------------------------------------------------ acceptance scenarios


def _scase(
    sid: str,
    reqs: tuple[str, ...],
    *,
    milestone: str = "m1",
    out_of_scope: str | None = None,
    implemented: bool = False,
) -> ScenarioCase:
    name = f"test_uat_{sid.removeprefix('UAT-')}_x.py"
    return ScenarioCase(
        sid, milestone, reqs, out_of_scope, implemented, "test_x", Path(__file__).parent / name, 1
    )


def test_every_register_scenario_has_one_case_citing_its_links() -> None:
    problems = check_scenarios(
        load_requirements(), load_scenarios(), discover_scenarios(), discover_cases()
    )
    assert problems == [], "\n".join(problems)


def test_scenario_register_has_the_36_alshaya_scenarios() -> None:
    assert list(load_scenarios()) == [f"UAT-{n:02d}" for n in range(1, 37)]


def test_out_of_scope_scenarios_are_skipped_with_a_reason_not_deleted() -> None:
    skipped = {c.scenario_id: c.out_of_scope for c in discover_scenarios() if c.out_of_scope}
    assert set(skipped) == {"UAT-06", "UAT-10", "UAT-11", "UAT-29", "UAT-33"}
    assert all(reason.strip() for reason in skipped.values())


def test_check_scenarios_flags_every_mismatch() -> None:
    reqs = {"A-1": _req("A-1"), "A-2": _req("A-2")}
    scenarios = {
        "UAT-01": Scenario("UAT-01", "One", ("A-1", "A-2")),
        "UAT-02": Scenario("UAT-02", "Two", ("A-1",)),
        "UAT-03": Scenario("UAT-03", "Three", ("Z-9",)),
    }
    cases = [
        _scase("UAT-01", ("A-2", "A-1")),  # order-insensitive: fine
        _scase("UAT-01", ("A-1", "A-2")),
        ScenarioCase(
            "UAT-02",
            "m9",
            ("A-1", "Q-1"),
            None,
            False,
            "t",
            Path(__file__).parent / "test_uat_2.py",
            1,
        ),
        _scase("UAT-99", ("A-1",)),
    ]
    problems = check_scenarios(reqs, scenarios, cases)
    assert problems[0] == "UAT-03: register links unknown requirement id 'Z-9'"
    joined = "\n".join(problems)
    for fragment in (
        "duplicate case for UAT-01",
        "file name should start with test_uat_02_",
        "unknown milestone 'm9'",
        "cites unknown requirement id 'Q-1'",
        "reqs ['A-1', 'Q-1'] differ from register links ['A-1']",
        "cites unknown scenario id 'UAT-99'",
        "UAT-03: scenario has no test_uat_*.py case",
    ):
        assert fragment in joined
    assert len(problems) == 8


def test_scenario_may_not_land_before_its_requirements() -> None:
    reqs = {"A-1": _req("A-1"), "A-2": _req("A-2")}
    scenarios = {"UAT-01": Scenario("UAT-01", "One", ("A-1", "A-2"))}
    req_cases = [_case("A-1", "m1"), _case("A-2", "m3"), _case("A-9", "m9")]
    early = check_scenarios(reqs, scenarios, [_scase("UAT-01", ("A-1", "A-2"))], req_cases)
    assert len(early) == 1
    assert early[0].endswith("milestone m1 is before its linked requirements (m3)")
    ok = [_scase("UAT-01", ("A-1", "A-2"), milestone="m4")]
    assert check_scenarios(reqs, scenarios, ok, req_cases) == []


def test_load_scenarios_rejects_duplicate_ids(tmp_path: Path) -> None:
    csv_path = tmp_path / "s.csv"
    csv_path.write_text("id,title,requirement_links\n" + "UAT-01,t,A-1\n" * 2, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate scenario id 'UAT-01'"):
        load_scenarios(csv_path)


def test_discover_scenarios_reads_arguments(tmp_path: Path) -> None:
    (tmp_path / "test_uat_01_a.py").write_text(
        "@scenario('UAT-01', 'm1', reqs=('A-1', 'A-2'))\n"
        "def test_a() -> None: ...\n"
        "@registry.scenario(scenario_id='UAT-02', milestone='m2', reqs=('B-1',),\n"
        "    out_of_scope='food', implemented=False)\n"
        "def test_b() -> None: ...\n",
        encoding="utf-8",
    )
    (tmp_path / "test_other.py").write_text("@scenario('UAT-09', 'm1', reqs=())\n")
    got = [(c.scenario_id, c.milestone, c.reqs, c.status) for c in discover_scenarios(tmp_path)]
    assert got == [
        ("UAT-01", "m1", ("A-1", "A-2"), "pending"),
        ("UAT-02", "m2", ("B-1",), "out of scope"),
    ]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ("'UAT-01', reqs=()", "needs string id and milestone"),
        ("'UAT-01', 'm1', reqs=['A-1']", "must be a tuple of str"),
        ("'UAT-01', 'm1', reqs=(), out_of_scope=1", "out_of_scope=...\\) must be a str"),
        ("'UAT-01', 'm1', reqs=(), implemented=1", "implemented=...\\) must be a bool"),
    ],
)
def test_discover_scenarios_rejects_malformed_decorators(
    tmp_path: Path, args: str, message: str
) -> None:
    (tmp_path / "test_uat_01_x.py").write_text(f"@scenario({args})\ndef test_a() -> None: ...\n")
    with pytest.raises(ValueError, match=message):
        discover_scenarios(tmp_path)


def test_scenario_decorator_marks() -> None:
    def a() -> None: ...

    def b() -> None: ...

    def c() -> None: ...

    pend = {m.name: m for m in scenario("UAT-01", "m2", reqs=("A-1", "A-2"))(a).pytestmark}  # type: ignore[attr-defined]
    assert pend["scenario"].args == ("UAT-01",)
    assert pend["xfail"].kwargs["strict"] is True
    assert {m.args for m in a.pytestmark if m.name == "req"} == {("A-1",), ("A-2",)}  # type: ignore[attr-defined]
    oos = {m.name: m for m in scenario("UAT-01", "m2", reqs=(), out_of_scope="food")(b).pytestmark}  # type: ignore[attr-defined]
    assert oos["skip"].kwargs["reason"] == "out of pilot scope: food"
    assert "xfail" not in oos
    done = {m.name for m in scenario("UAT-01", "m2", reqs=(), implemented=True)(c).pytestmark}  # type: ignore[attr-defined]
    assert not done & {"xfail", "skip"}
    with pytest.raises(ValueError, match="unknown milestone"):
        scenario("UAT-01", "m9", reqs=())  # type: ignore[arg-type]


def test_render_lists_scenarios_with_status() -> None:
    scenarios = {
        "UAT-01": Scenario("UAT-01", "One", ("A-1",)),
        "UAT-02": Scenario("UAT-02", "Two", ("A-1",)),
        "UAT-03": Scenario("UAT-03", "Three", ("A-1",)),
        "UAT-04": Scenario("UAT-04", "Four", ("A-1",)),
    }
    cases = [
        _scase("UAT-01", ("A-1",), implemented=True),
        _scase("UAT-02", ("A-1",)),
        _scase("UAT-03", ("A-1",), out_of_scope="food | dine-in"),
    ]
    text = report.render({"A-1": _req("A-1")}, [], scenarios, cases)
    assert "implemented 1, pending 1, out of scope 1, missing 1." in text
    assert "| UAT-03 | Three | A-1 | M1 | out of scope: food \\| dine-in |" in text
    assert "| UAT-04 | Four | A-1 | — | missing | — |" in text
