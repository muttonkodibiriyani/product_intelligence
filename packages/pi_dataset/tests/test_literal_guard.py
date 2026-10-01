"""The ADR-0007 literal guard, extended to attribute keys and enum values (ADR-0008 §3).

A key or enum value declared by any committed profile must not appear as a quoted literal in
``pi_api``, ``pi_metrics`` or ``apps/web`` outside fixtures and contracts: those read the
declaration from the snapshot's ``meta.attributeSet``. The only exceptions are the two beauty
constants the dashboard still hard-codes, until step 6 replaces them with ``attributeSet`` and
``meta.taxonomy`` data and deletes these entries.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pi_dataset import committed_profile, committed_profiles

ROOT = Path(__file__).resolve().parents[3]
SCANNED = (
    "packages/pi_api/src",
    "packages/pi_metrics/src",
    "apps/web/src",
    "apps/web/app",
    "apps/web/components",
    "apps/web/lib",
)
SUFFIXES = {".py", ".js", ".mjs", ".ts", ".tsx"}
#: Generated from the contracts, so declared names may appear in them.
CONTRACT_FILES = {"apps/web/lib/api/schema.gen.ts"}
#: Beauty exceptions (ADR-0008 §3), file -> constants whose definition line is not scanned.
#: Step 6 removes them; ``test_every_exception_still_has_its_constant`` fails once one is gone.
BEAUTY_EXCEPTIONS = {"apps/web/src/data.js": ("FAMS", "CATS")}


def _declared() -> set[str]:
    names: set[str] = set()
    for ref in committed_profiles():
        name, _, version = ref.partition("@")
        profile = committed_profile(name, int(version))
        assert profile is not None
        for attribute in profile.attribute_set:
            names.add(attribute.key)
            names.update(v.id for v in attribute.values or ())
    return names


def _files() -> list[Path]:
    return sorted(
        path
        for root in SCANNED
        if (ROOT / root).is_dir()
        for path in (ROOT / root).rglob("*")
        if path.suffix in SUFFIXES
        and "node_modules" not in path.parts
        and path.relative_to(ROOT).as_posix() not in CONTRACT_FILES
    )


def _definition(constant: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*(export\s+)?(const|let|var)\s+{constant}\s*=")


def _literal(names: set[str]) -> re.Pattern[str]:
    alternatives = "|".join(map(re.escape, sorted(names)))
    return re.compile(rf"""["'`]({alternatives})["'`]""")


def test_declared_keys_are_not_literals() -> None:
    names = _declared()
    assert names, "no committed profile declares anything"
    literal = _literal(names)
    hits: list[str] = []
    for path in _files():
        rel = path.relative_to(ROOT).as_posix()
        skip = [_definition(c) for c in BEAUTY_EXCEPTIONS.get(rel, ())]
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(p.match(line) for p in skip):
                continue
            hits += [f"{rel}:{number}: {m.group(1)!r}" for m in literal.finditer(line)]
    assert hits == [], "declared attribute names belong in meta.attributeSet, not code"


@pytest.mark.parametrize(
    ("rel", "constant"),
    [(rel, c) for rel, constants in BEAUTY_EXCEPTIONS.items() for c in constants],
)
def test_every_exception_still_has_its_constant(rel: str, constant: str) -> None:
    lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
    assert any(_definition(constant).match(line) for line in lines), (
        f"{rel} no longer defines {constant}: delete its BEAUTY_EXCEPTIONS entry"
    )


def test_the_guard_finds_a_literal(tmp_path: Path) -> None:
    sample = tmp_path / "x.ts"
    sample.write_text('const k = "shadeFamilies";\nconst FAMS = ["finish"];\n', encoding="utf-8")
    literal = _literal(_declared())
    lines = sample.read_text(encoding="utf-8").splitlines()
    assert literal.search(lines[0])
    assert _definition("FAMS").match(lines[1])
