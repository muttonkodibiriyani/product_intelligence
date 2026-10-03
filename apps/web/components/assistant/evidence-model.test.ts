import { describe, expect, it } from 'vitest';
import {
  evidenceCards,
  evidenceShares,
  evidenceTotal,
  MAX_CARDS,
  sourceLink,
  toMoney,
} from './evidence-model';
import type { Citation, ToolEnvelope } from '@/lib/assistant/types';

const u = (s: string) => ({ untrusted: s });
const cite = (tool: string, filters: Record<string, unknown> = {}): Citation => ({
  tool,
  toolVersion: '1',
  apiVersion: '1.11.0',
  metricVersion: 'm1',
  datasetGeneration: 'g7',
  cutoff: '2026-09-30T00:00:00Z',
  market: 'uae',
  currency: 'AED',
  filters,
  cohort: null,
});
const env = (tool: string, data: ToolEnvelope['data'], filters?: Record<string, unknown>): ToolEnvelope => ({
  status: 'ok',
  citation: cite(tool, filters),
  caveats: [],
  data,
});

describe('toMoney', () => {
  it('rebuilds minor from the exact decimal text the sanitiser kept', () => {
    expect(toMoney({ amount: '215.00', currency: 'AED' })).toEqual({
      amount: '215.00',
      currency: 'AED',
      minor: 21500,
    });
    expect(toMoney({ amount: '12.345', currency: 'KWD' })).toEqual({
      amount: '12.345',
      currency: 'KWD',
      minor: 12345,
    });
  });
  it('refuses anything that is not a money record', () => {
    expect(toMoney(null)).toBeNull();
    expect(toMoney({ amount: 'free', currency: 'AED' })).toBeNull();
    expect(toMoney(u('215.00'))).toBeNull();
    expect(toMoney({ amount: '1.00' })).toBeNull();
  });
});

describe('evidenceCards', () => {
  it('search results: one line per shop from the prices map, not-sold for a shop without one', () => {
    const [card] = evidenceCards(
      env('search_products', {
        items: [
          {
            id: 'p05',
            name: u('Serum'),
            brand: u('Fixture Beauty'),
            category: [u('skincare'), u('serum')],
            size: { value: '50', unit: 'ml' },
            prices: { ulta_ae: { amount: '80.00', currency: 'AED' }, sephora_me: null },
            priceFlags: { sephora_me: 'invalid_low' },
            gap: {
              base: 'ulta_ae',
              other: 'sephora_me',
              excludedReason: null,
              gap: null,
              sizeLabels: ['50 ml', '30 ml'],
            },
            matches: [],
          },
        ],
        total: 1,
      }),
    );
    expect(card).toMatchObject({
      id: 'p05',
      name: 'Serum',
      brand: 'Fixture Beauty',
      category: 'skincare',
      size: { value: '50', unit: 'ml' },
      verdict: { kind: 'review' },
    });
    expect(card!.lines).toEqual([
      {
        retailer: 'ulta_ae',
        price: { amount: '80.00', currency: 'AED', minor: 8000 },
        priceFlag: undefined,
        notSold: false,
        size: '50 ml',
      },
      { retailer: 'sephora_me', price: null, priceFlag: 'invalid_low', notSold: false, size: '30 ml' },
    ]);
  });

  it('get_product: the card; other tools: nothing', () => {
    const data = {
      card: {
        id: 'p1',
        name: u('One'),
        brand: u('B'),
        category: [],
        size: null,
        prices: { ulta_ae: { amount: '5.00', currency: 'AED' } },
        matches: [],
      },
    };
    expect(evidenceCards(env('get_product', data))).toHaveLength(1);
    expect(evidenceCards(env('coverage_status', data))).toEqual([]);
    expect(evidenceCards(env('compare', { rows: [{ id: 'x', name: u('x') }] }))).toEqual([]);
  });

  it('keeps at most MAX_CARDS and drops rows without an id or a name', () => {
    const rows = Array.from({ length: MAX_CARDS + 3 }, (_, i) => ({
      id: `p${i}`,
      name: i === 0 ? 7 : u(`Product ${i}`),
      basePrice: { amount: '1.00', currency: 'AED' },
      otherPrice: { amount: '2.00', currency: 'AED' },
      gap: { amount: { amount: '1.00', currency: 'AED' }, pct: '100.0', cheaper: 'base' },
    }));
    const cards = evidenceCards(
      env('compare', { base: 'ulta_ae', other: 'sephora_me', rows, total: rows.length }),
    );
    expect(cards).toHaveLength(MAX_CARDS);
    expect(cards[0]!.id).toBe('p1');
    expect(cards[0]!.verdict).toEqual({ kind: 'dearer', retailer: 'sephora_me', pct: '100.0' });
  });
});

