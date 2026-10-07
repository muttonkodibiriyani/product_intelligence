import { describe, expect, it } from 'vitest';
import {
  activeFilterCount,
  currentPages,
  EMPTY,
  parseState,
  toExportQuery,
  toggle,
  toQuery,
  toSearch,
  withValidSort,
} from './explore';

const parse = (s: string) => parseState(new URLSearchParams(s));

describe('explorer URL state', () => {
  it('round-trips through the URL, keeping the retailer order', () => {
    const s = parse(
      'q=serum&brand=A&brand=B&retailer=shop_b&retailer=shop_a&matched=true&priceMin=10&sort=gap_asc',
    );
    expect(s).toMatchObject({
      q: 'serum',
      brand: ['A', 'B'],
      retailer: ['shop_b', 'shop_a'],
      matched: 'yes',
      priceMin: '10',
      sort: 'gap_asc',
    });
    expect(parse(toSearch(s).slice(1))).toEqual(s);
  });

  it('carries the stock filters Insights links with, in a fixed order, dropping unknown values', () => {
    const s = parse(
      'availability=out_of_stock&availability=in_stock&availability=gone&unavailableBrands=exclude',
    );
    expect(s.availability).toEqual(['in_stock', 'out_of_stock']);
    expect(s.unavailableBrands).toBe('exclude');
    expect(parse(toSearch(s).slice(1))).toEqual(s);
    expect(parse('unavailableBrands=all').unavailableBrands).toBeNull();
    expect(toQuery(s, null)).toEqual({
      availability: ['in_stock', 'out_of_stock'],
      unavailableBrands: 'exclude',
      sort: 'name',
      limit: 50,
    });
    expect(activeFilterCount(s)).toBe(3);
  });

  it('a clean view has a clean URL', () => {
    expect(toSearch(EMPTY)).toBe('');
    expect(parse('')).toEqual(EMPTY);
  });

  it('drops what the API would refuse instead of sending it', () => {
    const s = parse(`sort=cheapest&priceMin=1e3&priceMax=-5&matched=maybe&brand=${'x'.repeat(121)}&brand=`);
    expect(s).toEqual(EMPTY);
    expect(parse(Array.from({ length: 30 }, (_, i) => `brand=b${i}`).join('&')).brand).toHaveLength(25);
    expect(parse('brand=A&brand=A').brand).toEqual(['A']);
  });

  it('gap sorts need exactly two retailers, else name (the API answers 422)', () => {
    expect(parse('sort=gap').sort).toBe('name');
    expect(parse('sort=gap&retailer=a&retailer=b&retailer=c').sort).toBe('name');
    expect(parse('sort=gap&retailer=a&retailer=b').sort).toBe('gap');
    expect(withValidSort({ ...EMPTY, retailer: ['a'], sort: 'gap_asc' }).sort).toBe('name');
  });

  it('builds the API query: repeated lists, the pair in order, boolean matched, cursor last', () => {
    const q = toQuery(parse('retailer=shop_a&retailer=shop_b&matched=false&sort=gap'), 'c1');
    expect(q).toEqual({
      retailer: ['shop_a', 'shop_b'],
      matched: false,
      sort: 'gap',
      limit: 50,
      cursor: 'c1',
    });
    expect(toQuery(EMPTY, null)).toEqual({ sort: 'name', limit: 50 });
  });

  it('toggle keeps the order values were picked in', () => {
    expect(toggle(['a'], 'b')).toEqual(['a', 'b']);
    expect(toggle(['a', 'b'], 'a')).toEqual(['b']);
  });
});

describe('currentPages', () => {
  it('keeps only the pages from the last restart on', () => {
    const p = (n: number, restarted = false) => ({ n, restarted });
    expect(currentPages([p(1), p(2)]).map((x) => x.n)).toEqual([1, 2]);
    expect(currentPages([p(1), p(2), p(3, true), p(4)]).map((x) => x.n)).toEqual([3, 4]);
    expect(currentPages([])).toEqual([]);
  });
});

describe('toExportQuery', () => {
  it('keeps the filters, pair order and sort, drops paging, adds the format', () => {
    const s = parseState(
      new URLSearchParams('q=serum&retailer=shop_b&retailer=shop_a&sort=gap&matched=true&priceMax=200'),
    );
    expect(toExportQuery(s, 'jsonl')).toEqual({
      q: 'serum',
      retailer: ['shop_b', 'shop_a'],
      matched: true,
      priceMax: '200',
      sort: 'gap',
      format: 'jsonl',
    });
  });
});
