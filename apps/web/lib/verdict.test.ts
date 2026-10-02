import { describe, expect, it } from 'vitest';
import type { Schemas } from './api/types';
import { gapBar, gapScale, verdictOf } from './verdict';

const aed = (amount: string) => ({ amount, currency: 'AED', minor: Math.round(+amount * 100) });
const pair = (over: Partial<Schemas['PairGap']> = {}): Schemas['PairGap'] => ({
  base: 'a',
  other: 'b',
  gap: { amount: aed('20.00'), cheaper: 'base', pct: '25.0' },
  excludedReason: null,
  sizeLabels: null,
  ...over,
});
const prices = { a: aed('80.00'), b: aed('100.00') };

describe('verdictOf', () => {
  it('nothing without a pair, or when the product is not sold at both shops', () => {
    expect(verdictOf({ gap: null, prices })).toBeNull();
    expect(
      verdictOf({ gap: pair({ gap: null, excludedReason: 'not_offered' }), prices: { a: aed('1') } }),
    ).toBeNull();
  });

  it("names the other shop as dearer or cheaper by the API's percentage of the base price, sign dropped", () => {
    // base 80 vs other 100: the other shop is 25% dearer (not the base 25% cheaper; that is 20%).
    expect(verdictOf({ gap: pair(), prices })).toEqual({ kind: 'dearer', retailer: 'b', pct: '25.0' });
    // base 50 vs other 150: 200% dearer, where "base cheaper 200%" would be nonsense (it is 66.7%).
    expect(
      verdictOf({
        gap: pair({ gap: { amount: aed('100.00'), cheaper: 'base', pct: '200.0' } }),
        prices: { a: aed('50.00'), b: aed('150.00') },
      }),
    ).toEqual({ kind: 'dearer', retailer: 'b', pct: '200.0' });
    expect(
      verdictOf({ gap: pair({ gap: { amount: aed('-5.00'), cheaper: 'other', pct: '-4.2' } }), prices }),
    ).toEqual({ kind: 'cheaper', retailer: 'b', pct: '4.2' });
    expect(
      verdictOf({ gap: pair({ gap: { amount: aed('0.00'), cheaper: 'equal', pct: '0.0' } }), prices }),
    ).toEqual({
      kind: 'same',
    });
  });

  it('a withheld price on either side is "review" before anything else', () => {
    expect(verdictOf({ gap: pair(), prices: { a: aed('0.01'), b: aed('100.00') } })).toEqual({
      kind: 'review',
    });
    expect(
      verdictOf({ gap: pair(), prices: { a: null, b: aed('100.00') }, priceFlags: { a: 'invalid_low' } }),
    ).toEqual({
      kind: 'review',
    });
  });

  it('size reasons are "sizes"; any other exclusion keeps its reason', () => {
    expect(verdictOf({ gap: pair({ gap: null, excludedReason: 'size_mismatch' }), prices })).toEqual({
      kind: 'sizes',
    });
    expect(verdictOf({ gap: pair({ gap: null, excludedReason: 'size_unknown' }), prices })).toEqual({
      kind: 'sizes',
    });
    expect(verdictOf({ gap: pair({ gap: null, excludedReason: 'match_unreviewed' }), prices })).toEqual({
      kind: 'excluded',
      reason: 'match_unreviewed',
    });
  });
});

describe('gap bars', () => {
  it('scale is the largest |pct| in the list, at least 1', () => {
    expect(gapScale([])).toBe(1);
    expect(
      gapScale([
        { gap: null },
        { gap: pair() },
        { gap: pair({ gap: { amount: aed('1'), cheaper: 'other', pct: '-40.0' } }) },
      ]),
    ).toBe(40);
  });

  it('base cheaper fills the good side, base dearer the bad side, by |pct| against the scale', () => {
    expect(gapBar({ amount: aed('20.00'), cheaper: 'base', pct: '25.0' }, 50)).toEqual({
      side: 'good',
      width: 25,
    });
    expect(gapBar({ amount: aed('-5.00'), cheaper: 'other', pct: '-4.2' }, 25)).toEqual({
      side: 'bad',
      width: 8.4,
    });
    expect(gapBar({ amount: aed('99'), cheaper: 'base', pct: '80' }, 40)).toEqual({
      side: 'good',
      width: 50,
    });
    expect(gapBar({ amount: aed('0'), cheaper: 'equal', pct: '0.0' }, 40)).toBeNull();
  });
});
