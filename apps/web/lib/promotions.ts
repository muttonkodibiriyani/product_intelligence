import type { QueryOf, Schemas } from './api/types';
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

/** The export of the same list: the list's filters, no limit, in the format asked for. */
export function toPromotionsExportQuery(s: PromotionsState, format: 'csv' | 'jsonl') {
  const q: Partial<PromotionsQuery> = toPromotionsQuery(s);
  delete q.limit;
  return { ...q, format };
}

type Item = Pick<Schemas['PromoItem'], 'retailer' | 'depthPct'>;

/**
 * The deepest discount a shop shows in the list the API sent, as the API wrote it ("33.3"), or
 * null when the list has none of that shop's products (filtered out, or cut by the limit): the
 * tile then says nothing about depth rather than guess.
 */
export function deepestCut(items: readonly Item[], retailer: string): string | null {
  let best: string | null = null;
  for (const i of items) {
    if (i.retailer !== retailer || !/^\d+(\.\d+)?$/.test(i.depthPct)) continue;
    if (best === null || Number(i.depthPct) > Number(best)) best = i.depthPct;
  }
  return best;
}

/** A share the API wrote ("18.4") as a bar width in 0–100, or null when it is not a number. */
export function shareWidth(share: string | null): number | null {
  if (share === null || !/^\d+(\.\d+)?$/.test(share)) return null;
  return Math.min(100, Number(share));
}

/** The shop the user picked, when exactly one: the list's heading names it. */
export function pickedShop(s: Pick<PromotionsState, 'retailer'>): string | null {
  return s.retailer.length === 1 ? s.retailer[0]! : null;
}

type Share = Pick<Schemas['RetailerPromo'], 'retailer' | 'share' | 'reason'>;

/**
 * Why promotions are not measured for what is on screen, or null when at least one shown shop has
 * a share: the picked shop's own reason, else the envelope's, else the first shop's. An empty
 * list of discounts is only "no discounts" when something was measured.
 */
export function notMeasured(
  env: { reason?: Schemas['Reason'] | null; data: { retailers: readonly Share[] } | null },
  shop: string | null,
): string | null {
  const shares = env.data?.retailers ?? [];
  const picked = shop ? shares.find((r) => r.retailer === shop) : undefined;
  if (picked) return picked.share === null ? (picked.reason ?? env.reason ?? 'field_not_collected') : null;
  if (shares.some((r) => r.share !== null)) return null;
  return env.reason ?? shares.find((r) => r.reason)?.reason ?? 'field_not_collected';
}
