"""All firebase-tools invocations in tracked files pin the one exact version set in the Makefile."""

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
PINNED = re.compile(r"firebase-tools@(\$\(FIREBASE_TOOLS_VERSION\)|[^\s`)\"']+)")
# A global `firebase` binary runs whatever version happens to be installed.
BARE = re.compile(r"(?<![\w@/.-])firebase(?:\s|\\)+(deploy|emulators:\w+)\b")
SKIP = re.compile(r"(^|/)(package-lock\.json|pnpm-lock\.yaml|uv\.lock)$")
# Files allowed to keep a bare `firebase …` mention, and why. Pinned refs are checked everywhere.
EXCLUDED = {
    "apps/assistant/.env.example": "a comment pointing at the design §9.4 command",
}


def _pinned_version() -> str:
    makefile = (ROOT / "Makefile").read_text()
    match = re.search(r"^FIREBASE_TOOLS_VERSION \?= (\d+\.\d+\.\d+)$", makefile, re.M)
    assert match, "Makefile must set FIREBASE_TOOLS_VERSION to an exact x.y.z"
    return match.group(1)


def _tracked_texts() -> dict[str, str]:
    git = shutil.which("git")
    assert git, "git is needed to list tracked files"
    out = subprocess.run(  # noqa: S603 - fixed argv, no user input
        [git, "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    texts = {}
    for rel in out.stdout.splitlines():
        path = ROOT / rel
        if SKIP.search(rel) or not path.is_file():
            continue
        try:
            texts[rel] = path.read_text()
        except UnicodeDecodeError:
            continue
    return texts


def test_every_firebase_tools_reference_uses_the_makefile_pin() -> None:
    pinned = _pinned_version()
    seen: dict[str, list[str]] = {}
    for rel, text in _tracked_texts().items():
        if rel == "infra/tests/test_firebase_tools_pin.py":
            continue
        for ref in PINNED.findall(text):
            seen.setdefault(ref, []).append(rel)
    assert set(seen) <= {pinned, "$(FIREBASE_TOOLS_VERSION)"}, seen
    assert ".github/workflows/ci.yml" in seen.get(pinned, []), "CI must use the pinned version"


def test_no_bare_firebase_cli_invocations() -> None:
    bare = {
        rel: [m.group(0) for m in BARE.finditer(text)]
        for rel, text in _tracked_texts().items()
        if rel not in EXCLUDED and BARE.search(text)
    }
    assert not bare, f"use npx -y firebase-tools@{_pinned_version()} instead: {bare}"


def test_exclusions_are_current() -> None:
    texts = _tracked_texts()
    stale = [rel for rel in EXCLUDED if rel not in texts or not BARE.search(texts[rel])]
    assert not stale, f"remove EXCLUDED entries that no longer need it: {stale}"
