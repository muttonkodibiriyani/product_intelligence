import { describe, expect, it } from 'vitest';
import {
  EMPTY_LAUNCHES,
  launchesQueryKey,
  parseLaunches,
  parseWindow,
  toLaunchesQuery,
  toLaunchesSearch,
  windowEnd,
  windowSince,
} from './launches';

const parse = (q: string) => parseLaunches(new URLSearchParams(q));
const CUTOFF = '2026-09-30T00:00:00Z';
const DATES = ['2026-09-28', '2026-09-29', '2026-09-30'];

describe('launches URL state', () => {
  it('round-trips a full view and leaves defaults out', () => {
    const q = '?brand=The+Ordinary&category=Serum&days=7&limit=500';
    expect(toLaunchesSearch(parse(q))).toBe(q);
    expect(toLaunchesSearch(EMPTY_LAUNCHES)).toBe('');
    expect(toLaunchesSearch({ ...EMPTY_LAUNCHES, days: 30 })).toBe('');
  });

  it('round-trips every evidence filter and drops unknown evidence states', () => {
    const q =
      '?retailer=sephora_ae&brand=Evidence+Beauty&category=lips&availability=in_stock&evidence=stale' +
      '&dateFrom=2026-09-24&dateTo=2026-09-30&priceMin=25&priceMax=100.50&discountMin=10' +
      '&size=4+g&color=red&shade=rose';
    expect(toLaunchesSearch(parse(q))).toBe(q);
    expect(parse(`${q}&evidence=made_up`).evidence).toEqual(['stale']);
    expect(parse('dateFrom=yesterday&priceMin=-1&size=x'.repeat(121)).dateFrom).toBe('');
  });

  it('offers only the two windows, 30 days by default', () => {
    expect(parseWindow('7')).toBe(7);
    expect(parseWindow('30')).toBe(30);
    for (const v of ['14', '0', '-7', 'week', '', null]) expect(parseWindow(v)).toBe(30);
    expect(parse('since=2026-09-01&retailer=shop_a').days).toBe(30);
  });

  it('drops values the API would refuse', () => {
    expect(parse('limit=7').limit).toBe(100);
    expect(parse(`brand=${'x'.repeat(121)}&brand=ok`).brand).toEqual(['ok']);
  });

  it('ends the window on the last collection day, not the UTC date of the cutoff', () => {
    expect(windowEnd({ cutoff: CUTOFF, dates: DATES })).toBe('2026-09-30');
    // A run that finished after 20:00Z: the cutoff's UTC date is 30 Sept, the market day 1 Oct.
    const late = { cutoff: '2026-09-30T22:30:00Z', dates: [...DATES, '2026-10-01'] };
    expect(windowEnd(late)).toBe('2026-10-01');
    expect(windowSince(windowEnd(late), 30)).toBe('2026-09-02');
    expect(windowSince(windowEnd(late), 7)).toBe('2026-09-25');
    expect(toLaunchesQuery(EMPTY_LAUNCHES, windowEnd(late))).toEqual({ since: '2026-09-02', limit: 100 });
    // Without a listed day the cutoff's date is all there is.
    expect(windowEnd({ cutoff: '2026-09-30T22:30:00Z', dates: [] })).toBe('2026-09-30');
    expect(windowEnd({ cutoff: CUTOFF, dates: ['soon'] })).toBe('2026-09-30');
  });

  it('starts the window so that it ends on the given day, inclusive', () => {
    expect(windowSince(CUTOFF, 30)).toBe('2026-09-01');
    expect(windowSince(CUTOFF, 7)).toBe('2026-09-24');
    expect(windowSince('2026-03-03', 7)).toBe('2026-02-25');
    expect(windowSince('2024-03-01T12:00:00Z', 30)).toBe('2024-02-01');
    expect(windowSince('', 7)).toBe('');
    expect(windowSince('yesterday', 7)).toBe('');
  });

  it('asks for the window and only the filters set, always with a limit', () => {
    expect(toLaunchesQuery(EMPTY_LAUNCHES, CUTOFF)).toEqual({ since: '2026-09-01', limit: 100 });
    expect(toLaunchesQuery(parse('days=7&brand=Fixture+Beauty&limit=500'), CUTOFF)).toEqual({
      since: '2026-09-24',
      brand: ['Fixture Beauty'],
      limit: 500,
    });
    expect(toLaunchesQuery(parse('retailer=sephora_ae&shade=rose&evidence=missing'), CUTOFF)).toEqual({
      since: '2026-09-01',
      retailer: ['sephora_ae'],
      limit: 100,
    });
    // A cutoff that is not a day: no window rather than a value the API would refuse.
    expect(toLaunchesQuery(EMPTY_LAUNCHES, '')).toEqual({ limit: 100 });
  });

  it('keys the API query only on what the API receives', () => {
    const base = parse('retailer=sephora_ae&brand=Fixture+Beauty');
    const key = launchesQueryKey(base, CUTOFF);
    for (const change of [
      { priceMin: '25' },
      { priceMax: '100' },
      { discountMin: '10' },
      { size: '4 ' },
      { color: 'red' },
      { shade: 'rose gold' },
      { availability: ['in_stock'] },
      { evidence: ['stale' as const] },
      { dateFrom: '2026-09-24', dateTo: '2026-09-30' },
    ])
      expect(launchesQueryKey({ ...base, ...change }, CUTOFF)).toEqual(key);
    expect(launchesQueryKey({ ...base, days: 7 }, CUTOFF)).not.toEqual(key);
    expect(launchesQueryKey({ ...base, brand: ['Other'] }, CUTOFF)).not.toEqual(key);
    expect(launchesQueryKey(base, '2026-10-01')).not.toEqual(key);
  });

  it('keeps typed spaces in the URL so a term can still be typed', () => {
    for (const [k, v] of [
      ['size', '4 '],
      ['size', '4 g'],
      ['color', 'rose gold'],
      ['shade', ' rose'],
    ] as const) {
      const state = parse(new URLSearchParams({ [k]: v }).toString());
      expect(state[k]).toBe(v);
      expect(parse(toLaunchesSearch(state).slice(1))[k]).toBe(v);
    }
  });
});
