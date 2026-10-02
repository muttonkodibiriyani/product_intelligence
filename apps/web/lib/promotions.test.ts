import { describe, expect, it } from 'vitest';
import {
  deepestCut,
  EMPTY_PROMOTIONS,
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
    const a = { retailer: 'shop_a', share: '50.0', reason: null } as const;
    const c = { retailer: 'shop_c', share: null, reason: 'retailer_partial' } as const;
    const d = { retailer: 'shop_d', share: null, reason: 'was_price_unverified' } as const;
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
});
