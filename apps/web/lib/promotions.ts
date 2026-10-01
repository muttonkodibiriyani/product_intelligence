import type { QueryOf } from './api/types';
import { cleanList, type Limit, LIMITS, parseLimit, RETAILER_ID } from './url-state';

export type PromotionsQuery = QueryOf<'/api/v1/promotions'>;

/** Minimum discounts offered in the picker; '' means any discount. */
export const MIN_PCTS = ['', '10', '20', '30', '50'] as const;
export type MinPct = (typeof MIN_PCTS)[number];

/** The promotions view, all in the URL. No retailer picked means every retailer. */
export interface PromotionsState {
  retailer: string[];
  minPct: MinPct;
  brand: string[];
  category: string[];
  limit: Limit;
}

export const EMPTY_PROMOTIONS: PromotionsState = {
  retailer: [],
  minPct: '',
  brand: [],
  category: [],
  limit: LIMITS[0],
};

export function parsePromotions(sp: URLSearchParams): PromotionsState {
  const minPct = sp.get('minPct') ?? '';
  return {
    retailer: cleanList(sp.getAll('retailer')).filter((r) => RETAILER_ID.test(r)),
    minPct: (MIN_PCTS as readonly string[]).includes(minPct) ? (minPct as MinPct) : '',
    brand: cleanList(sp.getAll('brand')),
    category: cleanList(sp.getAll('category')),
    limit: parseLimit(sp.get('limit')),
  };
}

export function toPromotionsSearch(s: PromotionsState): string {
  const p = new URLSearchParams();
  for (const k of ['retailer', 'brand', 'category'] as const) for (const v of s[k]) p.append(k, v);
  if (s.minPct) p.set('minPct', s.minPct);
  if (s.limit !== LIMITS[0]) p.set('limit', String(s.limit));
  const out = p.toString();
  return out ? `?${out}` : '';
}

export function toPromotionsQuery(s: PromotionsState): PromotionsQuery {
  return {
    ...(s.retailer.length ? { retailer: s.retailer } : {}),
    ...(s.minPct ? { minPct: s.minPct } : {}),
    ...(s.brand.length ? { brand: s.brand } : {}),
    ...(s.category.length ? { category: s.category } : {}),
    limit: s.limit,
  };
}
