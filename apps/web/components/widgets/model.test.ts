import { describe, expect, it } from 'vitest';
import {
  activeRetailers,
  amount,
  brandShare,
  bandFloor,
  cheaperCells,
  cheaperShares,
  crossCells,
  compareHref,
  gapRows,
  scopedCaveats,
  trendPoints,
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

describe('head-to-head helpers', () => {
  const cav = (code: string, params: Record<string, string>) =>
    ({ code, params, en: '', ar: '' }) as unknown as CaveatView;

  it('drops a caveat about a retailer outside the request (API < 1.5.2 does not scope them)', () => {
    const own = cav('parent_listings_included', { retailer: 'sephora_me' });
    const foreign = cav('snapshot_import_date', { retailer: 'ulta_ae', date: '2026-09-30' });
    const global = cav('early_excluded', { count: '1' });
    expect(scopedCaveats([own, foreign, global], ['sephora_me'])).toEqual([own, global]);
    expect(scopedCaveats([own, foreign, global], ['sephora_me', 'ulta_ae'])).toHaveLength(3);
  });

  it('reports only collected or partly collected retailers', () => {
    const r = (id: string, status: string) => ({ id, status }) as never;
    expect(
      activeRetailers({
        retailers: [r('a', 'supported'), r('b', 'blocked'), r('c', 'partial'), r('d', 'pending')],
      }),
    ).toEqual(['a', 'c']);
    expect(activeRetailers(null)).toEqual([]);
  });

  it('draws a trend only when the API says so and two days carry an index', () => {
    const pt = (date: string, index: string | null) => ({ date, index, n: 7, reason: null });
    expect(trendPoints(null)).toBeNull();
    expect(
      trendPoints({ trendAvailable: false, points: [pt('2026-09-28', '98.0'), pt('2026-09-29', '99.0')] }),
    ).toBeNull();
    expect(trendPoints({ trendAvailable: true, points: [pt('2026-09-28', '98.0')] })).toBeNull();
    expect(
      trendPoints({ trendAvailable: true, points: [pt('2026-09-28', '98.0'), pt('2026-09-29', null)] }),
    ).toBeNull();
    expect(
      trendPoints({
        trendAvailable: true,
        points: [pt('2026-09-28', '98.0'), pt('2026-09-29', null), pt('2026-09-30', '103.3')],
      }),
    ).toHaveLength(2);
  });

  it('plots only counted pairs with two real prices, widest gap first', () => {
    const aed = (amount: string) => ({ amount, currency: 'AED', minor: Math.round(Number(amount) * 100) });
    const row = (id: string, base: string, other: string, pct: string, counted = true) =>
      ({
        id,
        name: id,
        brand: 'B',
        category: ['c'],
        counted,
        excludedReason: null,
        basePrice: aed(base),
        otherPrice: aed(other),
        gap: { amount: aed('0.00'), pct, cheaper: 'equal' },
      }) as never;
    const rows = gapRows([
      row('small', '100.00', '102.00', '2.0'),
      row('placeholder', '0.01', '100.00', '999.0'),
      row('big', '100.00', '80.00', '-20.0'),
      row('excluded', '100.00', '50.00', '-50.0', false),
    ]);
    expect(rows.map((r) => r.id)).toEqual(['big', 'small']);
  });

  it('turns group summaries into heatmap cells and keeps thin groups apart', () => {
    const g = (key: string, a: number, eq: number, b: number) => ({
      key,
      n: a + eq + b,
      status: 'ok',
      reason: null,
      summary: {
        n: a + eq + b,
        cheaperCounts: { a, b },
        equalCount: eq,
        medianGapPct: '0',
        meanGapPct: '0',
        basket: {},
      },
    });
    const thin = { key: 'thin', n: 2, status: 'not_enough_data', reason: 'cohort_too_small', summary: null };
    const out = cheaperCells([g('lips', 3, 1, 2), thin, g('skin', 0, 0, 5)] as never, 'a', 'b');
    expect(out.rows.map((r) => r.key)).toEqual(['lips', 'skin']);
    expect(out.thin.map((r) => r.key)).toEqual(['thin']);
    expect(out.cells).toEqual([
      [0, 0, 3],
      [1, 0, 1],
      [2, 0, 2],
      [0, 1, 0],
      [1, 1, 0],
      [2, 1, 5],
    ]);
    expect(out.max).toBe(5);
  });

  it('builds the category × brand grid from counted pairs and marks thin cells, never 0', () => {
    const aed = (amount: string) => ({ amount, currency: 'AED', minor: Math.round(Number(amount) * 100) });
    const row = (
      i: number,
      category: string,
      brand: string,
      cheaper: 'base' | 'other' | 'equal',
      counted = true,
    ) =>
      ({
        id: `p${i}`,
        name: `p${i}`,
        brand,
        category: [category, 'leaf'],
        counted,
        excludedReason: counted ? null : 'no_match',
        basePrice: aed('100.00'),
        otherPrice: aed(cheaper === 'base' ? '110.00' : cheaper === 'other' ? '90.00' : '100.00'),
        gap: { amount: aed('0.00'), pct: '0', cheaper },
      }) as never;
    const rows = [
      ...Array.from({ length: 5 }, (_, i) => row(i, 'Skincare', 'Acme', i < 4 ? 'base' : 'other')),
      row(10, 'Skincare', 'Zed', 'other'),
      row(11, 'Skincare', 'Zed', 'equal'),
      row(12, 'Makeup', 'Acme', 'other'),
      row(13, 'Makeup', 'Acme', 'other', false),
    ];
    const out = crossCells(rows, { min: 5 });
    expect(out.cats).toEqual(['Skincare', 'Makeup']);
    expect(out.brands).toEqual(['Acme', 'Zed']);
    expect(out.pairs).toBe(8);
    const full = out.cells.find((c) => c.row === 0 && c.col === 0)!;
    expect(full).toMatchObject({ n: 5, baseWins: 4, otherWins: 1, equal: 0, value: 0.6 });
    const thin = out.cells.find((c) => c.row === 0 && c.col === 1)!;
    expect(thin).toMatchObject({ n: 2, value: null });
    expect(out.cells.find((c) => c.row === 1 && c.col === 1)).toBeUndefined();
    expect(out.thin).toBe(2);
    // The busiest rows and columns only.
    expect(crossCells(rows, { min: 5, maxRows: 1, maxCols: 1 }).cells).toHaveLength(1);
  });

  it('turns group summaries into cheaper shares, base-heavy first, and skips thin groups', () => {
    const g = (key: string, a: number, eq: number, b: number) => ({
      key,
      n: a + eq + b,
      status: 'ok',
      reason: null,
      summary: {
        n: a + eq + b,
        cheaperCounts: { a, b },
        equalCount: eq,
        medianGapPct: '0',
        meanGapPct: '0',
        basket: {},
      },
    });
    const thin = { key: 'thin', n: 2, status: 'not_enough_data', reason: 'cohort_too_small', summary: null };
    const out = cheaperShares([g('lips', 1, 1, 2), thin, g('skin', 3, 0, 1)] as never, 'a', 'b');
    expect(out.map((r) => r.key)).toEqual(['skin', 'lips']);
    expect(out[0]).toMatchObject({ n: 4, base: 0.75, same: 0, other: 0.25, baseN: 3, sameN: 0, otherN: 1 });
  });

  it('links a group to the comparison narrowed to it', () => {
    expect(compareHref('en', { base: 'a', other: 'b', groupBy: 'category', category: 'lips' })).toBe(
      '/en/compare/?retailers=a%2Cb&groupBy=category&category=lips',
    );
  });
});
