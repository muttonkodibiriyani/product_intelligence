import { describe, expect, it } from 'vitest';
import { EMPTY_PROMOTIONS, parsePromotions, toPromotionsQuery, toPromotionsSearch } from './promotions';

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
