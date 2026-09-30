"""Guards that keep connectors free of network I/O (the fetch layer owns every request).

* ``network_imports``: static check. Walks a connector package's source and lists every import
  of a network, browser or fingerprinting library, or of pi_fetch's transports and fetcher, and
  every use of a fetch-capable name however it is reached (``from pi_fetch import Fetcher``,
  ``pi_fetch.Fetcher``, ``getattr(pi_fetch, "Fetcher")``).
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


#: pi_fetch names that perform network I/O. The fetcher is not re-exported from ``pi_fetch``;
#: these are flagged in any form, so a re-export or alias cannot reopen the path.
BANNED_NAMES = frozenset({"BrowserTransport", "Fetcher", "HttpTransport", "default_transport"})


class NetworkImport(PiModel):
    """One banned import found in a connector source file."""

    path: str
    line: int
    module: str


def _banned(module: str) -> bool:
    return any(module == b or module.startswith(f"{b}.") for b in BANNED_MODULES)


def _string_arg(node: ast.Call, index: int) -> str | None:
    if len(node.args) > index:
        arg = node.args[index]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _violations(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """(line, what) for every banned import or banned-name use in ``tree``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _banned(alias.name):
                    yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if _banned(node.module):
                yield node.lineno, node.module
            for alias in node.names:
                full = f"{node.module}.{alias.name}"
                if _banned(full) or alias.name in BANNED_NAMES:
                    yield node.lineno, full
        elif isinstance(node, ast.Attribute) and node.attr in BANNED_NAMES:
            yield node.lineno, f"<attribute>.{node.attr}"
        elif isinstance(node, ast.Call):
            name = _call_name(node)
            module = _string_arg(node, 0) if name in {"__import__", "import_module"} else None
            if module is not None and _banned(module):
                yield node.lineno, module
            attr = _string_arg(node, 1) if name == "getattr" else None
            if attr in BANNED_NAMES:
                yield node.lineno, f"getattr(..., {attr!r})"


def network_imports(root: Path) -> list[NetworkImport]:
    """Every banned import under ``root`` (``*.py``), sorted by path and line."""
    found: set[NetworkImport] = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, module in _violations(tree):
            found.add(NetworkImport(path=str(path), line=line, module=module))
    return sorted(found, key=lambda f: (f.path, f.line, f.module))


class NetworkForbiddenError(RuntimeError):
    """Connector code tried to open a connection or resolve a name."""


@contextmanager
def forbid_network() -> Iterator[None]:
    """Make every socket connect and DNS lookup in this process raise while the block runs."""

    def refuse(*_: Any, **__: Any) -> Any:
        msg = "network I/O is forbidden here: connectors never fetch (the runner does)"
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
