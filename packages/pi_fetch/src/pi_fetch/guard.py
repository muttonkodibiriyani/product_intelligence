"""Guards that keep connectors free of network I/O (the fetch layer owns every request).

* ``network_imports``: static check. Walks a connector package's source and lists every import
  of a network, browser or fingerprinting library, or of pi_fetch's transports and fetcher.
  ``tests/test_guard.py`` runs it over every ``packages/pi_connector_*/src``.
* ``forbid_network``: runtime check. Inside the block any socket connect or DNS lookup raises
  ``NetworkForbiddenError``; wrap ``parse``/``discover``/``requests_for`` tests in it.
"""

import ast
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pi_core import PiModel

#: Top-level modules a connector may not import (``pi_fetch.<x>`` entries match submodules).
BANNED_MODULES = frozenset(
    {
        "aiohttp",
        "camoufox",
        "curl_cffi",
        "ftplib",
        "http.client",
        "httpcore",
        "httpx",
        "patchright",
        "pi_fetch.ladder",
        "pi_fetch.transports",
        "playwright",
        "pycurl",
        "requests",
        "scrapling",
        "selenium",
        "socket",
        "ssl",
        "tls_client",
        "undetected_chromedriver",
        "urllib.request",
        "urllib3",
        "websocket",
        "websockets",
    }
)


class NetworkImport(PiModel):
    """One banned import found in a connector source file."""

    path: str
    line: int
    module: str


def _banned(module: str) -> bool:
    return any(module == b or module.startswith(f"{b}.") for b in BANNED_MODULES)


def _imported_modules(tree: ast.AST) -> Iterator[tuple[int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.lineno, node.module
            for alias in node.names:
                yield node.lineno, f"{node.module}.{alias.name}"
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name | ast.Attribute)
            and (node.func.id if isinstance(node.func, ast.Name) else node.func.attr)
            in {"__import__", "import_module"}
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            yield node.lineno, node.args[0].value


def network_imports(root: Path) -> list[NetworkImport]:
    """Every banned import under ``root`` (``*.py``), sorted by path and line."""
    found: set[NetworkImport] = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, module in _imported_modules(tree):
            if _banned(module):
                found.add(NetworkImport(path=str(path), line=line, module=module))
    return sorted(found, key=lambda f: (f.path, f.line, f.module))


class NetworkForbiddenError(RuntimeError):
    """Connector code tried to open a connection or resolve a name."""


@contextmanager
def forbid_network() -> Iterator[None]:
    """Make every socket connect and DNS lookup in this process raise while the block runs."""

    def refuse(*_: Any, **__: Any) -> Any:
        msg = "network I/O is forbidden here: connectors never fetch (use pi_fetch.Fetcher)"
        raise NetworkForbiddenError(msg)

    patched = {
        (socket.socket, "connect"): socket.socket.connect,
        (socket.socket, "connect_ex"): socket.socket.connect_ex,
        (socket, "create_connection"): socket.create_connection,
        (socket, "getaddrinfo"): socket.getaddrinfo,
    }
    for (owner, name), _original in patched.items():
        setattr(owner, name, refuse)
    try:
        yield
    finally:
        for (owner, name), original in patched.items():
            setattr(owner, name, original)
