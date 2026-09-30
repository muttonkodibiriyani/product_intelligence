"""A minimal offline connector used to exercise the contract (not a real source)."""

import json
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar

from pydantic import HttpUrl

from pi_core import (
    AvailabilityState,
    CollectionContext,
    FieldState,
    Locale,
    PriceType,
    TaxStatus,
)
from pi_fetch import (
    DiscoveredItem,
    FetchRequest,
    FetchResult,
    ListingDraft,
    OfferDraft,
    ParseError,
    ParseOutput,
    PayloadKind,
)

LISTING_GAPS = {
    "source_sku": FieldState.NOT_PUBLISHED,
    "name_ar": FieldState.NOT_PUBLISHED,
    "gtin": FieldState.NOT_PUBLISHED,
    "mpn": FieldState.NOT_PUBLISHED,
    "shade": FieldState.NOT_APPLICABLE,
    "shade_code": FieldState.NOT_APPLICABLE,
    "size_value": FieldState.NOT_PUBLISHED,
    "pack_count": FieldState.NOT_PUBLISHED,
    "concentration": FieldState.NOT_PUBLISHED,
    "category_path_source": FieldState.NOT_PUBLISHED,
    "images": FieldState.NOT_PUBLISHED,
}
OFFER_GAPS = {
    "price_regular_stated": FieldState.NOT_PUBLISHED,
    "price_promo": FieldState.NOT_PUBLISHED,
    "price_member": FieldState.NOT_PUBLISHED,
    "installment": FieldState.NOT_PUBLISHED,
    "available_variants": FieldState.NOT_PUBLISHED,
    "low_stock_flag": FieldState.NOT_PUBLISHED,
    "delivery_promise": FieldState.NOT_PUBLISHED,
    "rating_value": FieldState.NOT_PUBLISHED,
    "rating_count": FieldState.NOT_PUBLISHED,
    "rank_in_category": FieldState.NOT_PUBLISHED,
    "availability_state": FieldState.OBSERVED,
}


class SampleConnector:
    """Reads ``{"id", "name", "brand", "price", "in_stock", "observed_at"}`` product JSON."""

    source_key: ClassVar[str] = "sample_ae"
    connector_version: ClassVar[str] = "0.1.0"

    def discover(self, ctx: CollectionContext) -> Iterator[DiscoveredItem]:
        yield DiscoveredItem(
            url=HttpUrl("https://shop.example/api/p/SKU-1"),
            kind=PayloadKind.JSON,
            locale=ctx.locale,
            source_listing_key="SKU-1",
        )

    def requests_for(self, item: DiscoveredItem, ctx: CollectionContext) -> Sequence[FetchRequest]:
        return [FetchRequest(url=item.url, kind=item.kind, locale=item.locale)]

    def parse(self, result: FetchResult, ctx: CollectionContext) -> ParseOutput:
        try:
            data = json.loads(result.body)
            key, price = str(data["id"]), Decimal(str(data["price"]))
            observed_at = datetime.fromisoformat(data["observed_at"]).astimezone(UTC)
        except (ValueError, KeyError, TypeError) as exc:
            raise ParseError(str(exc)) from exc
        listing = ListingDraft(
            source_listing_key=key,
            source_sku=None,
            url=result.final_url,
            lang=Locale(result.request.locale),
            name_original=data["name"],
            name_ar=None,
            brand=data["brand"],
            gtin=None,
            mpn=None,
            shade=None,
            shade_code=None,
            size_value=None,
            pack_count=None,
            concentration=None,
            category_path_source=None,
            images=None,
            observed_at=observed_at,
            field_state=LISTING_GAPS,
        )
        offer = OfferDraft(
            source_listing_key=key,
            crawl_run_id=ctx.crawl_run_id,
            source_context_id=ctx.source_context.id,
            observed_at=observed_at,
            price_current=price,
            price_regular_stated=None,
            price_promo=None,
            price_member=None,
            price_type=PriceType.FULL,
            currency=ctx.currency,
            installment=None,
            tax_status=TaxStatus.INCLUDED,
            availability_state=(
                AvailabilityState.IN_STOCK if data["in_stock"] else AvailabilityState.OUT_OF_STOCK
            ),
            available_variants=None,
            low_stock_flag=None,
            delivery_promise=None,
            rating_value=None,
            rating_count=None,
            rank_in_category=None,
            field_state=OFFER_GAPS,
        )
        return ParseOutput(listings=(listing,), offers=(offer,))
