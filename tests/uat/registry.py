"""Requirement register and UAT case registry.

Every pilot-scope requirement in ``docs/requirements/traceability.csv`` must have at
least one UAT case under ``tests/uat/cases``. A case is a test function decorated with
:func:`uat`, which attaches the ``uat``, ``req`` and milestone (``m0``..``m5``) markers.

Every acceptance scenario in ``docs/requirements/uat_scenarios.csv`` (UAT-01..UAT-36 of
the Alshaya register) must have exactly one ``tests/uat/test_uat_XX_<slug>.py`` whose test
is decorated with :func:`scenario`, citing the same requirement IDs as the register.
Scenarios outside the pilot scope are skipped with an explicit reason, never deleted.

Pending cases are strict xfails that raise ``NotImplementedError``: when a milestone
lands, replace the body with the real scenario and pass ``implemented=True``. A pending
case that starts passing (XPASS) fails the run, so status cannot silently drift.

Case discovery is static (AST) so the checker and the status report never import or
execute the cases themselves.
"""

from __future__ import annotations

import ast
import csv
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TypeVar, get_args

import pytest

Milestone = Literal["m0", "m1", "m2", "m3", "m4", "m5"]
MILESTONES: Final[tuple[Milestone, ...]] = get_args(Milestone)

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
TRACEABILITY_CSV: Final = REPO_ROOT / "docs" / "requirements" / "traceability.csv"
CASES_DIR: Final = Path(__file__).resolve().parent / "cases"
STATUS_MD: Final = REPO_ROOT / "docs" / "requirements" / "uat_status.md"
SCENARIOS_CSV: Final = REPO_ROOT / "docs" / "requirements" / "uat_scenarios.csv"
SCENARIOS_DIR: Final = Path(__file__).resolve().parent

PENDING_REASON: Final = "not yet implemented"

F = TypeVar("F", bound=Callable[..., object])


@dataclass(frozen=True, slots=True)
class Requirement:
    id: str
    module: str
    priority: str
    gate: str
    requirement: str
    acceptance_criterion: str
    pilot_scope: str

    @property
    def title(self) -> str:
        return self.requirement.split(".", 1)[0].strip()

    @property
    def in_pilot(self) -> bool:
        return self.pilot_scope == "pilot"


@dataclass(frozen=True, slots=True)
class UatCase:
    req_id: str
    milestone: str
    implemented: bool
    name: str
    path: Path
    lineno: int

    @property
    def nodeid(self) -> str:
        return f"{self.path.relative_to(REPO_ROOT).as_posix()}::{self.name}"


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    title: str
    requirement_links: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScenarioCase:
    scenario_id: str
    milestone: str
    reqs: tuple[str, ...]
    out_of_scope: str | None
    implemented: bool
    name: str
    path: Path
    lineno: int

    @property
    def nodeid(self) -> str:
        return f"{self.path.relative_to(REPO_ROOT).as_posix()}::{self.name}"

    @property
    def status(self) -> str:
        if self.out_of_scope is not None:
            return "out of scope"
        return "implemented" if self.implemented else "pending"


def load_scenarios(path: Path = SCENARIOS_CSV) -> dict[str, Scenario]:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    scenarios: dict[str, Scenario] = {}
    for row in rows:
        links = tuple(x.strip() for x in row["requirement_links"].split(";") if x.strip())
        sc = Scenario(row["id"].strip(), row["title"].strip(), links)
        if sc.id in scenarios:
            raise ValueError(f"duplicate scenario id {sc.id!r} in {path}")
        scenarios[sc.id] = sc
    return scenarios


def load_requirements(path: Path = TRACEABILITY_CSV) -> dict[str, Requirement]:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    reqs: dict[str, Requirement] = {}
    for row in rows:
        req = Requirement(
            id=row["id"].strip(),
            module=row["module"].strip(),
            priority=row["priority"].strip(),
            gate=row["gate"].strip(),
            requirement=row["requirement"].strip(),
            acceptance_criterion=row["acceptance_criterion"].strip(),
            pilot_scope=row["pilot_scope"].strip(),
        )
        if req.id in reqs:
            raise ValueError(f"duplicate requirement id {req.id!r} in {path}")
        reqs[req.id] = req
    return reqs


