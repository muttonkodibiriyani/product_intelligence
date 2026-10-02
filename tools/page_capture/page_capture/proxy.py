"""Owner-approved proxy egress for the hosts that block every direct route (task 01a0fc6d).

Rules, all enforced here or in :mod:`page_capture.run`:

- Only the hosts named in ``PROXY_HOSTS`` go through the proxy; every other host, and **every
  picture**, is fetched directly.
- The credential is read from Secret Manager at run time (``PROXY_SECRET`` is the version
  resource name). It is never logged, never written to the bucket and never put in a manifest;
  the manifest records the resource name only.
- Only the shop hosts the owner put in scope for task 01a0fc6d (ADR-0006 Amendment 4) may be
  named; any other host is refused at configuration time (``ALLOWED_HOSTS``).
- Bytes on the wire are metered per response against **one shared ledger** in the bucket
  (``PROXY_LEDGER``), which holds the owner's cap and what every run so far, including the
  ulta.ae runs, has used. The ledger is updated with a compare-and-swap after every proxied
  response and re-read before every proxied request, so a run stops when the shared balance is
  gone even if another run spent it. A run may lower its own share
  with ``PROXY_BYTE_CAP``; it can never raise the ledger's cap. No ledger, an exhausted ledger or
  a sharded job (more than one Cloud Run task) means no proxy at all.
- The meter counts what the proxy would bill: compressed response bytes plus an allowance for
  the request.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

DEFAULT_BYTE_CAP = 1_800_000_000
REQUEST_ALLOWANCE = 1_000  # bytes charged per request for headers, TLS and the request line
SECRET_FIELDS = ("host", "port", "username", "password")
LEDGER_FIELDS = ("cap_bytes", "used_bytes")
SAVE_ATTEMPTS = 5
# Page hosts of the shops in scope for task 01a0fc6d (ADR-0006 Amendment 4). ulta.ae is not
# here: its proxy use goes through pi_fetch under Amendment 2, and this job never touches it.
ALLOWED_HOSTS = frozenset(
    {
        "www.faces.ae",
        "www.nysaa.com",
        "www.sephora.sa",
        "www.noon.com",
        "www.amazon.ae",
        # KSA fashion matrix
        "aldo.com.sa",
        "en.mamasandpapas.com.sa",
        "ksa.milanomena.com",
        "sa.cos.com",
        "sa.nayomi.com",
        "www.americaneagle.com.sa",
        "www.centrepointstores.com",
        "www.charleskeith.sa",
        "www.footlocker.com.sa",
        "www.marksandspencer.sa",
        "www.maxfashion.com",
        "www.mothercare.com.sa",
        "www.muji.com.sa",
        "www.nike.sa",
        "www.stevemadden.sa",
        "www.victoriassecret.com.sa",
        "www.zara.com",
    }
)


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
    return httpx.Client(proxy=endpoint.url, follow_redirects=False, timeout=45.0)


class LedgerStore(Protocol):
    """Where the shared ledger lives: a GCS object (compare-and-swap on generation) or a file."""

    def load(self) -> tuple[bytes, object] | None:
        """The ledger bytes and an opaque version token; None when the object does not exist."""
        ...

    def save(self, data: bytes, token: object) -> bool:
        """Write only if the stored version still matches ``token``; False on a lost race."""
        ...


class LedgerError(RuntimeError):
    pass


@dataclass
class Meter:
    """This run's share of the proxy balance.

    ``cap`` is the smaller of the run's own ``PROXY_BYTE_CAP`` and what the shared ledger has
    left; ``used`` is this run's spend. With a ledger every charge is written through.
    """

    cap: int = DEFAULT_BYTE_CAP
    used: int = 0
    ledger: Ledger | None = None
    #: Set when the ledger could not be re-read; the meter then reports exhausted (fail closed).
    ledger_fault: str | None = None

    def charge(self, response_bytes: int) -> None:
        n = response_bytes + REQUEST_ALLOWANCE
        self.used += n
        if self.ledger is not None:
            self.ledger.charge(n)

    @property
    def exhausted(self) -> bool:
        """True once this run's share is spent *or* the shared balance is, whoever spent it.

        The ledger is re-read on every check so a concurrent run's spend counts here too; a
        run's cap was fixed at start and cannot see the other run otherwise.
        """
        if self.used >= self.cap:
            return True
        if self.ledger is None:
            return False
        try:
            self.ledger.reload()
        except LedgerError as exc:
            self.ledger_fault = str(exc)
            return True
        return self.ledger.remaining <= 0


def _is_count(value: object) -> bool:
    """A non-negative int; bool is an int in Python and is refused on purpose."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


class Ledger:
    """The one balance every proxied run draws from, kept in the bucket.

    Document: ``{"provider": "...", "cap_bytes": 1800000000, "used_bytes": N,
    "runs": {"<prefix>": bytes}, "updated": iso}``. ``cap_bytes`` is the owner's hard stop over
    *all* runs; an operator creates the document by hand with the balance already consumed
    (the ulta.ae snapshots) entered in ``used_bytes`` and ``runs``. Every charge is a
    read-modify-write guarded by the store's version token and retried on a lost race, so
    concurrent runs cannot both spend the same bytes.
    """

    def __init__(self, store: LedgerStore, run_id: str, clock: Callable[[], str]) -> None:
        self.store = store
        self.run_id = run_id
        self.clock = clock
        self.doc: dict[str, Any] = {}
        self.token: object = None
        self.reload()

    def reload(self) -> None:
        got = self.store.load()
        if got is None:
            raise LedgerError("proxy ledger does not exist; create it with the known balance")
        data, token = got
        try:
            doc = json.loads(data)
        except json.JSONDecodeError as exc:
            raise LedgerError("proxy ledger is not JSON") from exc
        if not isinstance(doc, dict) or any(not _is_count(doc.get(k)) for k in LEDGER_FIELDS):
            raise LedgerError("proxy ledger needs integer cap_bytes and used_bytes")
        runs = doc.get("runs", {})
        if not isinstance(runs, dict) or any(not _is_count(v) for v in runs.values()):
            raise LedgerError("proxy ledger runs must map run ids to byte counts")
        if doc["cap_bytes"] > DEFAULT_BYTE_CAP:
            raise LedgerError(f"proxy ledger cap_bytes exceeds the owner cap {DEFAULT_BYTE_CAP}")
        self.doc, self.token = doc, token

    @property
    def remaining(self) -> int:
        return max(0, int(self.doc["cap_bytes"]) - int(self.doc["used_bytes"]))

    def charge(self, n: int) -> None:
        for _ in range(SAVE_ATTEMPTS):
            self.doc["used_bytes"] = int(self.doc["used_bytes"]) + n
            runs = self.doc.setdefault("runs", {})
            runs[self.run_id] = int(runs.get(self.run_id, 0)) + n
            self.doc["updated"] = self.clock()
            if self.store.save(json.dumps(self.doc, indent=1).encode(), self.token):
                self.reload()
                return
            self.reload()  # lost the race: start from the other writer's figures
        raise LedgerError(f"proxy ledger could not be saved after {SAVE_ATTEMPTS} attempts")


def wire_bytes(response: Any) -> int:
    """Compressed bytes the response moved, falling back to the body length."""
    n = getattr(response, "num_bytes_downloaded", None)
    if isinstance(n, int) and n > 0:
        return n
    return len(response.content)
