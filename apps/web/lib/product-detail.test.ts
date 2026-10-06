import { describe, expect, it } from 'vitest';
import product from '../../../docs/contracts/golden/pi-api/product.json';
import type { CaveatView, Schemas } from '@/lib/api/types';
import { columns, whyMissing, type OfferField } from './product-detail';

type Offer = Schemas['OfferView'];
const full = product.data.offers[0] as Offer;
const aed = (amount: string) => ({ amount, currency: 'AED', minor: Math.round(Number(amount) * 100) });
const wasPrice: CaveatView = {
  code: 'was_price_unverified',
  params: { retailer: 'shop_a' },
  en: '',
  ar: '',
};
const FIELDS: OfferField[] = ['price', 'regular', 'promo', 'availability', 'rating', 'size', 'shades', 'sku'];
const sparse: Offer = {
  ...full,
  price: null,
  regular: null,
  promoPct: null,
  availability: null,
  rating: null,
  size: null,
  sizeLabel: null,
  shadeCount: null,
  sku: null,
};

describe('whyMissing', () => {
  it('says nothing for a value the API sent', () => {
    const o = { ...full, sku: 'A1', shadeCount: 12 };
    for (const f of FIELDS) expect(whyMissing(f, o, [], undefined)).toBeNull();
  });

  it('gives every missing attribute a state and a reason, never a value', () => {
    expect(Object.fromEntries(FIELDS.map((f) => [f, whyMissing(f, sparse, [], undefined)]))).toEqual({
      price: { state: 'notPublished', reason: 'noPrice' },
      regular: { state: 'notPublished', reason: 'noRegular' },
      promo: { state: 'notMeasured', reason: 'needsPrice' },
      availability: { state: 'notMeasured', reason: 'notCollected' },
      rating: { state: 'notPublished', reason: 'noRating' },
      size: { state: 'notPublished', reason: 'noSize' },
      shades: { state: 'notPublished', reason: 'noShades' },
      sku: { state: 'notPublished', reason: 'noSku' },
    });
  });

  it('reads an unverified was-price as not measured, for the regular price and the discount', () => {
    const o = { ...full, regular: null, promoPct: null };
    expect(whyMissing('regular', o, [wasPrice], undefined)).toEqual({
      state: 'notMeasured',
      reason: 'wasPriceUnverified',
    });
    expect(whyMissing('promo', o, [wasPrice], undefined)?.reason).toBe('wasPriceUnverified');
    // Another retailer's caveat doesn't apply.
    expect(whyMissing('regular', { ...o, retailer: 'shop_b' }, [wasPrice], undefined)?.reason).toBe(
      'noRegular',
    );
    expect(whyMissing('promo', { ...o, retailer: 'shop_b' }, [wasPrice], undefined)?.reason).toBe(
      'needsRegular',
    );
  });

  it('a price at the regular price has no discount; a price under review has none measured', () => {
    expect(whyMissing('promo', { ...full, promoPct: null, price: aed('100.00') }, [], undefined)).toEqual({
      state: 'none',
      reason: 'atRegular',
    });
    const review = { ...full, price: null, priceFlag: 'invalid_low' as const, promoPct: null };
    expect(whyMissing('price', review, [], undefined)).toBeNull();
    expect(whyMissing('promo', review, [], undefined)?.reason).toBe('priceUnderReview');
    // A 0.01 price the API didn't flag drops its discount too.
    expect(whyMissing('promo', { ...full, price: aed('0.01') }, [], undefined)?.reason).toBe(
      'priceUnderReview',
    );
  });

  it('0 shades is the retailer saying there is no range, not a count of 0', () => {
    expect(whyMissing('shades', { ...full, shadeCount: 0 }, [], undefined)).toEqual({
      state: 'none',
      reason: 'noShadeRange',
    });
  });

  it('a size label alone is a size', () => {
    expect(whyMissing('size', { ...sparse, sizeLabel: 'M', sizeSystem: 'EU' }, [], undefined)).toBeNull();
  });

  it('an attribute the dataset does not collect is not measured', () => {
    expect(whyMissing('rating', sparse, [], { ratings: false })).toEqual({
      state: 'notMeasured',
      reason: 'notCollected',
    });
    expect(whyMissing('size', sparse, [], { sizes: false })?.state).toBe('notMeasured');
    expect(whyMissing('shades', sparse, [], { shades: false })).toEqual({
      state: 'notMeasured',
      reason: 'notCollected',
    });
    // A published 0 is still the retailer's answer, collected or not.
    expect(whyMissing('shades', { ...full, shadeCount: 0 }, [], { shades: false })?.reason).toBe(
      'noShadeRange',
    );
  });
});

describe('columns', () => {
  it('one per offer; a retailer with two contexts is marked so they can be told apart', () => {
    const offers = [
      full,
      { ...full, context: 'shop_a_pickup', channel: 'pickup' as const },
      product.data.offers[1],
    ];
    expect(columns(offers as Offer[]).map((c) => [c.offer.context, c.multi])).toEqual([
      ['shop_a', true],
      ['shop_a_pickup', true],
      ['shop_b', false],
    ]);
  });
});
