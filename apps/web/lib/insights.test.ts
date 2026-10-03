import { describe, expect, it } from 'vitest';
import {
  allObservedOut,
  apiAtLeast,
  insightsServed,
  barPct,
  deepestUndercut,
  forPair,
  gapScale,
  policyColumns,
  sizesInOrder,
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

  it('"all observed out" needs at least one observed listing and every one out', () => {
    expect(allObservedOut({ brand: 'x', observed: 113, outOfStock: 113 })).toBe(true);
    expect(allObservedOut({ brand: 'x', observed: 12, outOfStock: 6 })).toBe(false);
    expect(allObservedOut({ brand: 'x', observed: 0, outOfStock: 0 })).toBe(false);
  });

  it('keeps only the pair, in pair order, whatever order the API sent', () => {
    const rows = [{ retailer: 'c' }, { retailer: 'b' }, { retailer: 'a' }];
    expect(forPair(rows, 'a', 'b').map((r) => r.retailer)).toEqual(['a', 'b']);
  });

  it('compares API versions per number, not as text', () => {
    expect(apiAtLeast('1.17.0', '1.17.0')).toBe(true);
    expect(apiAtLeast('1.16.0', '1.17.0')).toBe(false);
    expect(apiAtLeast('1.9.9', '1.17.0')).toBe(false);
    expect(apiAtLeast('2.0', '1.17.0')).toBe(true);
    expect(apiAtLeast('garbage', '1.17.0')).toBe(false);
  });

  it('Insights is served from API 1.17.0; unknown until /meta answers', () => {
    expect(insightsServed({ meta: { apiVersion: '1.16.0' } })).toBe(false);
    expect(insightsServed({ meta: { apiVersion: '1.17.0' } })).toBe(true);
    expect(insightsServed(undefined)).toBeUndefined();
  });
});
