"""Assert a Cloud Run service, revision or job carries the env it is meant to.

``gcloud run services|revisions|jobs describe --format=json`` is read from a file (``-`` for
stdin). The env list sits at a different depth for each kind (Cloud Run Admin API v1):

- Service: ``spec.template.spec.containers[0].env``
- Revision: ``spec.containers[0].env``
- Job: ``spec.template.spec.template.spec.containers[0].env``

The roll checklist's env diff (pi-api-deploy §6) reads the same list with errors silenced, so a
describe that failed, or a shape it did not expect, reads as "no live env" and its "would delete"
check passes on nothing. This gate makes that loud: it prints the env NAMES (never values) and
exits 1 when the list is empty or a ``--require`` name is missing, and 2 when the input is not a
describe body of a known kind.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

OK, FAIL, MALFORMED = 0, 1, 2

# Keys from the resource root down to its first container's ``env``.
CONTAINER_PATHS: dict[str, tuple[str, ...]] = {
    "Service": ("spec", "template", "spec", "containers"),
    "Revision": ("spec", "containers"),
    "Job": ("spec", "template", "spec", "template", "spec", "containers"),
}


class MalformedError(Exception):
    """The input is not a Cloud Run describe body this gate knows."""


def env_names(body: Any) -> tuple[str, str, list[str]]:
    """``(kind, name, env names in order)``; raises MalformedError on an unknown shape."""
    if not isinstance(body, dict):
        raise MalformedError("describe output is not a JSON object")
    kind = body.get("kind")
    if kind not in CONTAINER_PATHS:
        raise MalformedError(f"kind {kind!r} is not one of {', '.join(CONTAINER_PATHS)}")
    meta = body.get("metadata")
    name = str(meta.get("name", "?")) if isinstance(meta, dict) else "?"
    node: Any = body
    for key in CONTAINER_PATHS[kind]:
        if not isinstance(node, dict) or key not in node:
            raise MalformedError(f"{kind} {name}: no {'.'.join(CONTAINER_PATHS[kind])}")
        node = node[key]
    if not isinstance(node, list) or not node or not isinstance(node[0], dict):
        raise MalformedError(f"{kind} {name}: containers is empty or not a list")
    env = node[0].get("env", [])
    if not isinstance(env, list) or not all(isinstance(e, dict) and "name" in e for e in env):
        raise MalformedError(f"{kind} {name}: containers[0].env is not a list of named entries")
    return kind, name, [str(e["name"]) for e in env]


def check(body: Any, required: Sequence[str]) -> tuple[int, list[str]]:
    """Exit code and the lines to print."""
    try:
        kind, name, names = env_names(body)
    except MalformedError as exc:
        return MALFORMED, [f"MALFORMED: {exc}"]
    lines = [f"{kind} {name}: {len(names)} env var(s)", *(f"  {n}" for n in names)]
    problems = []
    if not names:
        problems.append("env is empty")
    missing = [r for r in required if r not in names]
    if missing:
        problems.append(f"missing required: {', '.join(missing)}")
    if problems:
        return FAIL, [*lines, *(f"FAIL: {p}" for p in problems)]
    return OK, [*lines, "ENV PRESENT"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("describe", help="describe --format=json output, or - for stdin")
    parser.add_argument(
        "--require", action="append", default=[], metavar="NAME", help="env name that must exist"
    )
    args = parser.parse_args(argv)
    try:
        if args.describe == "-":
            raw = sys.stdin.read()
        else:
            with open(args.describe, encoding="utf-8") as f:
                raw = f.read()
        body = json.loads(raw)
    except (OSError, ValueError) as exc:
        print(f"MALFORMED: cannot read describe output ({exc.__class__.__name__})")
        return MALFORMED
    code, lines = check(body, args.require)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
