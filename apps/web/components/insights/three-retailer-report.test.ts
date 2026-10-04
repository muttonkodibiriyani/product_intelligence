import { describe, expect, it } from 'vitest';
import { pairEvidence, threeRetailerPairs } from './three-retailer-report';

describe('threeRetailerPairs', () => {
  it('creates each unordered pair once, preserving retailer order', () => {
    expect(threeRetailerPairs(['ulta_ae', 'sephora_me', 'faces_ae'])).toEqual([
      { base: 'ulta_ae', other: 'sephora_me' },
      { base: 'ulta_ae', other: 'faces_ae' },
      { base: 'sephora_me', other: 'faces_ae' },
    ]);
  });

  it('does not manufacture a report from fewer than three retailers', () => {
    expect(threeRetailerPairs(['ulta_ae', 'sephora_me'])).toHaveLength(1);
    expect(threeRetailerPairs([])).toEqual([]);
  });

  it('keeps missing or withheld metrics out of numeric displays', () => {
    expect(pairEvidence(undefined)).toEqual({ matched: null, unreviewed: null, counted: false });
    expect(
      pairEvidence({
        status: 'not_enough_data',
        n: 0,
        unreviewed: 0,
        base: 'a',
        other: 'b',
        reason: 'cohort_too_small',
        sizes: [],
        brands: [],
        suppressedBrands: 0,
        suppressedSizes: 0,
      }),
    ).toEqual({ matched: null, unreviewed: 0, counted: false });
  });
});
