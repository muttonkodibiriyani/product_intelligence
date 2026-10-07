"""The ADR-0007 literal guard, extended to attribute keys and enum values (ADR-0008 §3).

A key or enum value declared by any committed profile must not appear as a quoted literal in
``pi_api``, ``pi_metrics`` or ``apps/web`` outside fixtures and contracts: those read the
declaration from the snapshot's ``meta.attributeSet``. The only exceptions are the two beauty
constants the dashboard still hard-codes, until step 6 replaces them with ``attributeSet`` and
``meta.taxonomy`` data and deletes these entries, and the product-name stop words below, which
are words of retailer names that coincide with declared enum values.
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
#: Name-token exceptions, file -> constants whose whole definition is not scanned. These are words
#: stripped from retailer product names ("for women"), never attribute reads, so they stay when
#: step 6 lands. ``beauty@2``'s ``gender`` values ``men`` and ``women`` collide with them.
NAME_TOKEN_EXCEPTIONS = {"packages/pi_metrics/src/pi_metrics/findings.py": ("NAME_STOP",)}
EXCEPTIONS = {
    rel: BEAUTY_EXCEPTIONS.get(rel, ()) + NAME_TOKEN_EXCEPTIONS.get(rel, ())
    for rel in BEAUTY_EXCEPTIONS.keys() | NAME_TOKEN_EXCEPTIONS.keys()
}


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
    return re.compile(rf"^\s*(export\s+)?((const|let|var)\s+)?{constant}\s*[:=]")


def _skipped(lines: list[str], constants: tuple[str, ...]) -> set[int]:
    """Line indexes of each constant's definition, through the line its brackets close on."""
    skipped: set[int] = set()
    for constant in constants:
        start = next((i for i, line in enumerate(lines) if _definition(constant).match(line)), None)
        depth, index = 0, start
        while index is not None and index < len(lines):
            skipped.add(index)
            depth += sum(lines[index].count(c) for c in "([{") - sum(
                lines[index].count(c) for c in ")]}"
            )
            index = index + 1 if depth > 0 else None
    return skipped


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
        lines = path.read_text(encoding="utf-8").splitlines()
        skipped = _skipped(lines, EXCEPTIONS.get(rel, ()))
        for number, line in enumerate(lines, 1):
            if number - 1 in skipped:
                continue
            hits += [f"{rel}:{number}: {m.group(1)!r}" for m in literal.finditer(line)]
    assert hits == [], "declared attribute names belong in meta.attributeSet, not code"


@pytest.mark.parametrize(
    ("rel", "constant"),
    [(rel, c) for rel, constants in EXCEPTIONS.items() for c in constants],
)
def test_every_exception_still_has_its_constant(rel: str, constant: str) -> None:
    lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
    assert any(_definition(constant).match(line) for line in lines), (
        f"{rel} no longer defines {constant}: delete its exception entry"
    )


def test_the_guard_finds_a_literal(tmp_path: Path) -> None:
    sample = tmp_path / "x.ts"
    sample.write_text('const k = "shadeFamilies";\nconst FAMS = ["finish"];\n', encoding="utf-8")
    literal = _literal(_declared())
    lines = sample.read_text(encoding="utf-8").splitlines()
    assert literal.search(lines[0])
    assert _definition("FAMS").match(lines[1])


def test_an_exception_skips_its_whole_definition_only() -> None:
    lines = ["NAME_STOP = frozenset(", "    [", '        "women",', "    ]", ")", 'x = "women"']
    assert _skipped(lines, ("NAME_STOP",)) == {0, 1, 2, 3, 4}
    assert _skipped(["const FAMS = ['finish'];", "f('finish')"], ("FAMS",)) == {0}
