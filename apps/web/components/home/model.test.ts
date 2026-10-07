import { describe, expect, it } from 'vitest';
import { THIN, categoryCompareData, compareGroups } from '@/e2e/category-compare-fixture';
import { parseCategoryCompare } from '@/lib/api/category-compare';
import { golden } from '@/lib/api/golden';
import type { CaveatView, Schemas } from '@/lib/api/types';
import {
  abs,
  bucketCheaper,
  categoryLines,
  deepestCut,
  depthBands,
  earlyExcluded,
  launchTotals,
  leadingBand,
  matchedRead,
  gapWidth,
  minus,
  peakDay,
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

describe('categoryLines and matchedRead', () => {
  const groups = compareGroups('shop_a', 'shop_b', {
    concealer: [4, 3, 0],
    lips: [2, 6, 0],
    cheek: 2,
  }) as Schemas['Group'][];
  it('shows a category with a range gap or a summarised matched group, ranked by the gap', () => {
    const { shown, thin } = categoryLines(buckets, groups);
    // Concealer has no gap (too few) but its matched pairs are summarised, so it shows, last.
    expect(shown.map((l) => l.key)).toHaveLength(9);
    expect(shown[shown.length - 1]!.key).toBe('concealer');
    expect(thin).toEqual([]);
    const lone = categoryLines(buckets, []);
    expect(lone.thin.map((l) => l.key)).toEqual(['concealer']);
    expect(categoryLines([], groups).shown.map((l) => l.key)).toEqual(['lips', 'concealer']);
    expect(categoryLines([], [{ ...groups[0]!, key: 'shoes' }]).shown).toEqual([]);
  });
  it('the title read counts categories by the shop cheaper on more matched pairs; thin groups left out', () => {
    const { shown } = categoryLines(buckets, groups);
    expect(matchedRead(shown, 'shop_a', 'shop_b')).toEqual({ compared: 2, base: 1, other: 1 });
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

describe('depth bands and launch days', () => {
  const depth = {
    bands: ['10-20', '20-30', '50+'],
    cells: [
      [4, 1, 0],
      [2, 3, 0],
      [0, 0, 0],
    ],
  };
  it('depthBands sums each band over the categories, in the API order, with the total', () => {
    expect(depthBands(depth)).toEqual({
      bands: [
        { band: '10-20', n: 6 },
        { band: '20-30', n: 4 },
        { band: '50+', n: 0 },
      ],
      total: 10,
    });
    expect(depthBands({ bands: ['10-20'], cells: [] })).toEqual({
      bands: [{ band: '10-20', n: 0 }],
      total: 0,
    });
  });
  it('leadingBand says "most" only past half, "largest" for a plurality, and names no band on a tie', () => {
    // 6 of 10: more than half.
    expect(leadingBand(depth)).toEqual({ kind: 'most', band: '10-20', n: 6, total: 10 });
    // Exactly half is not "most".
    expect(leadingBand({ bands: ['a', 'b', 'c'], cells: [[2, 1, 1]] })).toEqual({
      kind: 'largest',
      band: 'a',
      n: 2,
      total: 4,
    });
    // A plurality: 3 of 7 leads, but is not most.
    expect(
      leadingBand({
        bands: ['a', 'b', 'c'],
        cells: [
          [1, 3, 1],
          [1, 0, 1],
        ],
      }),
    ).toEqual({
      kind: 'largest',
      band: 'b',
      n: 3,
      total: 7,
    });
    // A tie at the top, here between the last two bands: no band is named, first or otherwise.
    expect(leadingBand({ bands: ['a', 'b', 'c'], cells: [[1, 2, 2]] })).toEqual({ kind: 'tie', total: 5 });
    expect(leadingBand({ bands: ['10-20'], cells: [[0]] })).toBeNull();
  });
  it('leadingBand on the golden /summary depth (1 + 1 + 1 of 3) is a tie, never "most of 3"', () => {
    const s = golden('summary') as { data: { promoDepth: { bands: string[]; cells: number[][] } } };
    expect(leadingBand(s.data.promoDepth)).toEqual({ kind: 'tie', total: 3 });
  });
  it('launchTotals sums only the shops with complete dates, and says when that is not all of them', () => {
    const d = (date: string, n: number) => ({ date, n });
    const a = { name: 'Shop A', perDay: [d('2026-09-29', 2), d('2026-09-30', 0)] };
    const b = { name: 'Shop B', perDay: [d('2026-09-29', 1), d('2026-09-30', 4)] };
    expect(launchTotals(2, [a, b])).toEqual({
      total: 7,
      peak: d('2026-09-30', 4),
      covered: ['Shop A', 'Shop B'],
      partial: false,
    });
    // Shop B's list was truncated (perDay null), so it is not in the series: the total is Shop A's
    // alone and says so.
    expect(launchTotals(2, [a])).toEqual({
      total: 2,
      peak: d('2026-09-29', 2),
      covered: ['Shop A'],
      partial: true,
    });
  });
  it('peakDay is the busiest day, the first on a tie, or null with no launch', () => {
    const d = (date: string, n: number) => ({ date, n });
    expect(peakDay([d('2026-09-01', 0), d('2026-09-02', 3), d('2026-09-03', 3)])).toEqual(d('2026-09-02', 3));
    expect(peakDay([d('2026-09-01', 0)])).toBeNull();
    expect(peakDay([])).toBeNull();
  });
});