describe('evidenceShares and evidenceTotal', () => {
  it('reads the promotions tool only, keeps null shares as not measured', () => {
    const e = env('promotions', {
      items: [],
      retailers: [
        { retailer: 'sephora_me', n: 10, onPromo: 2, share: '20.0', reason: null },
        { retailer: 'ulta_ae', n: 5, onPromo: 0, share: null, reason: 'was_price_unverified' },
        { retailer: 'x', n: 'many', onPromo: 0, share: '1.0', reason: null },
      ],
      total: 7,
    });
    expect(evidenceShares(e)).toEqual([
      { retailer: 'sephora_me', n: 10, onPromo: 2, share: '20.0', reason: null },
      { retailer: 'ulta_ae', n: 5, onPromo: 0, share: null, reason: 'was_price_unverified' },
    ]);
    expect(evidenceTotal(e)).toBe(7);
    expect(evidenceShares({ ...e, citation: cite('compare') })).toEqual([]);
    expect(evidenceTotal(env('compare', null))).toBeNull();
  });
});

/** A linked pill's target, as the page reads it: the path and every query pair, order-free. */
const parsed = (href: string) => {
  const u = new URL(href, 'http://pi.test');
  return { path: u.pathname, params: [...u.searchParams.entries()].sort() };
};
type Row = {
  tool: string;
  args: Record<string, unknown>;
  /** The page and the exact query the link carries; `null` when the pill must stay plain text. */
  link: { path: string; params: [string, string][] } | null;
};
const pairArg = { retailers: { base: 'ulta_ae', other: 'sephora_me' } };
const PAIR: [string, string] = ['retailers', 'ulta_ae,sephora_me'];

// One row per tool and argument combination: the link's query must equal the tool's arguments,
// and an argument the page cannot read means no link at all (never a broader page).
const TABLE: Row[] = [
  // search_products: Products reads every argument
  {
    tool: 'search_products',
    args: { q: 'foundation', retailer: ['ulta_ae'], matched: true, priceMax: '200', sort: 'name', limit: 10 },
    link: {
      path: '/en/explore/',
      params: [
        ['q', 'foundation'],
        ['retailer', 'ulta_ae'],
        ['matched', 'true'],
        ['priceMax', '200'],
      ],
    },
  },
  {
    tool: 'search_products',
    args: {
      brand: ['Dior', 'Huda Beauty'],
      category: ['makeup'],
      matched: false,
      priceMin: '50',
      sort: 'price_desc',
    },
    link: {
      path: '/en/explore/',
      params: [
        ['brand', 'Dior'],
        ['brand', 'Huda Beauty'],
        ['category', 'makeup'],
        ['matched', 'false'],
        ['priceMin', '50'],
        ['sort', 'price_desc'],
      ],
    },
  },
  { tool: 'search_products', args: {}, link: { path: '/en/explore/', params: [] } },
  // get_product: the product
  { tool: 'get_product', args: { id: 'p 1' }, link: { path: '/en/product/', params: [['id', 'p 1']] } },
  { tool: 'get_product', args: {}, link: null },
  // compare: pair, grouping, brand/category; never ids or a date
  {
    tool: 'compare',
    args: { ...pairArg, groupBy: 'brand', brand: ['Dior'], limit: 25 },
    link: { path: '/en/compare/', params: [PAIR, ['groupBy', 'brand'], ['brand', 'Dior']] },
  },
  {
    tool: 'compare',
    args: { ...pairArg, category: ['skincare', 'makeup'] },
    link: { path: '/en/compare/', params: [PAIR, ['category', 'skincare'], ['category', 'makeup']] },
  },
  { tool: 'compare', args: { ...pairArg, ids: ['p01', 'p02'] }, link: null },
  { tool: 'compare', args: { ...pairArg, date: '2026-09-29' }, link: null },
  { tool: 'compare', args: { brand: ['Dior'] }, link: null },
  // category_compare: Compare by category shows pair gaps, not the medians; never a page
  { tool: 'category_compare', args: pairArg, link: null },
  { tool: 'category_compare', args: { ...pairArg, level: 'bucket' }, link: null },
  { tool: 'category_compare', args: { ...pairArg, level: 'common' }, link: null },
  // index_trend: no page shows the index
  { tool: 'index_trend', args: pairArg, link: null },
  { tool: 'index_trend', args: { ...pairArg, brand: ['Dior'] }, link: null },
  { tool: 'index_trend', args: { ...pairArg, from: '2026-09-01', to: '2026-09-30' }, link: null },
  // promotions: shops, brand/category and the preset depths; never a date or an off-list depth
  {
    tool: 'promotions',
    args: { retailer: ['ulta_ae'], minPct: 30, category: ['makeup'], limit: 25 },
    link: {
      path: '/en/promotions/',
      params: [
        ['retailer', 'ulta_ae'],
        ['category', 'makeup'],
        ['minPct', '30'],
      ],
    },
  },
  { tool: 'promotions', args: {}, link: { path: '/en/promotions/', params: [] } },
  { tool: 'promotions', args: { minPct: 15 }, link: null },
  { tool: 'promotions', args: { retailer: ['sephora_me'], date: '2026-09-29' }, link: null },
  // assortment_gaps: Products cannot express "missing at one shop, present at the other"
  { tool: 'assortment_gaps', args: { presentAt: 'ulta_ae', missingAt: 'sephora_me' }, link: null },
  {
    tool: 'assortment_gaps',
    args: { presentAt: 'ulta_ae', missingAt: 'sephora_me', brand: ['Dior'] },
    link: null,
  },
  // launches: the page shows a preset window, the tool all history; never a page
  { tool: 'launches', args: {}, link: null },
  { tool: 'launches', args: { brand: ['Dior'], limit: 25 }, link: null },
  { tool: 'launches', args: { retailer: ['ulta_ae'] }, link: null },
  { tool: 'launches', args: { since: '2026-09-20' }, link: null },
  // reviews_summary: one id is the product; a list has no page; filters open Products
  {
    tool: 'reviews_summary',
    args: { ids: ['p01'] },
    link: { path: '/en/product/', params: [['id', 'p01']] },
  },
  { tool: 'reviews_summary', args: { ids: ['p01', 'p02'] }, link: null },
  {
    tool: 'reviews_summary',
    args: { brand: ['Dior'], retailer: ['ulta_ae', 'sephora_me'] },
    link: {
      path: '/en/explore/',
      params: [
        ['brand', 'Dior'],
        ['retailer', 'ulta_ae'],
        ['retailer', 'sephora_me'],
      ],
    },
  },
  // price_history: the product; a date window is not a page view
  { tool: 'price_history', args: { id: 'p01' }, link: { path: '/en/product/', params: [['id', 'p01']] } },
  { tool: 'price_history', args: { id: 'p01', from: '2026-09-01' }, link: null },
  // coverage_status: Dataset shows every shop
  { tool: 'coverage_status', args: {}, link: { path: '/en/dataset/', params: [] } },
  { tool: 'coverage_status', args: { retailer: ['ulta_ae'] }, link: null },
  // availability: no page shows stock
  { tool: 'availability', args: {}, link: null },
  { tool: 'availability', args: { retailer: ['ulta_ae'] }, link: null },
  // summary tools: Prices shows the named shop; the defaults of tool and page need not agree
  {
    tool: 'price_ladder',
    args: { retailer: 'ulta_ae' },
    link: { path: '/en/prices/', params: [['retailer', 'ulta_ae']] },
  },
  { tool: 'price_distribution', args: {}, link: null },
  {
    tool: 'brand_positioning',
    args: { retailer: 'sephora_me' },
    link: { path: '/en/prices/', params: [['retailer', 'sephora_me']] },
  },
  { tool: 'category_mix', args: { retailer: 'ulta_ae' }, link: null },
  { tool: 'assortment_breadth', args: {}, link: null },
  // a tool the app does not know
  { tool: 'something_new', args: { retailer: ['ulta_ae'] }, link: null },
];

