"""Requirement register and UAT case registry.

Every pilot-scope requirement in ``docs/requirements/traceability.csv`` must have at
least one UAT case under ``tests/uat/cases``. A case is a test function decorated with
:func:`uat`, which attaches the ``uat``, ``req`` and milestone (``m0``..``m5``) markers.

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


def pending() -> None:
    """Body of a UAT case whose milestone has not landed yet."""
    raise NotImplementedError(PENDING_REASON)


def _literal(node: ast.expr) -> object:
    try:
        return ast.literal_eval(node)
    except ValueError:
        raise ValueError(f"line {node.lineno}: uat() arguments must be literals") from None


def _parse_uat_call(call: ast.Call) -> tuple[str, str, bool]:
    args = [_literal(a) for a in call.args]
    kwargs = {kw.arg: _literal(kw.value) for kw in call.keywords if kw.arg is not None}
    positional = ("req_id", "milestone")
    for key, value in zip(positional, args, strict=False):
        kwargs[key] = value
    req_id, milestone = kwargs.get("req_id"), kwargs.get("milestone")
    implemented = kwargs.get("implemented", False)
    if not (isinstance(req_id, str) and isinstance(milestone, str)):
        raise ValueError(f"line {call.lineno}: uat() needs string req_id and milestone")
    if not isinstance(implemented, bool):
        raise ValueError(f"line {call.lineno}: uat(implemented=...) must be a bool")
    return req_id, milestone, implemented


def discover_cases(cases_dir: Path = CASES_DIR) -> list[UatCase]:
    """Statically find every ``@uat(...)``-decorated test function."""
    cases: list[UatCase] = []
    for path in sorted(cases_dir.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for deco in node.decorator_list:
                if not (isinstance(deco, ast.Call) and _is_uat_name(deco.func)):
                    continue
                req_id, milestone, implemented = _parse_uat_call(deco)
                cases.append(UatCase(req_id, milestone, implemented, node.name, path, node.lineno))
    return cases


def _is_uat_name(func: ast.expr) -> bool:
    return (isinstance(func, ast.Name) and func.id == "uat") or (
        isinstance(func, ast.Attribute) and func.attr == "uat"
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
