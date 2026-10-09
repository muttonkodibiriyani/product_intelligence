import type { CaveatView, Schemas } from '@/lib/api/types';
import { priceState } from '@/lib/money';

type Offer = Schemas['OfferView'];
type Caps = Partial<Schemas['Capabilities']> | undefined;
/** The offer's own source's declared field states (/meta `sources[].fields`), by field key. */
type Fields = Readonly<Record<string, Schemas['FieldStatus']>> | undefined;

/** The /meta field key each offer attribute is declared under (pi_dataset `RetailerV3.fields`). */
const FIELD_KEY: Partial<Record<OfferField, string>> = {
  price: 'price',
  regular: 'regular',
  availability: 'stock',
  rating: 'rating',
  size: 'size',
  shades: 'shades',
  sku: 'sku',
};

/**
 * "Not published" is a claim about the retailer's page, so it stands only when the source does not
 * declare otherwise: a field the source says it did not collect, could not parse, was blocked on
 * or collected only in part is ours, not the retailer's, and says so.
 */
const DECLARED: Partial<Record<Schemas['FieldStatus'], Why>> = {
  not_collected: { state: 'notMeasured', reason: 'notCollected' },
  parse_failure: { state: 'notMeasured', reason: 'parseFailure' },
  blocked: { state: 'notMeasured', reason: 'blocked' },
  partial: { state: 'notMeasured', reason: 'partialCollection' },
};

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
  'price' | 'regular' | 'promo' | 'availability' | 'rating' | 'size' | 'shades' | 'sku';

const wasPriceUnverified = (caveats: readonly CaveatView[], retailer: string) =>
  caveats.some((c) => c.code === 'was_price_unverified' && c.params.retailer === retailer);

/**
 * The reason `field` is missing on `o`, or null when it has a value (or a price under review,
 * which the price cell words itself). `caps` is /meta's capabilities: an attribute the dataset
 * doesn't collect is "not measured", never "not published" by the retailer. An offer the latest
 * crawl didn't see (`not_observed`, a listing carried from an earlier run) has no values by
 * design, so nothing on it can be read as the retailer's: every gap is "not seen". `fields` is
 * the offer's source's declared field states: "not published" yields to any declared state that
 * makes the gap ours (not collected, parse failure, blocked, partial).
 */
export function whyMissing(
  field: OfferField,
  o: Offer,
  caveats: readonly CaveatView[],
  caps: Caps,
  fields?: Fields,
): Why | null {
  const why = fieldWhy(field, o, caveats, caps);
  if (why && why.state !== 'none' && o.availability === 'not_observed')
    return { state: 'notMeasured', reason: 'notObserved' };
  if (why?.state !== 'notPublished') return why;
  const key = FIELD_KEY[field];
  const declared = key ? fields?.[key] : undefined;
  return (declared && DECLARED[declared]) ?? why;
}

/**
 * The declared field states of the one source that is this retailer's, or none when /meta sends
 * no source, or more than one, of that exact id (conflicting declarations are never merged).
 */
export function sourceFields(
  sources: readonly Pick<Schemas['SourceInfo'], 'source' | 'fields'>[] | undefined,
  retailer: string,
): Fields {
  const own = (sources ?? []).filter((s) => s.source === retailer);
  return own.length === 1 ? own[0]!.fields : undefined;
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
