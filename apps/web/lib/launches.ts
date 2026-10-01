import type { QueryOf } from './api/types';
import { cleanList, type Limit, LIMITS, parseLimit, RETAILER_ID } from './url-state';

export type LaunchesQuery = QueryOf<'/api/v1/launches'>;

/** The launches view, all in the URL. No retailer picked means every retailer. */
export interface LaunchesState {
  retailer: string[];
  /** First seen on or after this day (YYYY-MM-DD); '' means any day. */
  since: string;
  brand: string[];
  category: string[];
  limit: Limit;
}

export const EMPTY_LAUNCHES: LaunchesState = {
  retailer: [],
  since: '',
  brand: [],
  category: [],
  limit: LIMITS[0],
};

/** A real calendar day as YYYY-MM-DD, the only form the API accepts; anything else is ''. */
export function cleanDay(v: string | null): string {
  // The API's dates start at year 1, so 0000 is refused there too.
  if (!v || !/^\d{4}-\d{2}-\d{2}$/.test(v) || v.startsWith('0000')) return '';
  const d = new Date(`${v}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === v ? v : '';
}

export function parseLaunches(sp: URLSearchParams): LaunchesState {
  return {
    retailer: cleanList(sp.getAll('retailer')).filter((r) => RETAILER_ID.test(r)),
    since: cleanDay(sp.get('since')),
    brand: cleanList(sp.getAll('brand')),
    category: cleanList(sp.getAll('category')),
    limit: parseLimit(sp.get('limit')),
  };
}

export function toLaunchesSearch(s: LaunchesState): string {
  const p = new URLSearchParams();
  for (const k of ['retailer', 'brand', 'category'] as const) for (const v of s[k]) p.append(k, v);
  if (s.since) p.set('since', s.since);
  if (s.limit !== LIMITS[0]) p.set('limit', String(s.limit));
  const out = p.toString();
  return out ? `?${out}` : '';
}

/** Always with a limit: only then does the API send the newest first and say when it cut. */
export function toLaunchesQuery(s: LaunchesState): LaunchesQuery {
  return {
    ...(s.retailer.length ? { retailer: s.retailer } : {}),
    ...(s.since ? { since: s.since } : {}),
    ...(s.brand.length ? { brand: s.brand } : {}),
    ...(s.category.length ? { category: s.category } : {}),
    limit: s.limit,
  };
}
