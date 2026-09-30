"""Network-free Ulta connector glue for interface sketch v0.1."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from pydantic import HttpUrl

from pi_connector_ulta._pi_fetch_stub import (
    CollectionContext,
    DiscoveredItem,
    FetchRequest,
    FetchResult,
    Locale,
    ParseError,
    ParseOutput,
    PayloadKind,
)
from pi_connector_ulta.mapping import map_product
from pi_connector_ulta.parse import parse_product_html, parse_product_json


class UltaConnector:
    """Pure discovery/request planning/parsing adapter; the runner owns fetching."""

    source_key = "ulta_ae"
    connector_version = "0.1.0"

    def discover(self, ctx: CollectionContext) -> Iterator[DiscoveredItem]:
        """Yield locale storefront seeds without fetching them."""
        del ctx
        for locale in (Locale.EN, Locale.AR):
            yield DiscoveredItem(
                url=HttpUrl(f"https://www.ulta.ae/{locale.value}/"),
                kind=PayloadKind.HTML,
                locale=locale,
            )

    def requests_for(self, item: DiscoveredItem, ctx: CollectionContext) -> Sequence[FetchRequest]:
        """Map one discovered item to a request; perform no I/O."""
        del ctx
        return (
            FetchRequest(
                url=item.url,
                kind=item.kind,
                locale=item.locale,
                render=item.render,
                capture_json=item.render,
            ),
        )

    def parse(self, result: FetchResult, ctx: CollectionContext) -> ParseOutput:
        """Parse one successful fixture-backed fetch result deterministically."""
        if result.block is not None:
            raise ParseError("blocked fetch results must never be parsed")
        if not result.ok:
            raise ParseError(
                f"unsuccessful fetch status {result.http_status}: not observed; no records emitted"
            )
        try:
            document = result.body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ParseError("product payload is not UTF-8") from exc
        if result.request.kind is PayloadKind.JSON:
            record = parse_product_json(document)
        elif result.request.kind is PayloadKind.HTML:
            record = parse_product_html(document)
        else:
            raise ParseError(f"unsupported product payload kind: {result.request.kind.value}")

        return map_product(record, result, ctx)
