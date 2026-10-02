"""Owner-approved proxy egress for the hosts that block every direct route (task 01a0fc6d).

Rules, all enforced here or in :mod:`page_capture.run`:

- Only the hosts named in ``PROXY_HOSTS`` go through the proxy; every other host, and **every
  picture**, is fetched directly.
- The credential is read from Secret Manager at run time (``PROXY_SECRET`` is the version
  resource name). It is never logged, never written to the bucket and never put in a manifest;
  the manifest records the resource name only.
- Bytes on the wire are metered per response and the run stops the proxied hosts at
  ``PROXY_BYTE_CAP`` (owner cap 1.8 GB by default). The meter counts what the proxy would bill:
  compressed response bytes plus an allowance for the request.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_BYTE_CAP = 1_800_000_000
REQUEST_ALLOWANCE = 1_000  # bytes charged per request for headers, TLS and the request line
SECRET_FIELDS = ("host", "port", "username", "password")


@dataclass(frozen=True)
class ProxyEndpoint:
    host: str
    port: int
    username: str
    password: str
    provider: str = ""

    @property
    def url(self) -> str:
        return f"http://{self.username}:{self.password}@{self.host}:{self.port}"

    def __repr__(self) -> str:  # never leak the credential through logging or tracebacks
        return f"ProxyEndpoint(host={self.host!r}, port={self.port}, provider={self.provider!r})"


def parse_endpoint(payload: str) -> ProxyEndpoint:
    """The proxy endpoint from the secret's JSON payload; every field must be present."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("proxy secret is not JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("proxy secret must be a JSON object")
    missing = [k for k in SECRET_FIELDS if not str(data.get(k, "")).strip()]
    if missing:
        raise ValueError(f"proxy secret is missing {', '.join(missing)}")
    return ProxyEndpoint(
        host=str(data["host"]).strip(),
        port=int(data["port"]),
        username=str(data["username"]),
        password=str(data["password"]),
        provider=str(data.get("provider", "")),
    )


def access_secret(resource: str, token: str, client: httpx.Client | None = None) -> str:
    """The decoded payload of a Secret Manager version (``projects/*/secrets/*/versions/*``)."""
    c = client or httpx.Client(timeout=20.0)
    r = c.get(
        f"https://secretmanager.googleapis.com/v1/{resource}:access",
        headers={"Authorization": f"Bearer {token}"},
    )
    if r.status_code != 200:
        raise RuntimeError(f"secret access failed with http {r.status_code}")
    body: dict[str, Any] = r.json()
    return base64.b64decode(body["payload"]["data"]).decode("utf-8")


def runtime_token() -> str:
    """An access token from the ambient Google credentials (Cloud Run runner or key file)."""
    import google.auth  # noqa: PLC0415 - only the real job needs it; tests never do
    import google.auth.transport.requests  # noqa: PLC0415

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(google.auth.transport.requests.Request())
    token = credentials.token
    if not isinstance(token, str) or not token:
        raise RuntimeError("no access token from the runtime credentials")
    return token


def endpoint_from_secret(resource: str) -> ProxyEndpoint:
    return parse_endpoint(access_secret(resource, runtime_token()))


def proxy_client(endpoint: ProxyEndpoint) -> httpx.Client:
    return httpx.Client(proxy=endpoint.url, follow_redirects=True, timeout=45.0)


@dataclass
class Meter:
    """Bytes charged against the owner's cap."""

    cap: int = DEFAULT_BYTE_CAP
    used: int = 0

    def charge(self, response_bytes: int) -> None:
        self.used += response_bytes + REQUEST_ALLOWANCE

    @property
    def exhausted(self) -> bool:
        return self.used >= self.cap


def wire_bytes(response: Any) -> int:
    """Compressed bytes the response moved, falling back to the body length."""
    n = getattr(response, "num_bytes_downloaded", None)
    if isinstance(n, int) and n > 0:
        return n
    return len(response.content)
