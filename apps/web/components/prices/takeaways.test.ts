import { describe, expect, it } from 'vitest';
import { summaryBody } from '@/e2e/summary-fixture';
import { golden } from '@/lib/api/golden';
import type { Summary } from '@/lib/api/summary';
import type { Schemas } from '@/lib/api/types';
import { brandTakeaway, gapTakeaway, histTakeaway, ladderTakeaway } from './takeaways';

const s = summaryBody.data as Summary;
const cmp = (golden('compare') as { data: Schemas['Comparison'] }).data;

describe('Prices takeaways', () => {
  it('names the fullest price band and its share of every product in the histogram', () => {
    const t = histTakeaway(s.priceHist)!;
    expect(t).toMatchObject({ lo: '50', hi: '100', count: 1140, total: 4812 });
    expect(t.share).toBeCloseTo(1140 / 4812, 6);
    expect(histTakeaway(null)).toBeNull();
    expect(histTakeaway({ edges: ['0', '50'], counts: [0] })).toBeNull();
  });

  it('spans the ladder from the lowest category median to the highest', () => {
    const t = ladderTakeaway(s.ladder)!;
    expect(t.low).toEqual({ category: s.ladder![0]!.category, median: s.ladder![0]!.p50 });
    expect(t.high.category).toBe(s.ladder!.at(-1)!.category);
    expect(ladderTakeaway(null)).toBeNull();
    expect(ladderTakeaway(s.ladder!.slice(0, 1))).toBeNull();
  });

  it('ranks only the brands the chart draws: the largest `top`, with a usable median', () => {
    const t = brandTakeaway(s.brandPrice, 5)!;
    expect(t.n).toBe(5);
    const five = s.brandPrice!.slice(0, 5).map((b) => Number(b.median.amount));
    expect(Number(t.high.median.amount)).toBe(Math.max(...five));
    expect(Number(t.low.median.amount)).toBe(Math.min(...five));
    const all = brandTakeaway(s.brandPrice, 20)!;
    expect(all.n).toBe(Math.min(20, s.brandPrice!.length));
    expect(brandTakeaway(null, 10)).toBeNull();
    expect(
      brandTakeaway([{ brand: 'x', n: 1, median: { amount: '0.00', currency: 'AED', minor: 0 } }], 10),
    ).toBeNull();
  });

  it('splits the matched pairs by the sign of their gap band', () => {
    // Golden: edges -50..50, counts [0,0,0,1,1,1,1,0,1,1,0]: two bands below zero, one astride it, three above.
    const t = gapTakeaway(cmp.summary!.gapHist)!;
    expect(t.n).toBe(6);
    expect(t.dearer).toBeCloseTo(3 / 6, 6);
    expect(t.cheaper).toBeCloseTo(2 / 6, 6);
    expect(t.same).toBeCloseTo(1 / 6, 6);
    expect(gapTakeaway(null)).toBeNull();
    expect(gapTakeaway({ edges: ['0'], counts: [0, 0] })).toBeNull();
    // A body whose counts do not fit its edges is not drawn, so it has no takeaway either.
    expect(gapTakeaway({ edges: ['0'], counts: [1] })).toBeNull();
  });
});
