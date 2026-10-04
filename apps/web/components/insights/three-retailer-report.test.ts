import { describe, expect, it } from 'vitest';
import { threeRetailerPairs } from './three-retailer-report';

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
});
