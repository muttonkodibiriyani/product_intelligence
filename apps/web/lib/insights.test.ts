import { describe, expect, it } from 'vitest';
import {
  apiAtLeast,
  insightsServed,
  barPct,
  deepestUndercut,
  fewRated,
  gapScale,
  oncePerName,
  perUnitMedian,
  pickedShop,
  pickSize,
  policyColumns,
  ratingOutOfFive,
  shopPairs,
  sizesInOrder,
  valueCategories,
  type ValueCategory,
  type ValuePicks,
  type BrandPolicy,
  type SizeGap,
} from './insights';

const size = (
  value: string,
  medianGapPct: string,
  otherCheaper = 3,
  baseCheaper = 1,
  unit = 'ml',
): SizeGap => ({
  value,
  unit,
  medianGapPct,
  n: otherCheaper + baseCheaper,
  otherCheaper,
  baseCheaper,
  equal: 0,
});

describe('insights helpers', () => {
  it('orders sizes by unit, then by number, not by text', () => {
    const out = sizesInOrder([size('100', '1'), size('30', '1'), size('9', '1', 3, 1, 'g'), size('50', '1')]);
    expect(out.map((s) => `${s.value}${s.unit}`)).toEqual(['9g', '30ml', '50ml', '100ml']);
  });

  it('the deepest undercut is the most negative median where the other shop wins more pairs', () => {
    const sizes = [size('30', '-12', 1, 3), size('50', '-8'), size('100', '-4'), size('200', '3')];
    expect(deepestUndercut(sizes)?.value).toBe('50');
    expect(deepestUndercut([size('30', '2'), size('50', '-5', 1, 1)])).toBeNull();
  });

  it('groups brands by policy and keeps the API order inside a column', () => {
    const b = (brand: string, policy: BrandPolicy['policy']) => ({ brand, policy }) as BrandPolicy;
    const cols = policyColumns([
      b('A', 'parity'),
      b('B', 'other_cheaper'),
      b('C', 'parity'),
      b('D', 'mixed'),
    ]);
    expect(cols.parity.map((x) => x.brand)).toEqual(['A', 'C']);
    expect(cols.other_cheaper.map((x) => x.brand)).toEqual(['B']);
    expect(cols.mixed).toHaveLength(1);
    expect(cols.base_cheaper).toEqual([]);
  });

  it('scales diverging bars to the widest gap, never past the half', () => {
    expect(gapScale(['-8', '4'])).toBe(8);
    expect(gapScale(['0'])).toBe(1);
    expect(barPct('-4', 8)).toBe(50);
    expect(barPct('12', 8)).toBe(100);
    expect(barPct('3', 0)).toBe(0);
  });

  it('lists a product once per brand and name, ignoring case and spacing', () => {
    const rows = [
      { brand: 'Milani', name: 'Fruit Fetish Lip Oil', id: '1' },
      { brand: 'milani ', name: 'Fruit  Fetish lip oil', id: '2' },
      { brand: 'Milani', name: 'Color Statement Lipliner', id: '3' },
      { brand: 'NYX', name: 'Fruit Fetish Lip Oil', id: '4' },
    ];
    expect(oncePerName(rows).map((r) => r.id)).toEqual(['1', '3', '4']);
  });

  it('pairs every shop with every later one, once', () => {
    expect(shopPairs(['a', 'b', 'c'])).toEqual([
      { base: 'a', other: 'b' },
      { base: 'a', other: 'c' },
      { base: 'b', other: 'c' },
    ]);
    expect(shopPairs(['a'])).toEqual([]);
  });

  it('reads the picked shop only when the dataset collects it', () => {
    expect(pickedShop(new URLSearchParams('shop=b'), ['a', 'b'])).toBe('b');
    expect(pickedShop(new URLSearchParams('shop=zz'), ['a', 'b'])).toBeNull();
    expect(pickedShop(new URLSearchParams(''), ['a', 'b'])).toBeNull();
  });

  it('flags a category as few rated below a quarter of its priced listings', () => {
    expect(fewRated({ rated: 119, priced: 1805 })).toBe(true);
    expect(fewRated({ rated: 25, priced: 100 })).toBe(false);
    expect(fewRated({ rated: 24, priced: 100 })).toBe(true);
    expect(fewRated({ rated: 0, priced: 0 })).toBe(false);
  });

  it('drops the catch-all category from value picks', () => {
    const cat = (category: string) => ({ category }) as ValueCategory;
    const v = { categories: [cat('lips'), cat('other'), cat('eyes')] } as ValuePicks;
    expect(valueCategories(v).map((c) => c.category)).toEqual(['lips', 'eyes']);
  });

  it('reads the audit fields: a per-unit median, else the shelf price; a size and unit price together or neither', () => {
    const c = { category: 'fragrance', median: { amount: '310.00', currency: 'AED' } } as ValueCategory;
    expect(perUnitMedian(c)).toBeNull();
    expect(perUnitMedian({ ...c, basis: 'shelf' } as ValueCategory)).toBeNull();
    // Per unit with no unit median: no per-unit line, the shelf price shows instead.
    expect(perUnitMedian({ ...c, basis: 'per_unit', unitMedians: [] } as ValueCategory)).toBeNull();
    const unitMedians = [
      { median: '9.80', n: 12, unit: 'g' },
      { median: '3.10', n: 900, unit: 'ml' },
    ];
    expect(perUnitMedian({ ...c, basis: 'per_unit', unitMedians } as ValueCategory)).toEqual({
      median: { amount: '3.10', currency: 'AED' },
      unit: 'ml',
    });
    const p = { brand: 'b', id: '1', name: 'n', price: { amount: '515.00', currency: 'AED' } } as Parameters<
      typeof pickSize
    >[0];
    expect(pickSize(p)).toEqual({ size: null, unitPrice: null });
    // A unit price is shown only with the size it is per.
    expect(pickSize({ ...p, unitPrice: '5.15' } as typeof p)).toEqual({ size: null, unitPrice: null });
    expect(pickSize({ ...p, sizeValue: '100', sizeUnit: 'ml', unitPrice: '5.15' } as typeof p)).toEqual({
      size: { value: '100', unit: 'ml' },
      unitPrice: { amount: '5.15', currency: 'AED' },
    });
  });

  it('puts the rating floor on a five-point scale', () => {
    expect(ratingOutOfFive('90.0')).toBe('4.5');
    expect(ratingOutOfFive('80')).toBe('4');
  });

  it('compares API versions per number, not as text', () => {
    expect(apiAtLeast('1.18.0', '1.18.0')).toBe(true);
    expect(apiAtLeast('1.17.0', '1.18.0')).toBe(false);
    expect(apiAtLeast('1.9.9', '1.18.0')).toBe(false);
    expect(apiAtLeast('2.0', '1.18.0')).toBe(true);
    expect(apiAtLeast('garbage', '1.18.0')).toBe(false);
  });

  it('Insights is served from API 1.22.0; unknown until /meta answers', () => {
    expect(insightsServed({ meta: { apiVersion: '1.18.0' } })).toBe(false);
    expect(insightsServed({ meta: { apiVersion: '1.21.0' } })).toBe(false);
    expect(insightsServed({ meta: { apiVersion: '1.22.0' } })).toBe(true);
    expect(insightsServed(undefined)).toBeUndefined();
  });
});
