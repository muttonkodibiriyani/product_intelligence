import { describe, expect, it } from 'vitest';
import {
  amount,
  brandShare,
  bandFloor,
  categoryNodes,
  exploreHref,
  freshness,
  heatCells,
  histBins,
  imageSrc,
  ladderRows,
  pct,
  promotions,
  promotionsHref,
  ratingPoints,
} from './model';

describe('widget model', () => {
  it('formats amounts and percentages with Latin digits in both languages', () => {
    expect(amount('129.50', 'AED', 'en')).toMatch(/129\.50/);
    expect(amount('129.50', 'AED', 'ar')).toMatch(/129[.,٫]50/);
    expect(amount('129.50', 'AED', 'en', true)).toMatch(/130|129/);
    expect(amount('n/a', 'AED', 'en')).toBe('n/a');
    expect(pct('23.4', 'en')).toBe('23.4%');
    expect(pct(null, 'en')).toBe('–');
  });

  it('links marks to the lists they count', () => {
    expect(exploreHref('en', { category: ['Lipstick'] })).toBe('/en/explore/?category=Lipstick');
    expect(exploreHref('ar', {})).toBe('/ar/explore/');
    expect(promotionsHref('en', { category: 'Skincare', minPct: '20' })).toBe(
      '/en/promotions/?category=Skincare&minPct=20',
    );
    // A band floor the promotions picker doesn't offer drops to "any discount".
    expect(promotionsHref('en', { category: 'Skincare', minPct: '15' })).toBe(
      '/en/promotions/?category=Skincare',
    );
    expect(bandFloor('20-30%')).toBe('20');
    expect(bandFloor('50+')).toBe('50');
    expect(bandFloor('other')).toBe('');
  });

  it('drops ladder rows a log axis cannot place', () => {
    const row = { category: 'A', n: 3, min: '10', p25: '20', p50: '30', p75: '40', max: '50' };
    expect(
      ladderRows([row, { ...row, category: 'B', min: '0' }, { ...row, category: 'C', p50: 'x' }]),
    ).toHaveLength(1);
  });

  it('builds heatmap cells and their maximum, treating missing cells as zero', () => {
    const { cells, max } = heatCells({
      category: ['a', 'b'],
      bands: ['10-20', '20-30'],
      cells: [[1, 4], [2]],
    });
    expect(cells).toEqual([
      [0, 0, 1],
      [1, 0, 4],
      [0, 1, 2],
      [1, 1, 0],
    ]);
    expect(max).toBe(4);
  });

  it('orders categories by count and drops empty ones', () => {
    expect(
      categoryNodes([
        { category: 'Makeup', n: 13 },
        { category: 'Skincare', n: 20 },
        { category: 'Gifts', n: 0 },
        { category: '', n: 3 },
      ]),
    ).toEqual([
      { name: 'Skincare', value: 20 },
      { name: 'Makeup', value: 13 },
    ]);
  });

  it('keeps promotions off unless measured, with the reason /summary gives', () => {
    const none = { promoSharePct: null, promoDepth: null, topDiscounts: null };
    expect(promotions({ ...none, withheld: [{ section: 'promotions', reason: 'capability_off' }] })).toEqual({
      measured: false,
      reason: 'capability_off',
    });
    expect(promotions({ ...none, withheld: [] })).toEqual({ measured: false, reason: 'field_not_collected' });
    const depth = { category: ['A'], bands: ['10-20'], cells: [[1]] };
    expect(promotions({ promoSharePct: '4.0', promoDepth: depth, topDiscounts: [], withheld: [] })).toEqual({
      measured: true,
      share: '4.0',
      depth,
      top: [],
    });
    // Withheld wins even if a field slipped through.
    expect(
      promotions({
        promoSharePct: '4.0',
        promoDepth: depth,
        topDiscounts: [],
        withheld: [{ section: 'promotions', reason: 'cohort_too_small' }],
      }).measured,
    ).toBe(false);
  });

  it('pairs histogram counts with their edges', () => {
    expect(histBins({ edges: ['0', '50', '100'], counts: [3, 4, 9] })).toEqual([
      { lo: '0', hi: '50', count: 3 },
      { lo: '50', hi: '100', count: 4 },
    ]);
  });

  it('keeps placeable rating points only', () => {
    expect(
      ratingPoints({
        n: 3,
        ratedPct: '66.7',
        points: [
          { price: '100', rating: '4.5', count: 12 },
          { price: '0', rating: '4', count: 1 },
          { price: '50', rating: '', count: 1 },
        ],
      }),
    ).toEqual([[100, 4.5, 12]]);
  });

  it('accepts images from the retailer image host over https only', () => {
    expect(imageSrc('https://img-product.sephora.me/a.jpg')).toBe('https://img-product.sephora.me/a.jpg');
    expect(imageSrc('http://img-product.sephora.me/a.jpg')).toBeNull();
    expect(imageSrc('https://evil.example/img-product.sephora.me.jpg')).toBeNull();
    expect(imageSrc('javascript:alert(1)')).toBeNull();
    expect(imageSrc(null)).toBeNull();
  });

  it('never guesses freshness', () => {
    expect(freshness({ cutoff: '2026-09-30', ageDays: 1, status: 'fresh' })).toBe('fresh');
    expect(freshness({ cutoff: '2026-09-28', ageDays: 3, status: 'aging' })).toBe('aging');
    expect(freshness({ cutoff: '2026-09-01', ageDays: 30, status: 'stale' })).toBe('stale');
    expect(freshness({ cutoff: '2026-09-01', ageDays: 30, status: 'odd' })).toBe('unknown');
  });
});

describe('brandShare', () => {
  it('ranks brands by products and keeps a running share of the whole catalogue', () => {
    const rows = brandShare(
      [
        { brand: 'B', n: 10, median: '50' },
        { brand: 'A', n: 30, median: '90' },
        { brand: 'C', n: 0, median: '10' },
      ],
      200,
    );
    expect(rows.map((r) => [r.brand, r.share, r.cum])).toEqual([
      ['A', 15, 15],
      ['B', 5, 20],
    ]);
    expect(brandShare([{ brand: 'A', n: 1, median: '1' }], 0)).toEqual([]);
  });
});
