import { describe, expect, it } from 'vitest';
import {
  amount,
  brandShare,
  bandFloor,
  categoryNodeHref,
  categoryNodes,
  exploreHref,
  freshness,
  hasParents,
  heatCells,
  histBins,
  imageHost,
  imageSrc,
  importedOn,
  ladderRows,
  pct,
  promotions,
  promotionsHref,
  ratingPoints,
  WITHHELD_REASONS,
} from './model';
import type { CaveatView } from '@/lib/api/types';

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
    const m = (amount: string) => ({ amount, currency: 'AED', minor: 0 });
    const row = { category: 'A', n: 3, min: m('10'), p25: m('20'), p50: m('30'), p75: m('40'), max: m('50') };
    expect(
      ladderRows([row, { ...row, category: 'B', min: m('0') }, { ...row, category: 'C', p50: m('x') }]),
    ).toHaveLength(1);
    expect(ladderRows(null)).toEqual([]);
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

  it('orders category paths by count, named by their last step, and drops empty ones', () => {
    expect(
      categoryNodes([
        { category: ['Makeup'], n: 13 },
        { category: ['Skincare', 'Serum'], n: 20 },
        { category: ['Gifts'], n: 0 },
        { category: [], n: 3 },
      ]),
    ).toEqual([
      { name: 'Serum', trail: ['Skincare', 'Serum'], value: 20 },
      { name: 'Makeup', trail: ['Makeup'], value: 13 },
    ]);
    expect(categoryNodes(null)).toEqual([]);
  });

  it('drills a tile into its category code, the first step of its path, never the leaf', () => {
    const [serum] = categoryNodes([{ category: ['Skincare', 'Serum'], n: 20 }]);
    expect(categoryNodeHref('en', serum!)).toBe('/en/explore/?category=Skincare');
    const [lips] = categoryNodes([{ category: ['Makeup', 'Lips', 'Liquid Lipstick'], n: 4 }]);
    expect(categoryNodeHref('ar', lips!)).toBe('/ar/explore/?category=Makeup');
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
        sampled: false,
        scale: '5',
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

  it('matches the exact hostname, each retailer on its own host', () => {
    const ulta = 'https://media.alshaya.com/p/1.jpg';
    expect(imageSrc(ulta)).toBe(ulta);
    expect(imageSrc(ulta, 'ulta_ae')).toBe(ulta);
    expect(imageHost(ulta, 'ulta_ae')).toBe('media.alshaya.com');
    expect(imageSrc(ulta, 'sephora_me')).toBeNull();
    expect(imageSrc('https://img-product.sephora.me/a.jpg', 'ulta_ae')).toBeNull();
    expect(imageSrc('https://img-product.sephora.me/a.jpg', 'sephora_me')).not.toBeNull();
    expect(imageSrc('https://img-product.sephora.me.evil.example/a.jpg')).toBeNull();
    expect(imageSrc('https://media.alshaya.com.evil.example/a.jpg')).toBeNull();
    expect(imageSrc('https://x.media.alshaya.com/a.jpg')).toBeNull();
    expect(imageSrc('https://u:p@media.alshaya.com/a.jpg')).toBeNull();
    expect(imageSrc('https://media.alshaya.com/a.jpg', 'other')).toBeNull();
  });

  it('never guesses freshness', () => {
    expect(freshness({ cutoff: '2026-09-30', ageDays: 1, status: 'fresh' })).toBe('fresh');
    expect(freshness({ cutoff: '2026-09-28', ageDays: 3, status: 'aging' })).toBe('aging');
    expect(freshness({ cutoff: '2026-09-01', ageDays: 30, status: 'stale' })).toBe('stale');
    // A status newer than this build reads as unknown, not as fresh.
    expect(freshness({ cutoff: '2026-09-01', ageDays: 30, status: 'odd' as 'stale' })).toBe('unknown');
  });
});

const aed = (amount: string) => ({ amount, currency: 'AED', minor: 0 });

describe('brandShare', () => {
  it('ranks brands by products and keeps a running share of the whole catalogue', () => {
    const rows = brandShare(
      [
        { brand: 'B', n: 10, median: aed('50') },
        { brand: 'A', n: 30, median: aed('90') },
        { brand: 'C', n: 0, median: aed('10') },
      ],
      200,
    );
    expect(rows.map((r) => [r.brand, r.share, r.cum])).toEqual([
      ['A', 15, 15],
      ['B', 5, 20],
    ]);
    expect(brandShare([{ brand: 'A', n: 1, median: aed('1') }], 0)).toEqual([]);
    // Withheld: no brands, or no priced count.
    expect(brandShare(null, 200)).toEqual([]);
    expect(brandShare([{ brand: 'A', n: 1, median: aed('1') }], null)).toEqual([]);
  });
});

describe('imported retailers (API 1.5.0)', () => {
  const cav = (code: string, params: Record<string, string>) =>
    ({ code, params, en: '', ar: '' }) as unknown as CaveatView;
  const caveats = [
    cav('was_price_unverified', { retailer: 'ulta_ae' }),
    cav('snapshot_import_date', { retailer: 'ulta_ae', date: '2026-09-30' }),
    cav('parent_listings_included', { retailer: 'ulta_ae' }),
  ];

  it('rates a snapshot as a snapshot, never fresh however recent', () => {
    expect(freshness({ cutoff: '2026-10-01', ageDays: 0, status: 'snapshot' })).toBe('snapshot');
  });

  it("reads the import date and parent listings from the retailer's own caveats only", () => {
    expect(importedOn(caveats, 'ulta_ae')).toBe('2026-09-30');
    expect(importedOn(caveats, 'sephora_me')).toBeNull();
    expect(importedOn([], 'ulta_ae')).toBeNull();
    // A malformed date is no date: the caller falls back to the API's cutoff, still as an import.
    expect(
      importedOn([cav('snapshot_import_date', { retailer: 'ulta_ae', date: 'soon' })], 'ulta_ae'),
    ).toBeNull();
    expect(hasParents(caveats, 'ulta_ae')).toBe(true);
    expect(hasParents(caveats, 'sephora_me')).toBe(false);
  });

  it('words a was-price withholding instead of reading it as 0%', () => {
    const p = promotions({
      withheld: [{ section: 'promotions', reason: 'was_price_unverified' }],
      promoSharePct: null,
      promoDepth: null,
      topDiscounts: null,
    } as unknown as Parameters<typeof promotions>[0]);
    expect(p).toEqual({ measured: false, reason: 'was_price_unverified' });
    expect(WITHHELD_REASONS).toContain('was_price_unverified');
  });
});
