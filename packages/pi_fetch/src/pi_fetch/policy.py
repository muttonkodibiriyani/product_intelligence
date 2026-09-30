"""Which rungs and methods a fetch may use (ADR-0003 as amended by ADR-0006).

The forbidden rungs come from ``pi_core`` (``FORBIDDEN_RUNGS`` / ``LadderRung.is_permitted``) and
are never redefined here. On top of that:

* rung 4 (egress variation) exists only when an egress profile is configured at runtime;
* rung 5 (paid proxy) exists only when the owner has approved it: the source context's cap must
  allow it **and** ``FetchPolicy.paid_proxy`` must name the approval. It is off by default;
* a browser fetch uses the engine pinned for the source in ``FetchPolicy.browsers`` (owner
  config). There is no default engine and no automatic engine fallback;
* robots.txt is obeyed unless the source is configured ``tag_only`` (Sephora only, ADR-0005);
* a source may set a page interval longer than the 1 s floor (e.g. ulta.ae: 5 s).
"""

import os
from collections.abc import Mapping
from enum import StrEnum

from pydantic import Field, field_validator

from pi_core import CollectionContext, FetchMethod, LadderRung, PiModel, SourceContext
from pi_core.types import DbId, NonEmptyStr
from pi_fetch.pacing import MIN_INTERVAL_FLOOR_S, RobotsMode
from pi_fetch.types import BrowserProfile, FetchRequest, PayloadKind

#: Egress name recorded on results fetched from the default (direct) network path.
DIRECT_EGRESS = "direct"

#: A normal desktop browser User-Agent (ADR-0005 §3). One fixed value: no rotation.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)

_RUNG0_METHOD: dict[PayloadKind, FetchMethod] = {
    PayloadKind.XML: FetchMethod.SITEMAP,
    PayloadKind.JSON: FetchMethod.SITE_API,
    PayloadKind.HTML: FetchMethod.EMBEDDED_JSON,
}


class LadderPolicyError(ValueError):
    """A request cannot be fetched under the configured policy (configuration error)."""


class Engine(StrEnum):
    """Transport family: plain HTTP (httpx) or a real browser (Playwright)."""

    HTTP = "http"
    BROWSER = "browser"


class EgressProfile(PiModel):
    """A network path. The proxy URL is read from an environment variable, never from git."""

    name: NonEmptyStr
    #: Environment variable holding the forward-proxy URL; None means a direct connection.
    proxy_url_env: NonEmptyStr | None = None

    def proxy_url(self) -> str | None:
        """The proxy URL, or None for a direct profile. Raises when the variable is unset."""
        if self.proxy_url_env is None:
            return None
        value = os.environ.get(self.proxy_url_env)
        if not value:
            msg = f"egress {self.name!r}: environment variable {self.proxy_url_env} is not set"
            raise LadderPolicyError(msg)
        return value


class PaidProxyConfig(PiModel):
    """Rung 5. Only configured after the owner decides on a Proxy Decision Report."""

    egress: EgressProfile
    #: Reference to the owner's written approval (e.g. decision id or doc link).
    owner_approval_ref: NonEmptyStr


class FetchPolicy(PiModel):
    """Runtime fetch configuration. The defaults allow rungs 0, 1 and 2 only."""

    user_agent: NonEmptyStr = DEFAULT_USER_AGENT
    #: The robots.txt group token (RFC 9309 §2.2.1). None: the product token of ``user_agent``.
    robots_agent: NonEmptyStr | None = None
    timeout_s: float = 30.0
    #: Rung 4: e.g. the Gulf Cloud Run egress. None disables the rung.
    egress_variation: EgressProfile | None = None
    #: Rung 5: None (the default) disables it.
    paid_proxy: PaidProxyConfig | None = None
    #: The browser pinned per source (``SourceContext.source_id``). A source without an entry
    #: cannot use a browser rung.
    browsers: Mapping[DbId, BrowserProfile] = Field(default_factory=dict)
    #: Sources that only tag robots.txt instead of obeying it. Owner decision per source.
    robots_modes: Mapping[DbId, RobotsMode] = Field(default_factory=dict)
    #: Minimum seconds between page requests to a source's host, when longer than the floor.
    page_interval_s: Mapping[DbId, float] = Field(default_factory=dict)

    @field_validator("page_interval_s")
    @classmethod
    def _check_intervals(cls, value: Mapping[DbId, float]) -> Mapping[DbId, float]:
        too_fast = sorted(k for k, v in value.items() if v < MIN_INTERVAL_FLOOR_S)
        if too_fast:
            msg = f"page_interval_s below {MIN_INTERVAL_FLOOR_S}s for sources {too_fast}"
            raise ValueError(msg)
        return value

    def robots_mode_for(self, source_id: DbId) -> RobotsMode:
        """OBEY unless the source is explicitly configured otherwise."""
        return self.robots_modes.get(source_id, RobotsMode.OBEY)

    def interval_for(self, source_id: DbId) -> float:
        """The source's page interval (at least the 1 s floor)."""
        return self.page_interval_s.get(source_id, MIN_INTERVAL_FLOOR_S)

    def browser_for(self, source_id: DbId) -> BrowserProfile:
        """The pinned browser for ``source_id``; raises when the owner has not pinned one."""
        profile = self.browsers.get(source_id)
        if profile is None:
            msg = f"no browser engine is pinned for source {source_id} (owner config)"
            raise LadderPolicyError(msg)
        return profile