def uat(req_id: str, milestone: Milestone, *, implemented: bool = False) -> Callable[[F], F]:
    """Mark a test as the UAT case for ``req_id``, landing in ``milestone``."""
    if milestone not in MILESTONES:
        raise ValueError(f"unknown milestone {milestone!r}")

    def decorate(fn: F) -> F:
        marks = [pytest.mark.uat, pytest.mark.req(req_id), getattr(pytest.mark, milestone)]
        if not implemented:
            marks.append(
                pytest.mark.xfail(
                    raises=NotImplementedError,
                    strict=True,
                    reason=f"{PENDING_REASON} (lands in {milestone.upper()})",
                )
            )
        for mark in marks:
            fn = mark(fn)
        return fn

    return decorate


def scenario(
    scenario_id: str,
    milestone: Milestone,
    *,
    reqs: tuple[str, ...],
    out_of_scope: str | None = None,
    implemented: bool = False,
) -> Callable[[F], F]:
    """Mark a test as acceptance scenario ``scenario_id`` covering ``reqs``.

    ``out_of_scope`` skips the scenario with that reason (e.g. a market or category the
    pilot does not cover); otherwise it is a strict xfail until ``implemented``.
    """
    if milestone not in MILESTONES:
        raise ValueError(f"unknown milestone {milestone!r}")

    def decorate(fn: F) -> F:
        marks = [
            pytest.mark.uat,
            pytest.mark.scenario(scenario_id),
            *(pytest.mark.req(r) for r in reqs),
            getattr(pytest.mark, milestone),
        ]
        if out_of_scope is not None:
            marks.append(pytest.mark.skip(reason=f"out of pilot scope: {out_of_scope}"))
        elif not implemented:
            marks.append(
                pytest.mark.xfail(
                    raises=NotImplementedError,
                    strict=True,
                    reason=f"{PENDING_REASON} (lands in {milestone.upper()})",
                )
            )
        for mark in marks:
            fn = mark(fn)
        return fn

    return decorate


def pending() -> None:
    """Body of a UAT case whose milestone has not landed yet."""
    raise NotImplementedError(PENDING_REASON)


def _literal(node: ast.expr) -> object:
    try:
        return ast.literal_eval(node)
    except ValueError:
        raise ValueError(f"line {node.lineno}: decorator arguments must be literals") from None


def _call_kwargs(call: ast.Call, positional: tuple[str, ...]) -> dict[str, object]:
    kwargs = {kw.arg: _literal(kw.value) for kw in call.keywords if kw.arg is not None}
    for key, node in zip(positional, call.args, strict=False):
        kwargs[key] = _literal(node)
    return kwargs


def _parse_uat_call(call: ast.Call) -> tuple[str, str, bool]:
    kwargs = _call_kwargs(call, ("req_id", "milestone"))
    req_id, milestone = kwargs.get("req_id"), kwargs.get("milestone")
    implemented = kwargs.get("implemented", False)
    if not (isinstance(req_id, str) and isinstance(milestone, str)):
        raise ValueError(f"line {call.lineno}: uat() needs string req_id and milestone")
    if not isinstance(implemented, bool):
        raise ValueError(f"line {call.lineno}: uat(implemented=...) must be a bool")
    return req_id, milestone, implemented


_FuncDef = ast.FunctionDef | ast.AsyncFunctionDef


def _parse_scenario_call(call: ast.Call) -> tuple[str, str, tuple[str, ...], str | None, bool]:
    kwargs = _call_kwargs(call, ("scenario_id", "milestone"))
    scenario_id, milestone = kwargs.get("scenario_id"), kwargs.get("milestone")
    reqs, out_of_scope = kwargs.get("reqs"), kwargs.get("out_of_scope")
    implemented = kwargs.get("implemented", False)
    if not (isinstance(scenario_id, str) and isinstance(milestone, str)):
        raise ValueError(f"line {call.lineno}: scenario() needs string id and milestone")
    if not (isinstance(reqs, tuple) and all(isinstance(r, str) for r in reqs)):
        raise ValueError(f"line {call.lineno}: scenario(reqs=...) must be a tuple of str")
    if not (out_of_scope is None or isinstance(out_of_scope, str)):
        raise ValueError(f"line {call.lineno}: scenario(out_of_scope=...) must be a str")
    if not isinstance(implemented, bool):
        raise ValueError(f"line {call.lineno}: scenario(implemented=...) must be a bool")
    return scenario_id, milestone, tuple(str(r) for r in reqs), out_of_scope, implemented


