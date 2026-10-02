"""Polite fetch layer and connector contract (ADR-0003 as amended by ADR-0006).

The runner imports the fetcher from ``pi_fetch.ladder``; it is deliberately not re-exported
here, so connectors that import ``pi_fetch`` get the contract types only (see ``guard``).

Connectors describe *what* to fetch and parse what comes back; this package does all fetching:
rungs 0 (site data), 1 (plain httpx) and 2 (stock Playwright), plus egress variation (4) when
configured and the paid proxy (5) only with owner approval. Rung 3 is never used.
"""

from pi_fetch.blocks import detect
from pi_fetch.cache import (
    CacheEntry,
    EvidenceStore,
    GcsEvidenceStore,
    LocalEvidenceStore,
    MemoryValidatorCache,
    ValidatorCache,
)
from pi_fetch.connector import (
    Connector,
    DiscoveredItem,
    ListingDraft,
    OfferDraft,
    ParseError,
    ParseOutput,
    SourceListingKey,
)
from pi_fetch.guard import forbid_network, network_imports
from pi_fetch.mapping import to_canonical
from pi_fetch.pacing import (
    HostPacer,
    OffPeakWindow,
    RobotsMode,
    RobotsRefusedError,
    RobotsTag,
    RobotsTagger,
)
from pi_fetch.policy import (
    EgressProfile,
    FetchPolicy,
    LadderPolicyError,
    PaidProxyConfig,
    next_rung,
    permitted_rungs,
)
from pi_fetch.proxy import ProxyUsage, ResidentialProxy
from pi_fetch.transports.base import TransportError
from pi_fetch.types import (
    BlockKind,
    BlockVendor,
    BlockVerdict,
    BrowserEngine,
    BrowserProfile,
    CapturedJson,
    FetchRequest,
    FetchResult,
    PayloadKind,
)

#: Version of the connector-facing interface. Bump on any change connectors can see, and tell
#: the connector owners. 0.2: ParseOutput carries source-keyed drafts (coordinator ruling);
#: FetchResult records the pinned BrowserProfile of a browser fetch; FetchPolicy pins engines,
#: robots modes and page intervals per source; the Fetcher lives only in ``pi_fetch.ladder``;
#: BlockVerdict.kind (challenge | blocked | rate_limited): a 429 is RATE_LIMITED, and only
#: CHALLENGE and BLOCKED mark a source blocked (PDR, API-route refusal); FetchResult.rate_limited.
#: robots.txt is matched per RFC 9309 (wildcards, $, longest match).
#: Runner-side additions that connectors cannot see (no bump): FetchPolicy.residential_proxy
#: (rung 5 via the pinned browser, ulta.ae only), ProxyUsage, SourceStoppedError; a rung-5
#: FetchResult may carry the browser profile.
#: 0.3 (ADR-0007, markets as data): ``FetchRequest.locale`` and ``DiscoveredItem.locale`` are
#: canonical BCP 47 tags (``LocaleTag``, e.g. ``"ar-AE"``) validated to plain ``str``; the
#: deprecated ``Locale`` members still validate, but compare with ``==``, not ``is``. The
#: Accept-Language fallbacks come from ``FetchPolicy.accept_language_fallbacks`` (default
#: ``("en",)``, so AE/KSA headers are unchanged) and ``OffPeakWindow.time_zone`` is required.
INTERFACE_VERSION = "0.3"

__all__ = [
    "INTERFACE_VERSION",
    "BlockKind",
    "BlockVendor",
    "BlockVerdict",
    "BrowserEngine",
    "BrowserProfile",
    "CacheEntry",
    "CapturedJson",
    "Connector",
    "DiscoveredItem",
    "EgressProfile",
    "EvidenceStore",
    "FetchPolicy",
    "FetchRequest",
    "FetchResult",
    "GcsEvidenceStore",
    "HostPacer",
    "LadderPolicyError",
    "ListingDraft",
    "LocalEvidenceStore",
    "MemoryValidatorCache",
    "OffPeakWindow",
    "OfferDraft",
    "PaidProxyConfig",
    "ParseError",
    "ParseOutput",
    "PayloadKind",
    "ProxyUsage",
    "ResidentialProxy",
    "RobotsMode",
    "RobotsRefusedError",
    "RobotsTag",
    "RobotsTagger",
    "SourceListingKey",
    "TransportError",
    "ValidatorCache",
    "detect",
    "forbid_network",
    "network_imports",
    "next_rung",
    "permitted_rungs",
    "to_canonical",
]
