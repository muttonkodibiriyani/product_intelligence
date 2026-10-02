"""Run the TypeScript assistant's gate (typecheck, lint, format, tests + coverage, build).

Install runs with --ignore-scripts (for the app and the separate evals package), so no
dependency lifecycle script executes in CI, and `npm audit` fails the gate on any
moderate-or-worse advisory (.npmrc audit-level).

This lets the existing Python CI job enforce the TS checks without a workflow change. It fails,
never skips, when Node.js/npm is missing, so the gate cannot pass silently.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
MIN_NODE_MAJOR = 20


EVALS = APP / "evals"
# promptfoo needs Node >= 22.22; evals never call a model here (validate only).
EVALS_ENV = {
    "PROMPTFOO_DISABLE_TELEMETRY": "1",
    "PROMPTFOO_DISABLE_UPDATE": "1",
    "PROMPTFOO_DISABLE_SHARING": "1",
}


def _run(
    npm: str, *args: str, cwd: Path = APP, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
        [npm, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
        env=None if env is None else {**os.environ, **env},
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
    install = _run(npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund")
    assert install.returncode == 0, install.stdout[-4000:] + install.stderr[-4000:]
    audit = _run(npm, "audit", "--audit-level=moderate")
    assert audit.returncode == 0, audit.stdout[-8000:] + audit.stderr[-4000:]
    check = _run(npm, "run", "check")
    assert check.returncode == 0, check.stdout[-8000:] + check.stderr[-4000:]
    # The Functions deploy ships lib/ (codebase "assistant", firebase.json); the build must pass.
    build = _run(npm, "run", "build")
    assert build.returncode == 0, build.stdout[-8000:] + build.stderr[-4000:]


def test_evals_package() -> None:
    """The promptfoo package installs without scripts, audits clean and its config is valid."""
    npm = shutil.which("npm")
    assert npm is not None, "npm is required for apps/assistant checks"
    install = _run(npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund", cwd=EVALS)
    assert install.returncode == 0, install.stdout[-4000:] + install.stderr[-4000:]
    audit = _run(npm, "audit", "--audit-level=moderate", cwd=EVALS)
    assert audit.returncode == 0, audit.stdout[-8000:] + audit.stderr[-4000:]
    validate = _run(npm, "run", "validate", cwd=EVALS, env=EVALS_ENV)
    assert validate.returncode == 0, validate.stdout[-8000:] + validate.stderr[-4000:]


def test_evals_lockfile_has_no_node_forge() -> None:
    """jks-js is stubbed in-repo: node-forge <= 1.4.0 (GHSA-86w9-cpqp-85rv) has no fix yet.

    Remove the stub and this test when node-forge ships a release > 1.4.0 (decision log).
    """
    lock = json.loads((EVALS / "package-lock.json").read_text(encoding="utf-8"))
    paths = lock["packages"]
    assert not [p for p in paths if p.rsplit("node_modules/", 1)[-1] == "node-forge"]
    stub = paths["node_modules/jks-js"]
    assert stub == {"resolved": "stubs/jks-js", "link": True}, stub
    assert (
        json.loads((EVALS / "package.json").read_text(encoding="utf-8"))["overrides"]["jks-js"]
        == "$jks-js"
    )


def test_jks_js_stub_refuses_every_use() -> None:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for apps/assistant checks"
    probe = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
        [
            node,
            "-e",
            "for (const f of Object.values(require('./stubs/jks-js'))) "
            "{ try { f(); process.exit(1); } catch (e) "
            "{ if (e.message !== 'JKS keystores not supported') process.exit(2); } }",
        ],
        cwd=EVALS,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert probe.returncode == 0, probe.stdout + probe.stderr
