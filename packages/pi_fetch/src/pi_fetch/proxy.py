"""Rung 5: the owner-approved residential proxy (ADR-0006 decision 5; owner decision for ulta.ae).

Credentials never live in git, config or logs. They are read at runtime from Secret Manager
(``.../versions/latest``, so a rotation takes effect on the next run), held in ``SecretStr`` and
kept out of every repr, audit event and exception message (``redact``). Nothing is cached to disk.

The proxy is metered: ``ProxyMeter`` counts request and response bytes through the proxy for the
run and stops it at a hard cap (default 1.8 GB of the 2 GB balance, owner decision), never
sending a request that could cross it (``page_reserve_bytes``/``request_reserve_bytes``). In the
proxied browser, heavy assets (images, media, fonts, pings) and third-party hosts (analytics,
tag managers, CDNs not allow-listed) are aborted before they are requested (``should_abort``).
The proxy may only ever be configured for ulta.ae (``PROXY_SOURCES``).
"""

import json
import re
import subprocess
import threading
from collections.abc import Callable, Iterable
from decimal import Decimal
from typing import Protocol, Self

import httpx
from pydantic import Field, SecretStr, ValidationError, field_validator

from pi_core import PiModel
from pi_core.types import NonEmptyStr

#: Default hard stop for bytes through the proxy per run: 1.8 GB (decimal), keeping 0.2 GB of the
#: 2 GB balance for a re-test (owner decision).
DEFAULT_BYTE_CAP = 1_800_000_000
#: The owner-approved price of the IPRoyal residential plan.
DEFAULT_USD_PER_GB = Decimal("6.25")
_BYTES_PER_GB = Decimal(1000**3)
#: The only sources a residential proxy may be configured for, with their registrable domain.
PROXY_SOURCES: dict[str, str] = {"ulta_ae": "ulta.ae"}
REDACTED = "REDACTED"

_SECRET_RESOURCE_RE = re.compile(r"^projects/[a-z0-9-]+/secrets/[A-Za-z0-9_-]+/versions/latest$")
_SM_ACCESS_URL = "https://secretmanager.googleapis.com/v1/{resource}:access"
_METADATA_SA_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-account/token"
)
#: Resource types never loaded through the proxy (bandwidth is billed per GB).
HEAVY_RESOURCE_TYPES = frozenset({"image", "media", "font", "texttrack", "ping", "manifest"})
#: Second-level labels under which a registrable domain has three labels (e.g. ``x.co.uk``).
_SECOND_LEVEL = frozenset({"co", "com", "net", "org", "gov", "ac", "edu"})


class ProxyConfigError(RuntimeError):
    """The proxy secret could not be read or is malformed. Never carries the secret's content."""


class ProxyBudgetExceededError(RuntimeError):
    """The run hit its proxy byte cap: stop the run (no more proxied requests)."""


class ResidentialProxy(PiModel):
    """Per-source rung-5 config. Holds where the credentials are, never the credentials."""

    #: The source this proxy is for; only keys in ``PROXY_SOURCES`` (ulta.ae) are accepted.
    source_key: NonEmptyStr
    #: Reference to the owner's written approval (decision id or doc link).
    owner_approval_ref: NonEmptyStr
    #: Secret Manager resource, always the ``latest`` version so rotation needs no deploy.
    secret_resource: NonEmptyStr
    #: Egress name recorded on results and audit events (e.g. ``iproyal_ae``).
    egress_name: NonEmptyStr
    #: Hard stop for request + response bytes through the proxy, over **all** runs on this
    #: allowance (the owner's 1.8 GB out of one prepaid balance), not per run.
    byte_cap: int = Field(default=DEFAULT_BYTE_CAP, gt=0)
    #: Bytes already used from ``byte_cap`` by earlier runs (their manifests' ``bytes_via_proxy``
    #: or the provider dashboard). Required, so a restart cannot silently start again at 0.
    prior_bytes: int = Field(ge=0)
    #: Headroom a page load may need: no page is started unless this much of the cap is left.
    page_reserve_bytes: int = Field(default=8_000_000, ge=0)
    #: Headroom per sub-request (XHR, script): aborted unless this much of the cap is left.
    request_reserve_bytes: int = Field(default=1_000_000, ge=0)
    usd_per_gb: Decimal = Field(default=DEFAULT_USD_PER_GB, ge=0)
    #: Third-party hosts the proxied browser may still load (first party is always allowed).
    allow_hosts: frozenset[str] = frozenset()

    @field_validator("source_key")
    @classmethod
    def _check_source(cls, value: str) -> str:
        if value not in PROXY_SOURCES:
            msg = f"a residential proxy is approved only for {sorted(PROXY_SOURCES)}, not {value!r}"
            raise ValueError(msg)
        return value

    @property
    def site_domain(self) -> str:
        """The registrable domain the proxy may carry requests to (e.g. ``ulta.ae``)."""
        return PROXY_SOURCES[self.source_key]

    @field_validator("secret_resource")
    @classmethod
    def _check_resource(cls, value: str) -> str:
        if not _SECRET_RESOURCE_RE.fullmatch(value):
            msg = "secret_resource must be projects/<p>/secrets/<name>/versions/latest"
            raise ValueError(msg)
        return value


