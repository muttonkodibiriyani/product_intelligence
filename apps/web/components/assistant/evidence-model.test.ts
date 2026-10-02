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

describe('sourceLink', () => {
  it('compare: the pair, grouping and filters in the compare URL', () => {
    const link = sourceLink(
      cite('compare', {
        retailers: { base: 'ulta_ae', other: 'sephora_me' },
        groupBy: 'brand',
        brand: ['Dior'],
        limit: 25,
      }),
      'ar',
    );
    expect(link).toEqual({
      page: 'compare',
      href: '/ar/compare/?retailers=ulta_ae%2Csephora_me&groupBy=brand&brand=Dior',
      retailers: ['ulta_ae', 'sephora_me'],
      brand: ['Dior'],
      category: [],
      groupBy: 'brand',
    });
  });
  it('category_compare groups by category; index_trend opens Prices', () => {
    const pair = { retailers: { base: 'ulta_ae', other: 'sephora_me' } };
    expect(sourceLink(cite('category_compare', pair), 'en')?.href).toBe(
      '/en/compare/?retailers=ulta_ae%2Csephora_me&groupBy=category',
    );
    expect(sourceLink(cite('index_trend', pair), 'en')?.href).toBe('/en/prices/');
  });
  it('promotions: shops, depth and filters; an off-list depth is dropped', () => {
    expect(
      sourceLink(cite('promotions', { retailer: ['ulta_ae'], minPct: 30, category: ['makeup'] }), 'en')?.href,
    ).toBe('/en/promotions/?retailer=ulta_ae&category=makeup&minPct=30');
    expect(sourceLink(cite('promotions', { minPct: 15 }), 'en')?.href).toBe('/en/promotions/');
  });
  it('search: the query and filters on Products; get_product: the product', () => {
    expect(
      sourceLink(
        cite('search_products', { q: 'foundation', matched: true, retailer: ['ulta_ae'], priceMax: '200' }),
        'en',
      )?.href,
    ).toBe('/en/explore/?q=foundation&retailer=ulta_ae&matched=true&priceMax=200');
    expect(sourceLink(cite('get_product', { id: 'p 1' }), 'en')?.href).toBe('/en/product/?id=p%201');
    expect(
      sourceLink(cite('assortment_gaps', { presentAt: 'ulta_ae', missingAt: 'sephora_me' }), 'en'),
    ).toMatchObject({
      page: 'explore',
      href: '/en/explore/?retailer=ulta_ae',
      retailers: ['ulta_ae'],
    });
  });
  it('tools without a page link nowhere', () => {
    expect(sourceLink(cite('something_new'), 'en')).toBeNull();
    expect(sourceLink(cite('coverage_status'), 'en')?.href).toBe('/en/dataset/');
    expect(sourceLink(cite('launches', { retailer: ['ulta_ae'] }), 'en')).toMatchObject({
      href: '/en/launches/',
      retailers: ['ulta_ae'],
    });
  });
});