class FetchPlan(PiModel):
    """How one request will be fetched: rung, audit method, transport and network path."""

    rung: LadderRung
    method: FetchMethod
    engine: Engine
    egress: EgressProfile
    #: Set exactly when ``engine`` is the browser.
    browser: BrowserProfile | None = None


def permitted_rungs(policy: FetchPolicy, source_context: SourceContext) -> tuple[LadderRung, ...]:
    """Rungs this policy may use for ``source_context``, cheapest first. Never a forbidden rung."""
    rungs: list[LadderRung] = []
    for rung in LadderRung:
        if not rung.is_permitted or rung > source_context.ladder_rung_max_allowed:
            continue
        if rung is LadderRung.EGRESS_VARIATION and policy.egress_variation is None:
            continue
        if rung.is_paid and policy.paid_proxy is None:
            continue
        rungs.append(rung)
    return tuple(rungs)


def next_rung(
    current: LadderRung, policy: FetchPolicy, source_context: SourceContext
) -> LadderRung | None:
    """The next permitted rung above ``current``, or None: stop, mark blocked and report.

    Escalation is a decision between runs, audit-logged by the caller; the fetcher itself never
    climbs on a block.
    """
    return next((r for r in permitted_rungs(policy, source_context) if r > current), None)


def plan(request: FetchRequest, ctx: CollectionContext, policy: FetchPolicy) -> FetchPlan:
    """Resolve the rung, method, engine and egress for ``request`` under ``ctx``.

    The rung is the context's ``ladder_rung_used``, raised to the browser rung for a ``render``
    request and to plain HTTP for an image (rung 0 has no image method). Raises
    ``LadderPolicyError`` when that rung is not permitted.
    """
    rung = ctx.ladder_rung_used
    if request.render and rung < LadderRung.BROWSER:
        rung = LadderRung.BROWSER
    if request.kind is PayloadKind.IMAGE and rung is LadderRung.SITE_DATA:
        rung = LadderRung.PLAIN_HTTP
    if rung not in permitted_rungs(policy, ctx.source_context):
        msg = f"rung {rung.name} is not permitted for this context and policy"
        raise LadderPolicyError(msg)
    method, engine, egress = _route(rung, request, policy)
    browser = policy.browser_for(ctx.source_context.source_id) if engine is Engine.BROWSER else None
    return FetchPlan(rung=rung, method=method, engine=engine, egress=egress, browser=browser)


def _route(
    rung: LadderRung, request: FetchRequest, policy: FetchPolicy
) -> tuple[FetchMethod, Engine, EgressProfile]:
    direct = EgressProfile(name=DIRECT_EGRESS)
    match rung:
        case LadderRung.SITE_DATA:
            return _RUNG0_METHOD[request.kind], Engine.HTTP, direct
        case LadderRung.PLAIN_HTTP:
            return FetchMethod.PLAIN_HTTP, Engine.HTTP, direct
        case LadderRung.BROWSER:
            return FetchMethod.PLAYWRIGHT, Engine.BROWSER, direct
        case LadderRung.EGRESS_VARIATION:
            if policy.egress_variation is None:  # pragma: no cover - permitted_rungs checked it
                msg = "rung 4 needs an egress profile"
                raise LadderPolicyError(msg)
            engine = Engine.BROWSER if request.render else Engine.HTTP
            return FetchMethod.EGRESS_VARIATION, engine, policy.egress_variation
        case LadderRung.PAID_PROXY:
            if policy.paid_proxy is None:  # pragma: no cover - permitted_rungs checked it
                msg = "rung 5 needs an owner-approved paid proxy config"
                raise LadderPolicyError(msg)
            if request.render or request.kind not in {PayloadKind.JSON, PayloadKind.XML}:
                # Blueprint §6.3: only JSON/API calls go through the paid proxy.
                msg = "the paid proxy carries JSON/API requests only"
                raise LadderPolicyError(msg)
            return FetchMethod.RESIDENTIAL_PROXY, Engine.HTTP, policy.paid_proxy.egress
        case _:  # pragma: no cover - forbidden rungs never reach here (permitted_rungs)
            msg = f"rung {rung.name} is forbidden"
            raise LadderPolicyError(msg)
