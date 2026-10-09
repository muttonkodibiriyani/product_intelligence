import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CaveatView, Schemas } from './api/types';
import {
  calendarDay,
  cellState,
  EVIDENCE_STATES,
  filterGaps,
  freshnessOf,
  missingFields,
  sourceFreshness,
  type SourceFreshness,
} from './source-freshness';

type Source = Schemas['SourceInfo'];
type Retailer = Schemas['RetailerView'];

const CAPS: Schemas['Capabilities'] = {
  campaigns: false,
  coverage: false,
  history: false,
  images: true,
  promotions: true,
  ratings: false,
  shades: false,
  sizes: true,
  stock: true,
};

const source = (id: string, lastDate: string, products: number, fields: Source['fields'] = {}): Source => ({
  source: id,
  lastDate,
  products,
  fields,
  cutoff: `${lastDate}T00:00:00Z`,
  generatedAt: `${lastDate}T00:00:00Z`,
  matchStage: 'first-pass',
  capabilities: CAPS,
});
const retailer = (id: string, status: Retailer['status'] = 'supported'): Retailer => ({
  id,
  name: id,
  country: 'AE',
  note: null,
  since: null,
  status,
});
const caveat = (code: CaveatView['code'], params: Record<string, string>): CaveatView => ({
  code,
  params,
  en: '',
  ar: '',
});

/**
 * The five saved sources as the accepted evidence has them: each retailer's own last observation
 * date, product count and declared field statuses (coverage packet manifest 42337037…, Ulta from
 * the canonical v2 review dataset 8a996969…). Aggregates only: no scraped text.
 */
const SAVED: Source[] = [
  source('bloomingdales_ae', '2026-10-08', 7694, {
    price: 'ok',
    regular: 'ok',
    stock: 'ok',
    size: 'partial',
    shades: 'not_collected',
    rating: 'not_collected',
    gtin: 'not_published',
    image: 'ok',
  }),
  source('faces_ae', '2026-10-03', 1457, {
    price: 'ok',
    regular: 'ok',
    stock: 'not_collected',
    size: 'partial',
    shades: 'not_collected',
    rating: 'not_collected',
    gtin: 'not_published',
    image: 'ok',
  }),
  source('ounass_ae', '2026-10-07', 32810, {
    price: 'ok',
    regular: 'ok',
    stock: 'ok',
    size: 'partial',
    shades: 'not_collected',
    rating: 'not_collected',
    gtin: 'not_published',
    image: 'ok',
  }),
  source('sephora_me', '2026-10-01', 9529, {
    gtin: 'not_published',
    image: 'partial',
    price: 'partial',
    rating: 'ok',
    regular: 'partial',
    shades: 'not_collected',
    size: 'partial',
    stock: 'ok',
  }),
  source('ulta_ae', '2026-10-09', 16868, {
    gtin: 'not_published',
    image: 'partial',
    price: 'partial',
    rating: 'ok',
    regular: 'partial',
    shades: 'not_collected',
    size: 'partial',
    stock: 'partial',
  }),
];
const IDS = ['bloomingdales_ae', 'faces_ae', 'ounass_ae', 'sephora_me', 'ulta_ae'];
const VIEW_DATES = ['2026-10-01', '2026-10-03', '2026-10-07', '2026-10-08', '2026-10-09'];
const savedMeta = { dates: VIEW_DATES, retailers: IDS.map((id) => retailer(id)), sources: SAVED };

afterEach(() => vi.useRealTimers());

