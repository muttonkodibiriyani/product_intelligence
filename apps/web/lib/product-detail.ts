import type { CaveatView, Schemas } from '@/lib/api/types';
import { priceState } from '@/lib/money';

type Offer = Schemas['OfferView'];
type Caps = Partial<Schemas['Capabilities']> | undefined;

/**
 * Why an offer attribute has no value: what the cell says (`state`) and the reason under it
 * (`reason`, a key in product.why). Never a 0 or an empty cell in its place.
 */
export interface Why {
  state: 'notPublished' | 'notMeasured' | 'none';
  reason: string;
}

/** The offer attributes that can be missing, each read from the API's own nulls and caveats. */
export type OfferField =
  | 'price'
  | 'regular'
  | 'member'
  | 'promo'
  | 'availability'
  | 'rating'
  | 'size'
  | 'shades'
  | 'sku'
  | 'images'
  | 'variants'
  | 'otherSizes';

type ContentState = Schemas['ContentState'];

/** A content field's own state: published but empty is the retailer's, not captured is ours. */
function contentWhy(state: ContentState, absent: string, notCollected: boolean): Why | null {
  if (state === 'observed') return null;
  if (state === 'not_published') return { state: 'notPublished', reason: absent };
  return { state: 'notMeasured', reason: notCollected ? 'notCollected' : 'contentNotCaptured' };
}

const wasPriceUnverified = (caveats: readonly CaveatView[], retailer: string) =>
  caveats.some((c) => c.code === 'was_price_unverified' && c.params.retailer === retailer);

/**
 * The reason `field` is missing on `o`, or null when it has a value (or a price under review,
 * which the price cell words itself). `caps` is /meta's capabilities: an attribute the dataset
 * doesn't collect is "not measured", never "not published" by the retailer. An offer the latest
 * crawl didn't see (`not_observed`, a listing carried from an earlier run) has no values by
 * design, so nothing on it can be read as the retailer's: every gap is "not seen".
 */
export function whyMissing(
  field: OfferField,
  o: Offer,
  caveats: readonly CaveatView[],
  caps: Caps,
): Why | null {
  const why = fieldWhy(field, o, caveats, caps);
  return why && why.state !== 'none' && o.availability === 'not_observed'
    ? { state: 'notMeasured', reason: 'notObserved' }
    : why;
}

function fieldWhy(field: OfferField, o: Offer, caveats: readonly CaveatView[], caps: Caps): Why | null {
  switch (field) {
    case 'price':
      return o.price || priceState(o) === 'review' ? null : { state: 'notPublished', reason: 'noPrice' };
    case 'regular':
      if (o.regular) return null;
      return wasPriceUnverified(caveats, o.retailer)
        ? { state: 'notMeasured', reason: 'wasPriceUnverified' }
        : { state: 'notPublished', reason: 'noRegular' };
    case 'member':
      // The contract carries no member (loyalty) price for any retailer: never shown as absent.
      return { state: 'notMeasured', reason: 'memberNotCollected' };
    case 'promo':
      // A discount on a price under review is no discount: the price itself isn't trusted.
      if (priceState(o) === 'review' || priceState({ price: o.regular }) === 'review')
        return { state: 'notMeasured', reason: 'priceUnderReview' };
      // The API sends a discount only when the price is below the regular price.
      if (o.promoPct) return null;
      if (!o.price) return { state: 'notMeasured', reason: 'needsPrice' };
      if (!o.regular)
        return wasPriceUnverified(caveats, o.retailer)
          ? { state: 'notMeasured', reason: 'wasPriceUnverified' }
          : { state: 'notMeasured', reason: 'needsRegular' };
      return { state: 'none', reason: 'atRegular' };
    case 'availability':
      return o.availability ? null : { state: 'notMeasured', reason: 'notCollected' };
    case 'rating':
      if (o.rating) return null;
      return caps?.ratings === false
        ? { state: 'notMeasured', reason: 'notCollected' }
        : { state: 'notPublished', reason: 'noRating' };
    case 'size':
      if (o.size || o.sizeLabel) return null;
      return caps?.sizes === false
        ? { state: 'notMeasured', reason: 'notCollected' }
        : { state: 'notPublished', reason: 'noSize' };
    case 'shades':
      // A count the retailer published, 0 included; 0 means the listing has no shade range.
      if (o.shadeCount === 0) return { state: 'none', reason: 'noShadeRange' };
      if (o.shadeCount !== null) return null;
      return caps?.shades === false
        ? { state: 'notMeasured', reason: 'notCollected' }
        : { state: 'notPublished', reason: 'noShades' };
    case 'sku':
      return o.sku ? null : { state: 'notPublished', reason: 'noSku' };
    case 'images': {
      const why = contentWhy(o.content.images.state, 'noImages', caps?.images === false);
      // An observed gallery the page can't show (no URL left) is not a gallery: say so.
      return (
        why ??
        (o.content.images.items.length > 0 ? null : { state: 'notMeasured', reason: 'contentNotCaptured' })
      );
    }
    case 'variants':
      return (
        contentWhy(o.content.variants.state, 'noVariants', false) ??
        (o.content.variants.items.length > 0 ? null : { state: 'notPublished', reason: 'noVariants' })
      );
    case 'otherSizes':
      // Sizes come from the page's own product family: with no page content there is no family.
      if (o.content.variants.state === 'not_captured' && o.content.sizes.length === 0)
        return { state: 'notMeasured', reason: 'contentNotCaptured' };
      return o.content.sizes.length > 0 ? null : { state: 'none', reason: 'noOtherSizes' };
  }
}

/**
 * The offers as columns: one per context, in the API's order. A retailer with more than one
 * context (a store, a delivery app) is named with the context, so two columns never read alike.
 */
export function columns(offers: readonly Offer[]): { offer: Offer; multi: boolean }[] {
  const per = new Map<string, number>();
  for (const o of offers) per.set(o.retailer, (per.get(o.retailer) ?? 0) + 1);
  return offers.map((offer) => ({ offer, multi: (per.get(offer.retailer) ?? 0) > 1 }));
}
