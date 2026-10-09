import { describe, expect, it } from 'vitest';
import product from '../../../docs/contracts/golden/pi-api/product.json';
import type { CaveatView, Schemas } from '@/lib/api/types';
import ar from '@/messages/ar.json';
import en from '@/messages/en.json';
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

describe('whyMissing on an offer the latest crawl did not see', () => {
  // A listing carried from an earlier run: no price, no stock reading, nothing the retailer said.
  const carried: Offer = { ...sparse, availability: 'not_observed', sku: 'A1' };
  const why = (o: Offer) => FIELDS.map((f) => whyMissing(f, o, [], undefined));

  it('says every gap is not seen, never not published', () => {
    expect(Object.fromEntries(FIELDS.map((f) => [f, whyMissing(f, carried, [], undefined)]))).toEqual({
      price: { state: 'notMeasured', reason: 'notObserved' },
      regular: { state: 'notMeasured', reason: 'notObserved' },
      promo: { state: 'notMeasured', reason: 'notObserved' },
      availability: null,
      rating: { state: 'notMeasured', reason: 'notObserved' },
      size: { state: 'notMeasured', reason: 'notObserved' },
      shades: { state: 'notMeasured', reason: 'notObserved' },
      sku: null,
    });
    // Ahead of a was-price caveat and of a dataset that does not collect the attribute.
    expect(whyMissing('regular', carried, [wasPrice], { ratings: false })?.reason).toBe('notObserved');
    expect(whyMissing('rating', carried, [], { ratings: false })?.reason).toBe('notObserved');
  });

  it('keeps a value it carries and a published 0 shades', () => {
    expect(whyMissing('price', { ...carried, price: aed('40.00') }, [], undefined)).toBeNull();
    expect(whyMissing('shades', { ...carried, shadeCount: 0 }, [], undefined)?.reason).toBe('noShadeRange');
  });

  it('an ordinary offer with no price is still not published', () => {
    expect(whyMissing('price', sparse, [], undefined)).toEqual({ state: 'notPublished', reason: 'noPrice' });
    expect(whyMissing('price', { ...sparse, availability: 'out_of_stock' }, [], undefined)?.reason).toBe(
      'noPrice',
    );
  });

  for (const [locale, m, notPublished, notSeen] of [
    ['en', en, 'Not published', 'Not seen in the latest crawl.'],
    ['ar', ar, 'غير منشور', 'لم يُرصد في آخر جمع.'],
  ] as const) {
    it(`reads "not seen" in ${locale}, and nothing on it reads "not published"`, () => {
      const text = why(carried)
        .filter((w) => w !== null)
        .map((w) => `${m.product.state[w.state]} ${(m.product.why as Record<string, string>)[w.reason]}`);
      expect(text.length).toBe(6);
      for (const t of text) {
        expect(t).toContain(notSeen);
        expect(t).not.toContain(notPublished);
      }
      // The control: the same render of an ordinary offer does say it.
      const w = whyMissing('price', sparse, [], undefined)!;
      expect(m.product.state[w.state]).toBe(notPublished);
    });
  }
});

type Content = Offer['content'];
const content = (c: Partial<Content>): Offer => ({ ...full, content: { ...full.content, ...c } });
const IMG = 'https://img-product.sephora.me/p/1.jpg';

describe('whyMissing on page content and member price', () => {
  it('the golden offer, with no page content, says it was not captured, never not published', () => {
    for (const f of ['images', 'variants', 'otherSizes'] as const)
      expect(whyMissing(f, full, [], undefined)).toEqual({
        state: 'notMeasured',
        reason: 'contentNotCaptured',
      });
  });

  it('a member price is not collected for any offer, with or without a price', () => {
    for (const o of [full, sparse])
      expect(whyMissing('member', o, [], undefined)).toEqual({
        state: 'notMeasured',
        reason: 'memberNotCollected',
      });
  });

  it("observed content has a value; content the page did not publish is the retailer's", () => {
    const o = content({
      images: { state: 'observed', items: [{ url: IMG }], source: 'page' },
      variants: {
        state: 'observed',
        items: [
          {
            sku: 'V1',
            shade: { state: 'observed', text: 'Ruby' },
            gtin: { state: 'not_published', barcode: null },
          },
        ],
      },
      sizes: [{ productId: 'p2', size: { unit: 'ml', value: '100' }, sizeLabel: null }],
    });
    for (const f of ['images', 'variants', 'otherSizes'] as const)
      expect(whyMissing(f, o, [], undefined)).toBeNull();
    const empty = content({
      images: { state: 'not_published', items: [], source: null },
      variants: { state: 'not_published', items: [] },
    });
    expect(whyMissing('images', empty, [], undefined)).toEqual({ state: 'notPublished', reason: 'noImages' });
    expect(whyMissing('variants', empty, [], undefined)).toEqual({
      state: 'notPublished',
      reason: 'noVariants',
    });
    // Content captured, no sibling in the family: none, not a gap in collection.
    expect(whyMissing('otherSizes', empty, [], undefined)).toEqual({ state: 'none', reason: 'noOtherSizes' });
  });

  it('images a dataset does not collect are not collected; an observed but empty gallery is not shown', () => {
    expect(whyMissing('images', full, [], { images: false })?.reason).toBe('notCollected');
    const hollow = content({ images: { state: 'observed', items: [], source: null } });
    expect(whyMissing('images', hollow, [], undefined)?.reason).toBe('contentNotCaptured');
  });

  it('an offer the latest crawl did not see reads not seen for its content too', () => {
    const carried = { ...full, availability: 'not_observed' as const };
    expect(whyMissing('images', carried, [], undefined)?.reason).toBe('notObserved');
    expect(whyMissing('member', carried, [], undefined)?.reason).toBe('notObserved');
  });

  it('every reason it can give is worded in both languages', () => {
    for (const m of [en, ar])
      for (const r of ['memberNotCollected', 'contentNotCaptured', 'noImages', 'noVariants', 'noOtherSizes'])
        expect((m.product.why as Record<string, string>)[r]).toBeTruthy();
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
