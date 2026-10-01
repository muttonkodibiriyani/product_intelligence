"""All firebase-tools references in CI, the Makefile and deploy docs pin one exact version."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
REF = re.compile(r"firebase-tools@(\$\(FIREBASE_TOOLS_VERSION\)|[^\s`)]+)")
FILES = (
    ".github/workflows/ci.yml",
    "Makefile",
    "infra/DEMO.md",
    "docs/runbooks/pi-api-deploy.md",
)


def test_firebase_tools_is_pinned_to_one_exact_version() -> None:
    makefile = (ROOT / "Makefile").read_text()
    match = re.search(r"^FIREBASE_TOOLS_VERSION \?= (\d+\.\d+\.\d+)$", makefile, re.M)
    assert match, "Makefile must set FIREBASE_TOOLS_VERSION to an exact x.y.z"
    pinned = match.group(1)
    seen: dict[str, list[str]] = {}
    for rel in FILES:
        for ref in REF.findall((ROOT / rel).read_text()):
            seen.setdefault(ref, []).append(rel)
    assert set(seen) <= {pinned, "$(FIREBASE_TOOLS_VERSION)"}, seen
    assert pinned in seen