describe('sourceFreshness on the saved five-retailer evidence', () => {
  it('dates each retailer by its own last observation against the view, keeping every product', () => {
    const out = sourceFreshness(savedMeta, [
      caveat('snapshot_import_date', { retailer: 'ulta_ae', date: '2026-10-09' }),
    ]);
    expect(out.map((s) => [s.retailer, s.state, s.lastDate])).toEqual([
      ['bloomingdales_ae', 'stale', '2026-10-08'],
      ['faces_ae', 'stale', '2026-10-03'],
      ['ounass_ae', 'stale', '2026-10-07'],
      ['sephora_me', 'stale', '2026-10-01'],
      ['ulta_ae', 'fresh', '2026-10-09'],
    ]);
    // Every source's product count passes through unchanged: 68,358 saved rows, none dropped.
    expect(out.map((s) => s.products)).toEqual([7694, 1457, 32810, 9529, 16868]);
    expect(out.reduce((a, s) => a + (s.products ?? 0), 0)).toBe(68358);
    expect(out.every((s) => s.viewDate === '2026-10-09')).toBe(true);
    // An imported source is "latest in this dataset" with its import date, never "captured today".
    expect(out[4]!.importedOn).toBe('2026-10-09');
    expect(out[0]!.fields).toEqual({ ok: 4, partial: 1, not_collected: 2, not_published: 1 });
  });

  it('never reads the wall clock: 2020 and 2040 give the same states', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2020-01-01T00:00:00Z'));
    const early = sourceFreshness(savedMeta);
    vi.setSystemTime(new Date('2040-12-31T23:59:59Z'));
    expect(sourceFreshness(savedMeta)).toEqual(early);
  });

  it('is fresh only on the view date: a source dated the view is fresh whatever its age', () => {
    const out = sourceFreshness({ ...savedMeta, dates: ['2026-10-01'], sources: [SAVED[3]!] });
    expect(freshnessOf(out, 'sephora_me').state).toBe('fresh');
  });
});

describe('sourceFreshness states', () => {
  const meta = (sources: Source[], retailers = IDS.map((id) => retailer(id)), dates = VIEW_DATES) => ({
    dates,
    retailers,
    sources,
  });

  it('marks blocked, pending and retired retailers unavailable even with data', () => {
    for (const status of ['blocked', 'pending', 'retired'] as const) {
      const out = sourceFreshness(meta(SAVED, [retailer('ulta_ae', status)]));
      expect(freshnessOf(out, 'ulta_ae').state).toBe('unavailable');
      expect(freshnessOf(out, 'ulta_ae').status).toBe(status);
    }
  });

  it('keeps partial retailers in their date state with the status beside it', () => {
    const out = sourceFreshness(meta(SAVED, [retailer('faces_ae', 'partial')]));
    expect(freshnessOf(out, 'faces_ae')).toMatchObject({ state: 'stale', status: 'partial' });
  });

  it('lists a retailer with no source as not_observed, with no borrowed date or count', () => {
    const out = sourceFreshness(meta(SAVED.slice(0, 4)));
    expect(freshnessOf(out, 'ulta_ae')).toMatchObject({
      state: 'not_observed',
      lastDate: null,
      products: null,
    });
    // A retailer the dataset never names at all is not_observed too.
    expect(freshnessOf(out, 'unknown_ae').state).toBe('not_observed');
  });

  it('matches by exact id only: an alias never takes another retailer source', () => {
    const out = sourceFreshness(meta(SAVED, [retailer('sephora_ae')]));
    expect(freshnessOf(out, 'sephora_ae').state).toBe('not_observed');
    expect(freshnessOf(out, 'sephora_me').lastDate).toBe('2026-10-01');
  });

  it('reports two different last dates for one retailer as a conflict, using neither', () => {
    const out = sourceFreshness(
      meta([source('faces_ae', '2026-10-03', 1), source('faces_ae', '2026-10-09', 2)]),
    );
    expect(freshnessOf(out, 'faces_ae')).toMatchObject({ state: 'conflict', lastDate: null, products: null });
  });

  it('reports a stale_source caveat that disagrees with the source date as a conflict', () => {
    const out = sourceFreshness(meta(SAVED), [
      caveat('stale_source', { retailer: 'ounass_ae', asOf: '2026-10-01' }),
    ]);
    expect(freshnessOf(out, 'ounass_ae').state).toBe('conflict');
  });

  it('honours a matching stale_source caveat, and one for a retailer with no source', () => {
    const out = sourceFreshness(meta([source('ulta_ae', '2026-10-09', 1)], [retailer('ulta_ae')]), [
      caveat('stale_source', { retailer: 'ulta_ae', asOf: '2026-10-09' }),
      caveat('stale_source', { retailer: 'faces_ae', asOf: '2026-10-03' }),
    ]);
    expect(freshnessOf(out, 'ulta_ae').state).toBe('stale');
    expect(freshnessOf(out, 'faces_ae')).toMatchObject({ state: 'stale', lastDate: null });
  });

  it('fails closed as invalid on malformed, rollover or future-of-view dates, or no view date', () => {
    for (const bad of ['2026-10-32', '2026-02-30', '10/09/2026', '', '2026-10-10']) {
      const out = sourceFreshness(meta([source('ulta_ae', bad, 1)], [retailer('ulta_ae')]));
      expect(freshnessOf(out, 'ulta_ae').state, bad).toBe('invalid');
    }
    const out = sourceFreshness(meta([source('ulta_ae', '2026-10-09', 1)], [retailer('ulta_ae')], []));
    expect(freshnessOf(out, 'ulta_ae').state).toBe('invalid');
  });

  it('never produces a state outside the six', () => {
    const out = sourceFreshness(meta(SAVED));
    expect(out.every((s) => EVIDENCE_STATES.includes(s.state))).toBe(true);
  });

  it('accepts only real calendar days', () => {
    expect(calendarDay('2026-10-09')).toBe('2026-10-09');
    expect(calendarDay('2026-02-29')).toBeNull();
    expect(calendarDay(20261009)).toBeNull();
  });
});

