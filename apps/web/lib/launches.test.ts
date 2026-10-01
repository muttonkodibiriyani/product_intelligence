import { describe, expect, it } from 'vitest';
import { cleanDay, EMPTY_LAUNCHES, parseLaunches, toLaunchesQuery, toLaunchesSearch } from './launches';

const parse = (q: string) => parseLaunches(new URLSearchParams(q));

describe('launches URL state', () => {
  it('round-trips a full view and leaves defaults out', () => {
    const q = '?retailer=shop_a&brand=The+Ordinary&category=Serum&since=2026-09-01&limit=500';
    expect(toLaunchesSearch(parse(q))).toBe(q);
    expect(toLaunchesSearch(EMPTY_LAUNCHES)).toBe('');
  });

  it('keeps only real days in the form the API accepts', () => {
    expect(cleanDay('2026-09-01')).toBe('2026-09-01');
    expect(cleanDay('2024-02-29')).toBe('2024-02-29');
    expect(cleanDay('0001-01-01')).toBe('0001-01-01');
    for (const v of [
      '2026-02-30',
      '2026-13-01',
      '2026-9-1',
      '01/09/2026',
      '2026-09-01T00:00',
      '0000-01-01',
      '',
      null,
    ])
      expect(cleanDay(v)).toBe('');
  });

  it('drops values the API would refuse', () => {
    expect(parse('retailer=Shop%20A&retailer=1shop&retailer=shop_b').retailer).toEqual(['shop_b']);
    expect(parse('since=yesterday').since).toBe('');
    expect(parse('limit=7').limit).toBe(100);
  });

  it('asks only for what is set, always with a limit', () => {
    expect(toLaunchesQuery(EMPTY_LAUNCHES)).toEqual({ limit: 100 });
    expect(toLaunchesQuery(parse('retailer=shop_b&since=2026-09-28'))).toEqual({
      retailer: ['shop_b'],
      since: '2026-09-28',
      limit: 100,
    });
  });
});