describe('sourceLink', () => {
  it.each(TABLE.map((r) => [r.tool, JSON.stringify(r.args), r] as const))(
    '%s %s links exactly or not at all',
    (_tool, _args, row) => {
      const link = sourceLink(cite(row.tool, row.args), 'en');
      if (row.link === null) {
        expect(link.href).toBeNull();
      } else {
        expect(link.href).not.toBeNull();
        expect(parsed(link.href!)).toEqual({ path: row.link.path, params: [...row.link.params].sort() });
      }
    },
  );

  it('keeps the scope for the label whether or not the pill links', () => {
    expect(sourceLink(cite('compare', { ...pairArg, groupBy: 'brand', brand: ['Dior'] }), 'ar')).toEqual({
      page: 'compare',
      href: '/ar/compare/?retailers=ulta_ae%2Csephora_me&groupBy=brand&brand=Dior',
      retailers: ['ulta_ae', 'sephora_me'],
      brand: ['Dior'],
      category: [],
      groupBy: 'brand',
    });
    expect(sourceLink(cite('index_trend', { ...pairArg, brand: ['Dior'] }), 'en')).toMatchObject({
      page: null,
      href: null,
      retailers: ['ulta_ae', 'sephora_me'],
      brand: ['Dior'],
    });
    expect(sourceLink(cite('launches', { retailer: ['ulta_ae'], since: '2026-09-20' }), 'en')).toMatchObject({
      page: null,
      href: null,
      retailers: ['ulta_ae'],
    });
    expect(sourceLink(cite('category_compare', pairArg), 'en').groupBy).toBe('category');
  });

  it('the product link is URL-encoded', () => {
    expect(sourceLink(cite('get_product', { id: 'p 1' }), 'en').href).toBe('/en/product/?id=p%201');
  });
});
