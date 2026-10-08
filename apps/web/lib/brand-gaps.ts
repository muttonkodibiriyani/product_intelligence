/**
 * Brand gaps: one focus shop's listings, per brand, against every other shop (lane D). Pure, so the
 * rules are unit-tested; `components/gaps/gaps-view.tsx` draws them.
 *
 * The unit is a listing (one product, one size, at one shop). A focus listing is `both` (an accepted
 * exact match at another shop), `unconfirmed`, `family` (another size or shade) or `focus_only` (no
 * match found). Only `notAt` is proven absence, and only for shops whose run is complete; a shop
 * that is not supported is named in `withheld` and has no count at all, never 0.
 */
import type { Schemas } from './api/types';
import { apiAtLeast } from './insights';
import { cleanList, RETAILER_ID } from './url-state';

// DRAFT CONTRACT: mirrors pi_metrics.brand_gaps (#301) and Insights' route shape until the routes
// PR adds them to the openapi; then these become Schemas[...] and schema.gen.ts is regenerated.
export type Reason = Schemas['Reason'];
export type GapLabel = Schemas['GapLabel'];
export type RetailerStatus = Schemas['RetailerStatus'];

export interface ShopCount {
  retailer: string;
  n: number;
}

export interface BrandRow {
  brand: string;
  focusN: number;
  both: number;
  unconfirmed: number;
  family: number;
  focusOnly: number;
  bothBy: ShopCount[];
  /** One per supported other shop, 0 included: a proven count. */
  notAt: ShopCount[];
  /** Null when the focus shop's own run can't back it (never 0). */
  othersOnly: number | null;
  othersBy: ShopCount[];
  focusOnlyShare: string | null;
  shareReason: Reason | null;
}

export interface BrandGaps {
  focus: string;
  others: string[];
  focusOnlyLabel: GapLabel;
  absenceLabel: GapLabel;
  totals: BrandRow;
  byBrand: BrandRow[];
  withheld: { retailer: string; reason: Reason }[];
  sides: {
    retailer: string;
    status: RetailerStatus;
    listings: number;
    window: { start: string; end: string } | null;
  }[];
}

export const SIDES = ['both', 'unconfirmed', 'family', 'focus_only', 'others_only', 'not_at'] as const;
export type Side = (typeof SIDES)[number];

/** The items route's data: one page of listings, `total` across every page. */
export interface GapItems {
  total: number;
  nextCursor: string | null;
  items: GapItem[];
}

export interface GapItem {
  id: string;
  brand: string;
  name: string;
  category: string[];
  retailer: string;
  side: Exclude<Side, 'not_at'>;
  bothAt: string[];
  /** Retailer ids proven not to have it (on the summary, `notAt` holds counts instead). */
  notAt: string[];
}

/** The API version that serves /brand-gaps; compared to /meta's apiVersion. */
export const GAPS_API = '1.27.0';

/** Listings asked per page of a list (the API allows 1–100). */
export const ITEMS_PAGE = 50;

/** The shop the page is about. The owner's question is Ulta's gaps; the URL can name another. */
export const DEFAULT_FOCUS = 'ulta_ae';

export const SORTS = ['focus_only', 'focus_n', 'brand'] as const;
export type Sort = (typeof SORTS)[number];

export interface GapsState {
  focus: string;
  /** Brands the table is narrowed to (the API's brand filter); empty is every brand. */
  brand: string[];
  sort: Sort;
  /** The open list: a brand (or every brand, null) and a side; `retailer` only with not_at. */
  list: { brand: string | null; side: Side; retailer: string | null } | null;
}

const isSide = (v: string | null): v is Side => (SIDES as readonly string[]).includes(v ?? '');

/** Sides that take a retailer: not_at needs one; both (in bothAt) and others_only (the listing's shop) may. */
const RETAILER_SIDES: ReadonlySet<Side> = new Set(['not_at', 'both', 'others_only']);

/**
 * The page's state from its URL. A list needs a valid side; not_at needs a valid retailer, both and
 * others_only keep one when given, and any other side drops it, so a URL can never ask for a list
 * the API would refuse.
 */
export function parseGaps(sp: URLSearchParams): GapsState {
  const focus = sp.get('focus') ?? '';
  const sort = sp.get('sort') ?? '';
  const side = sp.get('side');
  const retailer = sp.get('retailer') ?? '';
  const okRetailer = RETAILER_ID.test(retailer);
  const listBrand = sp.get('list')?.trim() || null;
  return {
    focus: RETAILER_ID.test(focus) ? focus : DEFAULT_FOCUS,
    brand: cleanList(sp.getAll('brand')),
    sort: (SORTS as readonly string[]).includes(sort) ? (sort as Sort) : 'focus_only',
    list:
      isSide(side) && (side !== 'not_at' || okRetailer)
        ? { brand: listBrand, side, retailer: okRetailer && RETAILER_SIDES.has(side) ? retailer : null }
        : null,
  };
}

export function toGapsSearch(s: GapsState): string {
  const p = new URLSearchParams();
  if (s.focus !== DEFAULT_FOCUS) p.set('focus', s.focus);
  for (const b of s.brand) p.append('brand', b);
  if (s.sort !== 'focus_only') p.set('sort', s.sort);
  if (s.list) {
    if (s.list.brand) p.set('list', s.list.brand);
    p.set('side', s.list.side);
    if (s.list.retailer) p.set('retailer', s.list.retailer);
  }
  const q = p.toString();
  return q ? `?${q}` : '';
}

/** The summary's query. */
export const toGapsQuery = (s: GapsState) => ({
  focus: s.focus,
  ...(s.brand.length ? { brand: s.brand } : {}),
});

export interface ItemsQuery {
  focus: string;
  side: Side;
  retailer?: string;
  brand?: string[];
}

/** The open list's query: one brand, or the table's brands when the list is for all of them. */
export function toItemsQuery(s: GapsState): ItemsQuery | null {
  if (!s.list) return null;
  const brand = s.list.brand ? [s.list.brand] : s.brand;
  return {
    focus: s.focus,
    side: s.list.side,
    ...(s.list.retailer ? { retailer: s.list.retailer } : {}),
    ...(brand.length ? { brand } : {}),
  };
}

/** Brands in the asked order; ties keep the brand's name order so the table never reshuffles. */
export function sortBrands(rows: readonly BrandRow[], sort: Sort, locale: string): BrandRow[] {
  const byName = (a: BrandRow, b: BrandRow) => a.brand.localeCompare(b.brand, locale);
  const by =
    sort === 'brand'
      ? byName
      : (a: BrandRow, b: BrandRow) =>
          (sort === 'focus_n' ? b.focusN - a.focusN : b.focusOnly - a.focusOnly) || byName(a, b);
  return [...rows].sort(by);
}

/**
 * The other shops the not-at columns are drawn for: those `totals.notAt` counts (supported, run
 * complete), in the API's order. A withheld shop has no column, so no number for it reads as 0.
 */
export const notAtShops = (g: BrandGaps): string[] => g.totals.notAt.map((c) => c.retailer);

/** A brand's proven not-at count for a shop; null when the API gave none (withheld). */
export const notAtOf = (row: BrandRow, retailer: string): number | null =>
  row.notAt.find((c) => c.retailer === retailer)?.n ?? null;

/** Does the live API serve brand gaps? Undefined until /meta has answered. */
export const gapsServed = (meta: { meta: { apiVersion: string } } | undefined): boolean | undefined =>
  meta ? apiAtLeast(meta.meta.apiVersion, GAPS_API) : undefined;
