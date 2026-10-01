import type { QueryOf, Schemas } from './api/types';

export type ProductSort = Schemas['ProductSort'];
export type ProductsQuery = QueryOf<'/api/v1/products'>;

export const SORTS: readonly ProductSort[] = ['name', 'price_asc', 'price_desc', 'gap', 'gap_asc'];
const GAP_SORTS: readonly ProductSort[] = ['gap', 'gap_asc'];
/** The API's limits (contract): at most 25 values per list filter, 120 characters each. */
const MAX_VALUES = 25;
const MAX_LEN = 120;
const PRICE = /^\d{1,12}(\.\d{1,6})?$/;
export const PAGE_SIZE = 50;

/**
 * Everything the explorer shows is described by the URL, so a view can be shared, reloaded and
 * reached with Back. `retailer` is ordered: with exactly two, the first is the base of the gap.
 */
export interface ExploreState {
  q: string;
  brand: string[];
  category: string[];
  retailer: string[];
  matched: 'any' | 'yes' | 'no';
  priceMin: string;
  priceMax: string;
  sort: ProductSort;
}

export const EMPTY: ExploreState = {
  q: '',
  brand: [],
  category: [],
  retailer: [],
  matched: 'any',
  priceMin: '',
  priceMax: '',
  sort: 'name',
};

const text = (v: string | null) => (v ?? '').trim().slice(0, MAX_LEN);
const list = (vs: string[]) =>
  [...new Set(vs.map((v) => v.trim()).filter((v) => v && v.length <= MAX_LEN))].slice(0, MAX_VALUES);

/** A gap needs exactly two different retailers. */
export const hasPair = (s: Pick<ExploreState, 'retailer'>) => s.retailer.length === 2;

/** Reads the URL leniently: anything the API would refuse is dropped rather than sent. */
export function parseState(sp: URLSearchParams): ExploreState {
  const sort = sp.get('sort') as ProductSort | null;
  const matched = sp.get('matched');
  const s: ExploreState = {
    q: text(sp.get('q')),
    brand: list(sp.getAll('brand')),
    category: list(sp.getAll('category')),
    retailer: list(sp.getAll('retailer')),
    matched: matched === 'true' ? 'yes' : matched === 'false' ? 'no' : 'any',
    priceMin: PRICE.test(sp.get('priceMin') ?? '') ? sp.get('priceMin')! : '',
    priceMax: PRICE.test(sp.get('priceMax') ?? '') ? sp.get('priceMax')! : '',
    sort: sort && SORTS.includes(sort) ? sort : 'name',
  };
  return withValidSort(s);
}

/** Gap sorts are refused (422) without a pair, so they fall back to name. */
export function withValidSort(s: ExploreState): ExploreState {
  return GAP_SORTS.includes(s.sort) && !hasPair(s) ? { ...s, sort: 'name' } : s;
}

export const isPrice = (v: string) => v === '' || PRICE.test(v);

/** The URL query for a state; defaults are left out so a clean view has a clean URL. */
export function toSearch(s: ExploreState): string {
  const p = new URLSearchParams();
  if (s.q) p.set('q', s.q);
  for (const k of ['brand', 'category', 'retailer'] as const) for (const v of s[k]) p.append(k, v);
  if (s.matched !== 'any') p.set('matched', s.matched === 'yes' ? 'true' : 'false');
  if (s.priceMin) p.set('priceMin', s.priceMin);
  if (s.priceMax) p.set('priceMax', s.priceMax);
  if (s.sort !== 'name') p.set('sort', s.sort);
  const out = p.toString();
  return out ? `?${out}` : '';
}

export function toQuery(s: ExploreState, cursor: string | null): ProductsQuery {
  return {
    ...(s.q ? { q: s.q } : {}),
    ...(s.brand.length ? { brand: s.brand } : {}),
    ...(s.category.length ? { category: s.category } : {}),
    ...(s.retailer.length ? { retailer: s.retailer } : {}),
    ...(s.matched !== 'any' ? { matched: s.matched === 'yes' } : {}),
    ...(s.priceMin ? { priceMin: s.priceMin } : {}),
    ...(s.priceMax ? { priceMax: s.priceMax } : {}),
    sort: s.sort,
    limit: PAGE_SIZE,
    ...(cursor ? { cursor } : {}),
  };
}

/** Adds a value at the end (keeping the order it was picked in) or removes it. */
export function toggle(values: readonly string[], v: string): string[] {
  return values.includes(v) ? values.filter((x) => x !== v) : [...values, v];
}

export const activeFilterCount = (s: ExploreState) =>
  (s.q ? 1 : 0) +
  s.brand.length +
  s.category.length +
  s.retailer.length +
  (s.matched !== 'any' ? 1 : 0) +
  (s.priceMin ? 1 : 0) +
  (s.priceMax ? 1 : 0);

/**
 * Pages as loaded. A page fetched after the data changed under its cursor starts over, so only
 * the pages from the last restart on describe one consistent list.
 */
export function currentPages<T extends { restarted: boolean }>(pages: readonly T[]): T[] {
  let from = 0;
  pages.forEach((p, i) => {
    if (p.restarted) from = i;
  });
  return pages.slice(from);
}
