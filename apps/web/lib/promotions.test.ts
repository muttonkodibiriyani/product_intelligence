import { describe, expect, it } from 'vitest';
import {
  deepestCut,
  EMPTY_PROMOTIONS,
  listable,
  listedItems,
  notMeasured,
  parsePromotions,
  pickedShop,
  shareWidth,
  toPromotionsExportQuery,
  toPromotionsQuery,
  toPromotionsSearch,
} from './promotions';

const parse = (q: string) => parsePromotions(new URLSearchParams(q));

describe('promotions URL state', () => {
  it('round-trips a full view and leaves defaults out', () => {
    const q = '?retailer=shop_a&retailer=shop_c&brand=The+Ordinary&minPct=20&limit=500';
    expect(toPromotionsSearch(parse(q))).toBe(q);
    expect(toPromotionsSearch(EMPTY_PROMOTIONS)).toBe('');
  });

  it('drops values the picker does not offer or the API would refuse', () => {
    expect(parse('minPct=15').minPct).toBe('');
    expect(parse('minPct=-5').minPct).toBe('');
    expect(parse('retailer=Shop%20A&retailer=shop_b').retailer).toEqual(['shop_b']);
    expect(parse('limit=7').limit).toBe(100);
  });

  it('asks only for what is set, always with a limit', () => {
    expect(toPromotionsQuery(EMPTY_PROMOTIONS)).toEqual({ limit: 100 });
    expect(toPromotionsQuery(parse('retailer=shop_a&minPct=10'))).toEqual({
      retailer: ['shop_a'],
      minPct: '10',
      limit: 100,
    });
  });
});

describe('promotions export', () => {
  it('carries the list’s filters and the format, never a limit', () => {
    expect(toPromotionsExportQuery(EMPTY_PROMOTIONS, 'csv')).toEqual({ format: 'csv' });
    expect(toPromotionsExportQuery(parse('retailer=shop_a&minPct=20&brand=X&limit=500'), 'jsonl')).toEqual({
      retailer: ['shop_a'],
      minPct: '20',
      brand: ['X'],
      format: 'jsonl',
    });
  });
});

describe('shop tiles from the API’s rows', () => {
  const items = [
    { retailer: 'shop_a', depthPct: '20.4' },
    { retailer: 'shop_b', depthPct: '45.0' },
    { retailer: 'shop_a', depthPct: '33.3' },
    { retailer: 'shop_a', depthPct: 'n/a' },
  ];

  it('deepest cut: the shop’s own deepest row as written, or null when it has none', () => {
    expect(deepestCut(items, 'shop_a')).toBe('33.3');
    expect(deepestCut(items, 'shop_b')).toBe('45.0');
    expect(deepestCut(items, 'shop_c')).toBeNull();
    expect(deepestCut([], 'shop_a')).toBeNull();
  });

  it('a share becomes a bar width only when it is a number, clamped to 100', () => {
    expect(shareWidth('18.4')).toBe(18.4);
    expect(shareWidth('0.0')).toBe(0);
    expect(shareWidth('120')).toBe(100);
    expect(shareWidth(null)).toBeNull();
    expect(shareWidth('many')).toBeNull();
  });

  it('names the shop from the user’s pick, never from the rows', () => {
    expect(pickedShop({ retailer: ['shop_a'] })).toBe('shop_a');
    expect(pickedShop({ retailer: [] })).toBeNull();
    expect(pickedShop({ retailer: ['shop_a', 'shop_b'] })).toBeNull();
  });

  it('tells "not measured" from "no discounts": a reason only when nothing shown has a share', () => {
    const a = { retailer: 'shop_a', n: 10, share: '50.0', reason: null } as const;
    const c = { retailer: 'shop_c', n: 0, share: null, reason: 'retailer_partial' } as const;
    const d = { retailer: 'shop_d', n: 9, share: null, reason: 'was_price_unverified' } as const;
    // Something measured: an empty list is a real "no discounts".
    expect(notMeasured({ reason: 'retailer_partial', data: { retailers: [a, c] } }, null)).toBeNull();
    // The picked shop decides for itself.
    expect(notMeasured({ reason: null, data: { retailers: [a, d] } }, 'shop_d')).toBe('was_price_unverified');
    expect(notMeasured({ reason: 'retailer_partial', data: { retailers: [a, c] } }, 'shop_a')).toBeNull();
    // Nothing measured at all: the envelope's reason, else the first shop's, else the field one.
    expect(notMeasured({ reason: 'capability_off', data: { retailers: [] } }, null)).toBe('capability_off');
    expect(notMeasured({ reason: null, data: { retailers: [c, d] } }, null)).toBe('retailer_partial');
    expect(notMeasured({ reason: null, data: null }, null)).toBe('field_not_collected');
    expect(notMeasured({ reason: null, data: null }, 'shop_a')).toBe('field_not_collected');
  });

  it('lists a shop whose share alone is withheld: partly covered or a small cohort, with prices seen', () => {
    const partial = { retailer: 'ulta_ae', n: 7234, share: null, reason: 'retailer_partial' } as const;
    const small = { retailer: 'faces_ae', n: 3, share: null, reason: 'cohort_too_small' } as const;
    const unseen = { retailer: 'sephora_me', n: 0, share: null, reason: 'retailer_partial' } as const;
    const unverified = { retailer: 'shop_d', n: 9, share: null, reason: 'was_price_unverified' } as const;
    expect(listable(partial)).toBe(true);
    expect(listable(small)).toBe(true);
    // No offer had both prices: nothing was measured, so an empty list is not "no discounts".
    expect(listable(unseen)).toBe(false);
    expect(listable(unverified)).toBe(false);
    // Every live shop partly covered: the list shows; the picked unmeasured shop still says why.
    expect(
      notMeasured({ reason: 'retailer_partial', data: { retailers: [partial, unseen] } }, null),
    ).toBeNull();
    expect(
      notMeasured({ reason: 'retailer_partial', data: { retailers: [partial, unseen] } }, 'ulta_ae'),
    ).toBeNull();
    expect(
      notMeasured({ reason: 'retailer_partial', data: { retailers: [partial, unseen] } }, 'sephora_me'),
    ).toBe('retailer_partial');
    expect(notMeasured({ reason: null, data: { retailers: [unverified] } }, null)).toBe(
      'was_price_unverified',
    );
  });

  it('lists only listable shops’ rows; the total is unknown when a capped list lost rows', () => {
    const partial = { retailer: 'shop_a', n: 50, share: null, reason: 'retailer_partial' as const };
    const blocked = { retailer: 'shop_b', n: 40, share: null, reason: 'retailer_blocked' as const };
    const [a1, b1, a2] = [{ retailer: 'shop_a' }, { retailer: 'shop_b' }, { retailer: 'shop_a' }];
    const rows = [a1, b1, a2];
    const base = { retailers: [partial, blocked], items: rows, total: 3, truncated: false };
    expect(listedItems(base)).toEqual({ items: [a1, a2], total: 2 });
    expect(listedItems({ ...base, total: 90, truncated: true })).toEqual({
      items: [a1, a2],
      total: null,
    });
    const all = { ...base, retailers: [partial], items: [a1], total: 90, truncated: true };
    expect(listedItems(all)).toEqual({ items: [a1], total: 90 });
  });
});
