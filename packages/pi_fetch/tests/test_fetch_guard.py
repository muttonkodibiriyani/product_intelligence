"""a4: connectors do no network I/O, statically (imports) and at runtime (sockets)."""

import socket
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

import pi_fetch
from fetch_helpers import make_ctx
from pi_core import LadderRung
from pi_fetch.guard import NetworkForbiddenError, forbid_network, network_imports
from sample_connector import SampleConnector
from test_fetch_connector import fetched

REPO = Path(__file__).resolve().parents[3]
CONNECTOR_SOURCES = sorted(REPO.glob("packages/pi_connector_*/src"))
FORBIDDEN_DISTRIBUTIONS = ("curl_cffi", "curl-cffi", "scrapling", "camoufox", "patchright")


@pytest.mark.parametrize("src", CONNECTOR_SOURCES, ids=lambda p: p.parent.name)
def test_connector_packages_import_no_network_library(src: Path) -> None:
    assert network_imports(src) == []


def test_sample_connector_imports_no_network_library(tmp_path: Path) -> None:
    source = Path(__file__).parent / "sample_connector.py"
    (tmp_path / "sample_connector.py").write_text(source.read_text())
    assert network_imports(tmp_path) == []


def test_guard_finds_every_import_form(tmp_path: Path) -> None:
    pkg = tmp_path / "pi_connector_bad" / "src"
    pkg.mkdir(parents=True)
    (pkg / "a.py").write_text(
        "import httpx\n"
        "import urllib.request as ur\n"
        "from playwright.sync_api import sync_playwright\n"
        "from pi_fetch.transports.http import HttpTransport\n"
        "from pi_fetch import ladder\n"
        "import importlib\n"
        "m = importlib.import_module('requests')\n"
        "s = __import__('socket')\n"
        "import json\n"
        "from pi_fetch import FetchRequest\n"
        "from . import sibling\n"
    )
    found = [(f.line, f.module) for f in network_imports(pkg)]
    assert found == [
        (1, "httpx"),
        (2, "urllib.request"),
        (3, "playwright.sync_api"),
        (3, "playwright.sync_api.sync_playwright"),
        (4, "pi_fetch.transports.http"),
        (4, "pi_fetch.transports.http.HttpTransport"),
        (5, "pi_fetch.ladder"),
        (7, "requests"),
        (8, "socket"),
    ]


def test_guard_finds_fetch_entry_points_however_they_are_reached(tmp_path: Path) -> None:
    pkg = tmp_path / "pi_connector_sneaky" / "src"
    pkg.mkdir(parents=True)
    (pkg / "a.py").write_text(
        "import pi_fetch\n"
        "from pi_fetch import Fetcher\n"
        "from pi_fetch import default_transport as dt\n"
        "f = pi_fetch.Fetcher\n"
        "g = getattr(pi_fetch, 'HttpTransport')\n"
        "h = pi_fetch.ladder.BrowserTransport\n"
    )
    assert [f.line for f in network_imports(pkg)] == [2, 3, 4, 5, 6]


def test_package_root_does_not_export_the_fetcher() -> None:
    for name in ("Fetcher", "HttpTransport", "BrowserTransport", "default_transport"):
        assert not hasattr(pi_fetch, name), name
        assert name not in pi_fetch.__all__


def test_forbid_network_blocks_sockets_and_dns() -> None:
    with forbid_network():
        with pytest.raises(NetworkForbiddenError):
            socket.create_connection(("127.0.0.1", 9))
        with pytest.raises(NetworkForbiddenError):
            socket.getaddrinfo("example.com", 443)
        with socket.socket() as sock, pytest.raises(NetworkForbiddenError):
            sock.connect(("127.0.0.1", 9))
    # Restored afterwards.
    assert socket.getaddrinfo("127.0.0.1", 80)


def test_connector_runs_fully_offline() -> None:
    ctx = make_ctx(LadderRung.SITE_DATA)
    connector = SampleConnector()
    with forbid_network():
        items = list(connector.discover(ctx))
        requests = connector.requests_for(items[0], ctx)
        output = connector.parse(fetched(), ctx)
    assert requests
    assert output.offers


def test_no_impersonation_or_stealth_dependency() -> None:
    pyproject = tomllib.loads((REPO / "packages/pi_fetch/pyproject.toml").read_text())
    deps = " ".join(pyproject["project"]["dependencies"]).lower()
    lock = (REPO / "uv.lock").read_text().lower()
    for name in FORBIDDEN_DISTRIBUTIONS:
        assert name not in deps
        assert f'name = "{name}"' not in lock
        with pytest.raises(metadata.PackageNotFoundError):
            metadata.distribution(name)


def test_http_transport_disables_http2() -> None:
    source = (REPO / "packages/pi_fetch/src/pi_fetch/transports/http.py").read_text()
    assert "http2=False" in source
