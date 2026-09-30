"""Polite fetch layer and connector contract (ADR-0003 as amended by ADR-0006).

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
from pi_fetch.ladder import Fetcher
from pi_fetch.mapping import to_canonical
from pi_fetch.pacing import HostPacer, OffPeakWindow, RobotsTag, RobotsTagger
from pi_fetch.policy import (
    EgressProfile,
    FetchPolicy,
    LadderPolicyError,
    PaidProxyConfig,
    next_rung,
    permitted_rungs,
)
from pi_fetch.transports.base import TransportError
from pi_fetch.types import (
    BlockVendor,
    BlockVerdict,
    CapturedJson,
    FetchRequest,
    FetchResult,
    PayloadKind,
)

#: Version of the connector-facing interface. Bump on any change connectors can see, and tell
#: the connector owners. 0.2: ParseOutput carries source-keyed drafts (coordinator ruling).
INTERFACE_VERSION = "0.2"

__all__ = [
    "INTERFACE_VERSION",
    "BlockVendor",
    "BlockVerdict",
    "CacheEntry",
    "CapturedJson",
    "Connector",
    "DiscoveredItem",
    "EgressProfile",
    "EvidenceStore",
    "FetchPolicy",
    "FetchRequest",
    "FetchResult",
    "Fetcher",
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