class ProxyCredentials(PiModel):
    """The proxy endpoint and login. ``username``/``password`` never appear in a repr."""

    host: NonEmptyStr
    port: int = Field(ge=1, le=65535)
    username: SecretStr
    password: SecretStr
    provider: NonEmptyStr

    @property
    def server(self) -> str:
        """``http://host:port`` without credentials (safe to log)."""
        return f"http://{self.host}:{self.port}"

    def playwright_proxy(self) -> dict[str, str]:
        """Playwright's ``proxy`` launch option. Do not log the returned dict."""
        return {
            "server": self.server,
            "username": self.username.get_secret_value(),
            "password": self.password.get_secret_value(),
        }

    def secrets(self) -> tuple[str, ...]:
        """The values ``redact`` must remove from any text."""
        return (self.username.get_secret_value(), self.password.get_secret_value())


def redact(text: str, secrets: Iterable[str]) -> str:
    """``text`` with every secret value replaced by ``REDACTED`` (longest first)."""
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    return text


class SecretReader(Protocol):
    """Reads a secret version's payload. Implementations must not cache it to disk."""

    def read(self, resource: str) -> bytes: ...


TokenProvider = Callable[[], str]


def metadata_token(client: httpx.Client | None = None) -> str:
    """An access token from the GCE/Cloud Run metadata server (the runtime service account)."""
    http = client or httpx.Client(timeout=5.0)
    try:
        response = http.get(_METADATA_SA_URL, headers={"Metadata-Flavor": "Google"})
        response.raise_for_status()
        return str(response.json()["access_token"])
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        msg = f"no access token from the metadata server ({type(exc).__name__})"
        raise ProxyConfigError(msg) from None
    finally:
        if client is None:
            http.close()


