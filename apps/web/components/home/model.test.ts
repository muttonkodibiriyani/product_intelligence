import { describe, expect, it } from 'vitest';
import { THIN, categoryCompareData } from '@/e2e/category-compare-fixture';
import { parseCategoryCompare } from '@/lib/api/category-compare';
import { golden } from '@/lib/api/golden';
import type { CaveatView, Schemas } from '@/lib/api/types';
import {
  abs,
  bucketCheaper,
  categoryRead,
  deepestCut,
  earlyExcluded,
  gapWidth,
  minus,
  share,
  sign,
  verdict,
  widestGap,
} from './model';

const compareBody = golden('compare') as { data: Schemas['Comparison']; caveats: CaveatView[] };
const compare = compareBody.data;
const buckets = parseCategoryCompare(categoryCompareData('shop_a', 'shop_b', THIN))!.buckets;

describe('verdict', () => {
  it('reads the leader, the trailing count and the equal count from the API counts', () => {
    expect(verdict(compare.summary!, 'shop_a', 'shop_b')).toEqual({
      kind: 'lead',
      leader: 'base',
      k: 3,
      trailing: 2,
      equal: 1,
      n: 6,
    });
  });
  it('a tie and all-same are their own kinds', () => {
    const s = compare.summary!;
    expect(verdict({ ...s, cheaperCounts: { shop_a: 2, shop_b: 2 } }, 'shop_a', 'shop_b').kind).toBe('tie');
    expect(verdict({ ...s, cheaperCounts: {} }, 'shop_a', 'shop_b')).toEqual({ kind: 'allSame', n: 6 });
  });
});

describe('categoryRead', () => {
  it('counts the compared buckets by the cheaper side, the too-few one left out', () => {
    expect(categoryRead(buckets, 'shop_a', 'shop_b')).toEqual({ compared: 8, base: 2, other: 5, same: 1 });
  });
  it('a bucket the API called same is same even with a non-zero gap; otherwise the sign decides', () => {
    const eyes = buckets.find((b) => b.key === 'eyes')!;
    expect(bucketCheaper(eyes, 'shop_a', 'shop_b')).toBe('same');
    expect(bucketCheaper({ ...eyes, cheaper: null, gapPct: '-0.8' }, 'shop_a', 'shop_b')).toBe('shop_b');
    expect(bucketCheaper({ ...eyes, cheaper: null, gapPct: '0.0' }, 'shop_a', 'shop_b')).toBe('same');
    expect(
      bucketCheaper(
        buckets.find((b) => b.key === 'concealer')!,
        'shop_a',
        'shop_b',
      ),
    ).toBeNull();
  });
});

describe('money and bars', () => {
  it('minus works on minor units and keeps the decimals of the amount', () => {
    expect(
      minus(
        { amount: '600.00', currency: 'AED', minor: 60000 },
        { amount: '580.75', currency: 'AED', minor: 58075 },
      ),
    ).toEqual({
      amount: '19.25',
      currency: 'AED',
      minor: 1925,
    });
    expect(
      minus({ amount: '0.50', currency: 'AED', minor: 50 }, { amount: '1.00', currency: 'AED', minor: 100 }),
    ).toEqual({
      amount: '-0.50',
      currency: 'AED',
      minor: -50,
    });
    expect(abs({ amount: '-0.50', currency: 'AED', minor: -50 })).toEqual({
      amount: '0.50',
      currency: 'AED',
      minor: 50,
    });
    expect(
      minus({ amount: '1', currency: 'USD', minor: 100 }, { amount: '1', currency: 'AED', minor: 100 }),
    ).toBeNull();
  });
  it('sign reads the API decimal strings', () => {
    expect(sign('2.4')).toBe(1);
    expect(sign('-0.8')).toBe(-1);
    expect(sign('0.0')).toBe(0);
    expect(sign('n/a')).toBe(0);
  });
  it('share and gapWidth scale against the widest value and never exceed their bar', () => {
    expect(share(50, 200)).toBe(25);
    expect(share(0, 200)).toBe(0);
    expect(share(5, 0)).toBe(0);
    // Concealer (−13.6%) is too few in the fixture, so body (−10.9%) is the widest gap compared.
    expect(widestGap(buckets)).toBe(10.9);
    expect(gapWidth('-10.9', 10.9)).toBe(50);
    expect(gapWidth('5.45', 10.9)).toBe(25);
    expect(gapWidth('0', 10.9)).toBe(0);
  });
  it('deepestCut picks the largest depth as sent', () => {
    expect(deepestCut([{ depthPct: '44.4' }, { depthPct: '50.0' }, { depthPct: 'x' }])).toBe('50.0');
    expect(deepestCut([])).toBeNull();
  });
});

describe('earlyExcluded', () => {
  const cav = (count: string): CaveatView => ({ code: 'early_excluded', en: '', ar: '', params: { count } });
  it('reads the count from the API caveat only; total above n is not "early"', () => {
    expect(earlyExcluded(compareBody.caveats)).toEqual({ count: 1, caveat: compareBody.caveats[0] });
    expect(compare.total).toBeGreaterThan(compare.summary!.n);
    expect(earlyExcluded([])).toBeNull();
    expect(earlyExcluded(undefined)).toBeNull();
    expect(earlyExcluded([{ ...cav('1'), code: 'retailer_partial' }])).toBeNull();
  });
  it('a zero or unreadable count is not early either', () => {
    expect(earlyExcluded([cav('0')])).toBeNull();
    expect(earlyExcluded([cav('')])).toBeNull();
    expect(earlyExcluded([cav('many')])).toBeNull();
    expect(earlyExcluded([cav('12')])?.count).toBe(12);
  });
});