describe('cellState', () => {
  const fresh: SourceFreshness = freshnessOf(sourceFreshness(savedMeta), 'ulta_ae');
  const stale: SourceFreshness = freshnessOf(sourceFreshness(savedMeta), 'faces_ae');
  const aed = { amount: '43.00', currency: 'AED', minor: 4300 } as Schemas['MoneyValue'];

  it('says no offer was observed, never out of stock, when the list has none for the retailer', () => {
    expect(cellState({ prices: {} }, fresh)).toBe('no_offer');
  });
  it('says no price was observed when the offer has no price on the read date', () => {
    expect(cellState({ prices: { ulta_ae: null } }, fresh)).toBe('no_price');
    expect(cellState({ prices: { faces_ae: null } }, stale)).toBe('no_price');
  });
  it('keeps an invalid price invalid whatever the source state', () => {
    expect(cellState({ prices: { ulta_ae: aed }, priceFlags: { ulta_ae: 'invalid_low' } }, fresh)).toBe(
      'invalid',
    );
  });
  it('takes the retailer own source state for a priced cell', () => {
    expect(cellState({ prices: { ulta_ae: aed } }, fresh)).toBe('fresh');
    expect(cellState({ prices: { faces_ae: aed } }, stale)).toBe('stale');
  });
  it('never reads another retailer price', () => {
    expect(cellState({ prices: { ulta_ae: aed } }, stale)).toBe('no_offer');
  });
});

describe('missingFields and filterGaps', () => {
  it('names every absent field and keeps the row', () => {
    const card = { brand: ' ', name: '', category: [], image: null, size: null, prices: { a: null } };
    expect(missingFields(card)).toEqual(['brand', 'name', 'category', 'image', 'size', 'price']);
    const full = {
      brand: 'B',
      name: 'N',
      category: ['c'],
      image: 'https://x/y.jpg',
      size: { value: '50', unit: 'ml' } as Schemas['Size'],
      prices: { a: { amount: '1.00', currency: 'AED', minor: 100 } as Schemas['MoneyValue'] },
    };
    expect(missingFields(full)).toEqual([]);
  });

  it('names the missing-data products each active server filter cannot match', () => {
    const none = { brand: [], category: [], priceMin: '', priceMax: '', availability: [] };
    expect(filterGaps(none)).toEqual([]);
    expect(
      filterGaps({ brand: ['B'], category: ['c'], priceMin: '', priceMax: '10', availability: ['in_stock'] }),
    ).toEqual(['brand', 'category', 'price', 'availability']);
  });
});