def gcloud_token() -> str:
    """An access token from the local gcloud login (developer runs)."""
    try:
        done = subprocess.run(
            ["gcloud", "auth", "print-access-token"],  # noqa: S607 - gcloud from PATH
            capture_output=True,
            check=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        msg = f"gcloud auth print-access-token failed ({type(exc).__name__})"
        raise ProxyConfigError(msg) from None
    return done.stdout.strip()


class SecretManagerReader:
    """Secret Manager over its REST API (``versions/latest:access``); in memory only."""

    def __init__(
        self, token: TokenProvider = metadata_token, client: httpx.Client | None = None
    ) -> None:
        self._token = token
        self._client = client

    def read(self, resource: str) -> bytes:
        """The payload of ``resource``. Errors name the resource and status, never the payload."""
        import base64  # noqa: PLC0415 - only needed here

        http = self._client or httpx.Client(timeout=10.0)
        try:
            response = http.get(
                _SM_ACCESS_URL.format(resource=resource),
                headers={"Authorization": f"Bearer {self._token()}"},
            )
            if response.status_code != httpx.codes.OK:
                msg = f"secret {resource}: HTTP {response.status_code}"
                raise ProxyConfigError(msg)
            return base64.b64decode(response.json()["payload"]["data"])
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            msg = f"secret {resource}: unreadable response ({type(exc).__name__})"
            raise ProxyConfigError(msg) from None
        finally:
            if self._client is None:
                http.close()


def load_credentials(reader: SecretReader, resource: str) -> ProxyCredentials:
    """Read and validate the proxy secret (JSON host/port/username/password/provider).

    Raised errors name only the resource and the failing field names, never a value.
    """
    payload = reader.read(resource)
    try:
        data = json.loads(payload)
        return ProxyCredentials.model_validate(data)
    except ValueError as exc:
        fields = (
            sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
            if isinstance(exc, ValidationError)
            else []
        )
        msg = f"secret {resource}: not valid proxy credentials (fields: {fields or 'json'})"
        raise ProxyConfigError(msg) from None


def registrable_domain(host: str) -> str:
    """``www.ulta.ae`` → ``ulta.ae``; ``a.b.co.uk`` → ``b.co.uk`` (small built-in table, no PSL)."""
    labels = host.lower().rstrip(".").split(".")
    size = 3 if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL else 2
    return ".".join(labels[-size:])


def should_abort(
    resource_type: str, url_host: str, site_host: str, allow_hosts: frozenset[str]
) -> bool:
    """True when the proxied browser must not load this request.

    Heavy assets always; anything off the page's registrable domain unless allow-listed.
    """
    if resource_type in HEAVY_RESOURCE_TYPES:
        return True
    host = url_host.lower()
    if host in allow_hosts:
        return False
    return registrable_domain(host) != registrable_domain(site_host)


class ProxyUsage(PiModel):
    """Proxy bytes for the run manifest (``bytes_via_proxy``, Blueprint §5)."""

    egress: str
    bytes_sent: int
    bytes_received: int
    #: Bytes of the same allowance used by earlier runs (seeded into the meter).
    prior_bytes: int = 0
    byte_cap: int
    usd_per_gb: Decimal
    stopped: bool

    @property
    def total(self) -> int:
        """Request plus response bytes."""
        return self.bytes_sent + self.bytes_received

    @property
    def allowance_used(self) -> int:
        """Earlier runs' bytes plus this run's: what counts against ``byte_cap``."""
        return self.prior_bytes + self.total

    @property
    def usd(self) -> Decimal:
        """Cost of the run's proxy bytes at the plan price, to the cent."""
        return (Decimal(self.total) / _BYTES_PER_GB * self.usd_per_gb).quantize(Decimal("0.01"))

    def manifest(self) -> dict[str, str | int | bool]:
        """The run-manifest entry (``bytes_via_proxy`` and its cost)."""
        return {
            "egress": self.egress,
            "bytes_via_proxy": self.total,
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
            "prior_bytes": self.prior_bytes,
            "allowance_used": self.allowance_used,
            "byte_cap": self.byte_cap,
            "usd_per_gb": str(self.usd_per_gb),
            "usd": str(self.usd),
            "stopped_at_cap": self.stopped,
        }


class ProxyMeter:
    """Counts bytes through one proxy for one run and enforces the cap. Thread-safe.

    Counts come from Playwright's ``Request.sizes()`` (headers + bodies). TLS and CONNECT
    overhead are not visible there, so the provider's bill runs somewhat higher: set the cap
    with margin.

    The meter starts at ``prior_bytes`` (earlier runs' use of the same allowance). Bytes are
    added when a request *finishes*, so concurrent sub-requests of one page may together pass
    ``request_reserve``: at worst one page overshoots by its own size. ``page_reserve`` (8 MB)
    and the owner's 0.2 GB margin absorb that and the TLS/CONNECT overhead; the transport logs
    each page's bytes (``proxy_page_bytes``) so the reserve can be checked against real pages.
    """

    def __init__(  # noqa: PLR0913 - keyword-only tuning knobs
        self,
        egress: str,
        byte_cap: int,
        *,
        usd_per_gb: Decimal = DEFAULT_USD_PER_GB,
        page_reserve: int = 0,
        request_reserve: int = 0,
        prior_bytes: int = 0,
    ) -> None:
        self._egress = egress
        self._prior = max(prior_bytes, 0)
        self._cap = byte_cap
        self._usd_per_gb = usd_per_gb
        self._page_reserve = page_reserve
        self._request_reserve = request_reserve
        self._sent = 0
        self._received = 0
        self._lock = threading.Lock()

    @classmethod
    def for_config(cls, config: ResidentialProxy) -> Self:
        """A meter with the config's egress name and cap."""
        return cls(
            config.egress_name,
            config.byte_cap,
            usd_per_gb=config.usd_per_gb,
            page_reserve=config.page_reserve_bytes,
            request_reserve=config.request_reserve_bytes,
            prior_bytes=config.prior_bytes,
        )

    def _would_cross(self, reserve: int) -> bool:
        with self._lock:
            return self._prior + self._sent + self._received + reserve > self._cap

    @property
    def exhausted(self) -> bool:
        """True once a new page could cross the cap: no further page may be started."""
        with self._lock:
            used = self._prior + self._sent + self._received
        return used >= self._cap or used + self._page_reserve > self._cap

    def allows_subrequest(self) -> bool:
        """False once a sub-request of up to ``request_reserve`` bytes could cross the cap."""
        return not self._would_cross(self._request_reserve)

    @property
    def run_bytes(self) -> int:
        """Bytes through the proxy in this run (excluding ``prior_bytes``)."""
        with self._lock:
            return self._sent + self._received

    def add(self, sent: int, received: int) -> None:
        """Record one request's bytes."""
        with self._lock:
            self._sent += max(sent, 0)
            self._received += max(received, 0)

    def check(self) -> None:
        """Raise ``ProxyBudgetExceededError`` when a new page could cross the cap."""
        if self.exhausted:
            usage = self.usage()
            msg = (
                f"proxy {self._egress}: {usage.allowance_used} bytes used; another page "
                f"(reserve {self._page_reserve}) could cross the cap of {self._cap}"
            )
            raise ProxyBudgetExceededError(msg)

    def usage(self) -> ProxyUsage:
        """A snapshot for the run manifest."""
        with self._lock:
            sent, received = self._sent, self._received
        used = self._prior + sent + received
        return ProxyUsage(
            egress=self._egress,
            bytes_sent=sent,
            bytes_received=received,
            prior_bytes=self._prior,
            byte_cap=self._cap,
            usd_per_gb=self._usd_per_gb,
            stopped=used + self._page_reserve > self._cap or used >= self._cap,
        )
