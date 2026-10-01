"""Shared pieces for the pi_api tests: an in-test signing key, tokens, a served dataset.

Nothing here touches the network: certificates come from ``FakeCerts`` and the dataset from a
``LocalStore`` in a pytest tmp dir.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import anyio
import httpx
import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from starlette.types import ASGIApp

from metrics_fixture import metrics_dataset, rebuild
from pi_api.app import TokenBuckets, create_app
from pi_api.auth import TokenVerifier
from pi_api.source import LocalStore, SnapshotSource
from pi_dataset import Dataset, DatasetV3, dump_dataset

PROJECT = "pi-test-project"
KID = "test-kid"
DATASET_PATH = "datasets/uae/latest.json"
NOW = time.time()
#: The API's wall clock in tests (``/summary`` freshness), fixed so goldens are stable.
CLOCK = datetime(2026, 10, 2, 6, 0, tzinfo=UTC)


def _key_and_cert() -> tuple[rsa.RSAPrivateKey, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "pi-api-test")])
    start = datetime.now(UTC) - timedelta(days=1)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(start)
        .not_valid_after(start + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return key, cert.public_bytes(serialization.Encoding.PEM).decode()


KEY, CERT = _key_and_cert()
OTHER_KEY, _ = _key_and_cert()


class FakeCerts:
    def __init__(self, certs: Mapping[str, str] | None = None, *, stale: bool = False) -> None:
        self.certs = dict(certs if certs is not None else {KID: CERT})
        self.is_stale = stale

    def certificates(self) -> Mapping[str, str]:
        return self.certs

    def stale(self) -> bool:
        return self.is_stale


def claims(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "iss": f"https://securetoken.google.com/{PROJECT}",
        "aud": PROJECT,
        "sub": "user-1",
        "iat": int(NOW) - 10,
        "exp": int(NOW) + 3600,
        "auth_time": int(NOW) - 20,
        "role": "viewer",
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def token(key: rsa.RSAPrivateKey = KEY, kid: str = KID, **overrides: Any) -> str:
    return jwt.encode(claims(**overrides), key, algorithm="RS256", headers={"kid": kid})


def bearer(**overrides: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(**overrides)}"}


def served_dataset() -> Dataset:
    """The pi_metrics fixture, marked real so the API's default refusal of test data holds."""
    return rebuild(metrics_dataset(), test=False)


def write(root: Path, dataset: Dataset | DatasetV3, path: str = DATASET_PATH) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(dump_dataset(dataset))


class Client:
    """Synchronous calls into the ASGI app in-process; no sockets, no network."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        async def call() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
                return await client.request(method, path, **kwargs)

        return anyio.run(call)

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)


def make_client(
    root: Path,
    *,
    rate: float = 1000,
    burst: int = 1000,
    certs: FakeCerts | None = None,
    paths: tuple[str, ...] = (DATASET_PATH,),
    load: bool = True,
    evidence_hosts: Mapping[str, frozenset[str]] | None = None,
    image_hosts: Mapping[str, frozenset[str]] | None = None,
    clock: Callable[[], datetime] = lambda: CLOCK,
) -> tuple[Client, SnapshotSource]:
    source = SnapshotSource(LocalStore(root), paths, refresh_seconds=3600)
    if load:
        source.load_all()
    verifier = TokenVerifier(PROJECT, certs or FakeCerts(), now=lambda: NOW)
    app = create_app(
        source,
        verifier,
        TokenBuckets(rate, burst),
        evidence_hosts=evidence_hosts,
        image_hosts=image_hosts,
        clock=clock,
    )
    return Client(app), source
