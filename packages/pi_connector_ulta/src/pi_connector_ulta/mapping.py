"""Pure conversion from Ulta source records to interface-v0.2 drafts."""

from __future__ import annotations

import re
from decimal import Decimal

from pydantic import HttpUrl

from pi_connector_ulta._pi_fetch_stub import (
    FetchResult,
    ListingDraft,
    OfferDraft,
    ParseOutput,
)
from pi_connector_ulta.models import (
    Image,
    LocalizedText,
    PriceValue,
    ProductRecord,
    Stock,
    StockState,
    VariantRecord,
)
from pi_core import (
    AvailabilityState,
    CollectionContext,
    FieldState,
    ImageRef,
    ImageRole,
    Locale,
    PriceType,
    TaxStatus,
    is_valid_gtin,
)

_SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(\S+)\s*$")


def _text(value: LocalizedText, locale: Locale) -> str:
    selected = value.ar if locale is Locale.AR else value.en
    fallback = value.en if locale is Locale.AR else value.ar
    if selected:
        return selected
    if fallback:
        return fallback
    raise ValueError("localized text has no usable value")


def _size(value: LocalizedText | None) -> tuple[Decimal | None, str | None]:
    if value is None:
        return None, None
    raw = value.en or value.ar
    if raw is None or (match := _SIZE.fullmatch(raw)) is None:
        return None, None
    return Decimal(match.group(1)), match.group(2)


def _images(values: tuple[Image, ...]) -> tuple[ImageRef, ...] | None:
    if not values:
        return None
    return tuple(
        ImageRef(
            source_url=HttpUrl(str(image.url)),
            role=ImageRole.MAIN if index == 0 else ImageRole.ALT,
            position=0 if index == 0 else index - 1,
        )
        for index, image in enumerate(values)
    )


def _listing_draft(
    product: ProductRecord,
    variant: VariantRecord,
    result: FetchResult,
) -> ListingDraft:
    locale = result.request.locale
    size_value, size_unit = _size(variant.size)
    images = _images(variant.images or product.images)
    gtin = variant.barcode if variant.barcode and is_valid_gtin(variant.barcode) else None
    field_state: dict[str, FieldState] = {
        "mpn": FieldState.NOT_PUBLISHED,
        "shade_code": FieldState.NOT_PUBLISHED,
        "pack_count": FieldState.NOT_PUBLISHED,
        "concentration": FieldState.NOT_APPLICABLE,
    }
    if variant.sku is None:
        field_state["source_sku"] = FieldState.NOT_PUBLISHED
    if product.content.name.ar is None:
        field_state["name_ar"] = FieldState.NOT_PUBLISHED
    if gtin is None:
        field_state["gtin"] = (
            FieldState.PARSE_FAILURE if variant.barcode else FieldState.NOT_PUBLISHED
        )
    if variant.shade is None:
        field_state["shade"] = FieldState.NOT_APPLICABLE
    if size_value is None:
        field_state["size_value"] = FieldState.NOT_PUBLISHED
    if images is None:
        field_state["images"] = FieldState.NOT_PUBLISHED

    return ListingDraft(
        source_listing_key=variant.source_variant_id,
        source_sku=variant.sku,
        url=HttpUrl(str(product.canonical_url)),
        lang=locale,
        name_original=_text(product.content.name, locale),
        name_ar=product.content.name.ar,
        brand=_text(product.brand, locale),
        gtin=gtin,
        mpn=None,
        shade=_text(variant.shade, locale) if variant.shade else None,
        shade_code=None,
        size_value=size_value,
        size_unit=size_unit,
        pack_count=None,
        concentration=None,
        category_path_source=tuple(_text(category, locale) for category in product.category_path),
        images=images,
        attributes={"source_product_id": product.source_product_id},
        observed_at=result.retrieved_at,
        field_state=field_state,
    )


def _missing_state(value: PriceValue) -> FieldState:
    return (
        FieldState.NOT_APPLICABLE if value.reason and "not " in value.reason else FieldState.UNKNOWN
    )


def _availability(stock: Stock) -> tuple[AvailabilityState, FieldState | None]:
    if stock.state is StockState.IN_STOCK:
        return AvailabilityState.IN_STOCK, None
    if stock.state is StockState.OUT_OF_STOCK:
        return AvailabilityState.OUT_OF_STOCK, FieldState.OBSERVED
    return AvailabilityState.UNKNOWN, FieldState.UNKNOWN


def _offer_draft(
    product: ProductRecord,
    variant: VariantRecord,
    result: FetchResult,
    ctx: CollectionContext,
) -> OfferDraft:
    prices = variant.prices
    availability, availability_reason = _availability(variant.stock)
    rating = product.ratings
    field_state: dict[str, FieldState] = {
        "installment": FieldState.NOT_PUBLISHED,
        "delivery_promise": FieldState.NOT_PUBLISHED,
        "rank_in_category": FieldState.NOT_PUBLISHED,
    }
    price_values = {
        "price_current": prices.current,
        "price_regular_stated": prices.regular,
        "price_promo": prices.promo,
        "price_member": prices.member,
    }
    for field, value in price_values.items():
        if value.amount is None:
            field_state[field] = _missing_state(value)
    if prices.price_type in {PriceType.RANGE, PriceType.QUOTE_ONLY}:
        field_state["price_current"] = FieldState.NOT_APPLICABLE
    if rating.average is None:
        field_state.update(
            {
                "rating_value": FieldState.NOT_PUBLISHED,
                "rating_count": FieldState.NOT_PUBLISHED,
            }
        )
    if availability_reason is not None:
        field_state["availability_state"] = availability_reason

    return OfferDraft(
        source_listing_key=variant.source_variant_id,
        crawl_run_id=ctx.crawl_run_id,
        source_context_id=ctx.source_context.id,
        observed_at=result.retrieved_at,
        ingested_at=result.retrieved_at,
        price_current=prices.current.amount,
        price_regular_stated=prices.regular.amount,
        price_promo=prices.promo.amount,
        price_member=prices.member.amount,
        price_type=prices.price_type,
        price_range_min=prices.range_min.amount,
        price_range_max=prices.range_max.amount,
        currency=prices.current.currency,
        installment=None,
        tax_status=TaxStatus.UNKNOWN,
        availability_state=availability,
        available_variants=len(product.variants),
        low_stock_flag=False,
        delivery_promise=None,
        rating_value=rating.average,
        rating_scale=rating.rating_scale,
        rating_count=rating.count,
        rank_in_category=None,
        field_state=field_state,
    )


def map_product(
    product: ProductRecord,
    result: FetchResult,
    ctx: CollectionContext,
) -> ParseOutput:
    """Build deterministic source-keyed drafts; no database identity exists here."""
    if (
        result.ladder_rung_used is not ctx.ladder_rung_used
        or result.fetch_method is not ctx.fetch_method
    ):
        raise ValueError("fetch evidence method/rung differs from collection context")
    listings = tuple(_listing_draft(product, variant, result) for variant in product.variants)
    offers = tuple(_offer_draft(product, variant, result, ctx) for variant in product.variants)
    return ParseOutput(listings=listings, offers=offers)
