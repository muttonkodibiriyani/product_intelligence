import { describe, expect, it } from 'vitest';
import { EMPTY_COMPARE, parseCompare, pick, toCompareQuery, toCompareSearch } from './compare';

const parse = (q: string) => parseCompare(new URLSearchParams(q));

describe('compare URL state', () => {
  it('round-trips a full view and leaves defaults out', () => {
    const q = '?retailers=shop_a%2Cshop_b&groupBy=brand&brand=The+Ordinary&category=serum&limit=500';
    expect(toCompareSearch(parse(q))).toBe(q);
    expect(toCompareSearch(EMPTY_COMPARE)).toBe('');
    expect(toCompareSearch(parse('limit=100'))).toBe('');
  });

  it('drops what the API would refuse', () => {
    for (const q of [
      'retailers=shop_a',
      'retailers=shop_a,shop_a',
      'retailers=a,b,c',
      'retailers=A%20B,b',
      'retailers=1shop,shop_b',
      'retailers=shop-a,shop_b',
    ])
      expect(parse(q)).toMatchObject({ base: '', other: '' });
    expect(parse('groupBy=retailer').groupBy).toBeNull();
    expect(parse('limit=1000').limit).toBe(100);
    expect(parse(`brand=${'x'.repeat(121)}&brand=a&brand=a`).brand).toEqual(['a']);
  });

  it('asks the API with the pair, base first, and the limit', () => {
    expect(toCompareQuery(parse('retailers=shop_b,shop_a&brand=x'))).toEqual({
      retailers: 'shop_b,shop_a',
      brand: ['x'],
      limit: 100,
    });
  });

  it('swaps the sides when a side is set to the other retailer', () => {
    const s = { ...EMPTY_COMPARE, base: 'shop_a', other: 'shop_b' };
    expect(pick(s, 'base', 'shop_b')).toMatchObject({ base: 'shop_b', other: 'shop_a' });
    expect(pick(s, 'other', 'shop_c')).toMatchObject({ base: 'shop_a', other: 'shop_c' });
  });
});
