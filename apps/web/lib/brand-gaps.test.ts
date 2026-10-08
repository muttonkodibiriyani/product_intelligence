import { describe, expect, it } from 'vitest';
import {
  type BrandRow,
  gapsServed,
  notAtOf,
  parseGaps,
  sortBrands,
  toGapsQuery,
  toGapsSearch,
  toItemsQuery,
} from './brand-gaps';

const parse = (q: string) => parseGaps(new URLSearchParams(q));

const row = (brand: string, focusN: number, focusOnly: number, notAt: [string, number][] = []): BrandRow => ({
  brand,
  focusN,
  both: focusN - focusOnly,
  unconfirmed: 0,
  family: 0,
  focusOnly,
  bothBy: [],
  notAt: notAt.map(([retailer, n]) => ({ retailer, n })),
  othersOnly: 0,
  othersBy: [],
  focusOnlyShare: null,
  shareReason: 'cohort_too_small',
});

describe('parseGaps', () => {
  it('defaults to Ulta, every brand, most unmatched first, no list', () => {
    expect(parse('')).toEqual({ focus: 'ulta_ae', brand: [], sort: 'focus_only', list: null });
  });

  it('drops a focus, sort or side the API would refuse', () => {
    expect(parse('focus=Ulta AE&sort=price&side=missing')).toEqual(parse(''));
  });

  it('not_at needs a valid retailer, else no list', () => {
    expect(parse('side=not_at').list).toBeNull();
    expect(parse('side=not_at&retailer=Sephora!').list).toBeNull();
    expect(parse('side=not_at&retailer=sephora_me&list=Dior').list).toEqual({
      brand: 'Dior',
      side: 'not_at',
      retailer: 'sephora_me',
    });
  });

  it('keeps a retailer only on the sides that take one', () => {
    expect(parse('side=both&retailer=faces_ae').list?.retailer).toBe('faces_ae');
    expect(parse('side=others_only&retailer=faces_ae').list?.retailer).toBe('faces_ae');
    for (const side of ['unconfirmed', 'family', 'focus_only'])
      expect(parse(`side=${side}&retailer=faces_ae`).list).toEqual({ brand: null, side, retailer: null });
  });

  it('an empty list= is the list for every brand', () => {
    expect(parse('side=focus_only&list=').list?.brand).toBeNull();
  });
});

describe('toGapsSearch', () => {
  it('round-trips and leaves defaults out of the URL', () => {
    expect(toGapsSearch(parse(''))).toBe('');
    const q = 'focus=faces_ae&brand=Dior&brand=MAC&sort=brand&list=Dior&side=not_at&retailer=sephora_me';
    expect(toGapsSearch(parse(q))).toBe(`?${q}`);
  });
});

describe('queries', () => {
  it('the summary always sends focus', () => {
    expect(toGapsQuery(parse(''))).toEqual({ focus: 'ulta_ae' });
    expect(toGapsQuery(parse('brand=Dior'))).toEqual({ focus: 'ulta_ae', brand: ['Dior'] });
  });

  it('a list asks for its brand, or the table’s brands when it is for all of them', () => {
    expect(toItemsQuery(parse('brand=A&brand=B&side=focus_only&list=A'))).toEqual({
      focus: 'ulta_ae',
      side: 'focus_only',
      brand: ['A'],
    });
    expect(toItemsQuery(parse('brand=A&brand=B&side=not_at&retailer=faces_ae'))).toEqual({
      focus: 'ulta_ae',
      side: 'not_at',
      retailer: 'faces_ae',
      brand: ['A', 'B'],
    });
    expect(toItemsQuery(parse(''))).toBeNull();
  });
});

describe('sortBrands', () => {
  const rows = [row('b', 10, 2), row('a', 30, 2), row('c', 5, 5)];
  it('most unmatched first, ties by name', () => {
    expect(sortBrands(rows, 'focus_only', 'en').map((r) => r.brand)).toEqual(['c', 'a', 'b']);
  });
  it('most listings first, or by name', () => {
    expect(sortBrands(rows, 'focus_n', 'en').map((r) => r.brand)).toEqual(['a', 'b', 'c']);
    expect(sortBrands(rows, 'brand', 'en').map((r) => r.brand)).toEqual(['a', 'b', 'c']);
  });
});

describe('notAtOf', () => {
  it('a proven 0 is 0; a shop the API left out (withheld) is null, never 0', () => {
    const r = row('a', 10, 1, [['sephora_me', 0]]);
    expect(notAtOf(r, 'sephora_me')).toBe(0);
    expect(notAtOf(r, 'ounass_ae')).toBeNull();
  });
});

describe('gapsServed', () => {
  it('reads /meta’s apiVersion; unknown until it answers', () => {
    expect(gapsServed(undefined)).toBeUndefined();
    expect(gapsServed({ meta: { apiVersion: '1.26.0' } })).toBe(false);
    expect(gapsServed({ meta: { apiVersion: '1.27.0' } })).toBe(true);
    expect(gapsServed({ meta: { apiVersion: '1.30.2' } })).toBe(true);
  });
});