def _decorated(paths: list[Path], name: str) -> list[tuple[Path, _FuncDef, ast.Call]]:
    """``(file, function, decorator call)`` for every function decorated with ``name(...)``."""
    found: list[tuple[Path, _FuncDef, ast.Call]] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                found.extend(
                    (path, node, deco)
                    for deco in node.decorator_list
                    if isinstance(deco, ast.Call) and _is_named(deco.func, name)
                )
    return found


def discover_cases(cases_dir: Path = CASES_DIR) -> list[UatCase]:
    """Statically find every ``@uat(...)``-decorated test function."""
    cases: list[UatCase] = []
    for path, node, deco in _decorated(sorted(cases_dir.rglob("test_*.py")), "uat"):
        req_id, milestone, implemented = _parse_uat_call(deco)
        cases.append(UatCase(req_id, milestone, implemented, node.name, path, node.lineno))
    return cases


def discover_scenarios(uat_dir: Path = SCENARIOS_DIR) -> list[ScenarioCase]:
    """Statically find every ``@scenario(...)`` test in ``test_uat_*.py`` files."""
    found: list[ScenarioCase] = []
    for path, node, deco in _decorated(sorted(uat_dir.glob("test_uat_*.py")), "scenario"):
        sid, milestone, reqs, out_of_scope, implemented = _parse_scenario_call(deco)
        found.append(
            ScenarioCase(
                sid, milestone, reqs, out_of_scope, implemented, node.name, path, node.lineno
            )
        )
    return found


def _is_named(func: ast.expr, name: str) -> bool:
    return (isinstance(func, ast.Name) and func.id == name) or (
        isinstance(func, ast.Attribute) and func.attr == name
    )


def check_traceability(reqs: dict[str, Requirement], cases: list[UatCase]) -> list[str]:
    """Return human-readable problems; an empty list means the suite is traceable."""
    problems: list[str] = []
    for case in cases:
        where = f"{case.nodeid} (line {case.lineno})"
        if case.req_id not in reqs:
            problems.append(f"{where}: cites unknown requirement id {case.req_id!r}")
        if case.milestone not in MILESTONES:
            problems.append(f"{where}: unknown milestone {case.milestone!r}")
    covered = {c.req_id for c in cases}
    problems.extend(
        f"{req.id}: pilot-scope requirement has no UAT case"
        for req in reqs.values()
        if req.in_pilot and req.id not in covered
    )
    return problems


def check_scenarios(
    reqs: dict[str, Requirement],
    scenarios: dict[str, Scenario],
    cases: list[ScenarioCase],
) -> list[str]:
    """Every register scenario has exactly one test citing exactly its requirement links."""
    problems = [
        f"{sc.id}: register links unknown requirement id {link!r}"
        for sc in scenarios.values()
        for link in sc.requirement_links
        if link not in reqs
    ]
    seen: dict[str, ScenarioCase] = {}
    for case in cases:
        where = f"{case.nodeid} (line {case.lineno})"
        expected_prefix = f"test_uat_{case.scenario_id.removeprefix('UAT-')}_"
        if not case.path.name.startswith(expected_prefix.lower()):
            problems.append(f"{where}: file name should start with {expected_prefix.lower()}")
        if case.milestone not in MILESTONES:
            problems.append(f"{where}: unknown milestone {case.milestone!r}")
        if case.scenario_id in seen:
            problems.append(f"{where}: duplicate case for {case.scenario_id}")
        seen[case.scenario_id] = case
        sc = scenarios.get(case.scenario_id)
        if sc is None:
            problems.append(f"{where}: cites unknown scenario id {case.scenario_id!r}")
            continue
        problems.extend(
            f"{where}: cites unknown requirement id {r!r}" for r in case.reqs if r not in reqs
        )
        if sorted(case.reqs) != sorted(sc.requirement_links):
            problems.append(
                f"{where}: reqs {list(case.reqs)} differ from register links "
                f"{list(sc.requirement_links)}"
            )
    problems.extend(
        f"{sid}: scenario has no test_uat_*.py case" for sid in scenarios if sid not in seen
    )
    return problems
