"""Run the TypeScript assistant's own gate (typecheck, lint, format, tests + coverage) from pytest.

This lets the existing Python CI job enforce the TS checks without a workflow change. It fails,
never skips, when Node.js/npm is missing, so the gate cannot pass silently.
"""

import shutil
import subprocess
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
MIN_NODE_MAJOR = 20


def _run(npm: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
        [npm, *args], cwd=APP, capture_output=True, text=True, timeout=600, check=False
    )


def test_node_available() -> None:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for apps/assistant checks"
    version = subprocess.run(  # noqa: S603 - fixed argv
        [node, "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert int(version.lstrip("v").split(".")[0]) >= MIN_NODE_MAJOR, version


def test_assistant_npm_check() -> None:
    npm = shutil.which("npm")
    assert npm is not None, "npm is required for apps/assistant checks"
    install = _run(npm, "ci", "--no-audit", "--no-fund")
    assert install.returncode == 0, install.stdout[-4000:] + install.stderr[-4000:]
    check = _run(npm, "run", "check")
    assert check.returncode == 0, check.stdout[-8000:] + check.stderr[-4000:]
