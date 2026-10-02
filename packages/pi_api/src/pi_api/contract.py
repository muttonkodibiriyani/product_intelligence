"""The committed API contract: ``docs/contracts/pi-api.openapi.json`` (drift-tested).

The running service serves no OpenAPI route; clients (and the FE's generated types) read this file.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from pi_api.app import build_api
from pi_api.source import LocalStore, SnapshotSource
from pi_api.wire import API_VERSION

SECURITY_SCHEME = {
    "type": "http",
    "scheme": "bearer",
    "bearerFormat": "Firebase ID token",
    "description": (
        "Every route, including unknown paths, needs a Firebase ID token carrying a "
        "`role` claim (viewer or admin). Cookies are ignored. Every response is "
        "`Cache-Control: private, no-store`."
    ),
}


def openapi() -> dict[str, Any]:
    spec = build_api(SnapshotSource(LocalStore("."), ())).openapi()
    spec["info"]["version"] = API_VERSION
    spec.setdefault("components", {})["securitySchemes"] = {"firebase": SECURITY_SCHEME}
    spec["security"] = [{"firebase": []}]
    return spec


def openapi_text() -> str:
    return json.dumps(openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pi-api", description="pi_api contract tools")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("openapi", help="print the OpenAPI document")
    parser.parse_args(argv)
    sys.stdout.write(openapi_text())
    return 0
