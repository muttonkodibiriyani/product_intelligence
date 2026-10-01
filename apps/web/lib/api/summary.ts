/**
 * GET /api/v1/summary (API 1.4.0): one retailer's snapshot, aggregated by the server for the
 * landing dashboard. The shape is the one agreed with the data side; until the generated schema
 * has it, it is written out here. On the rebase onto 1.4.0, `Summary` becomes
 * `Schemas['Summary']` and the cast in `getSummary` goes.
 *
 * Amounts and percentages are decimal strings, like everywhere else in the API.
 */
import type { ApiClient } from './client';
import type { Envelope, Schemas } from './types';

type Money = Schemas['MoneyValue'];

/** Why a section of /summary is null: it is not measured, which is not the same as zero. */
export interface Withheld {
  section: 'promotions' | 'prices' | 'ratings' | string;
  reason: 'capability_off' | 'field_not_collected' | 'cohort_too_small' | string;
}

export interface Summary {
  asOf: string;
  /** Every collected product, priced or not. */
  products: number;
  /** Products with a price: the denominator for any share of priced products. */
  priced: number;
  brands: number;
  categories: number;
  medianPrice: Money | null;
  /** The three promotion fields are null together when `withheld` lists "promotions". */
  promoSharePct: string | null;
  freshness: { cutoff: string; ageDays: number; status: 'fresh' | 'aging' | 'stale' | string };
  withheld: Withheld[];
  /** Per category: the price quartiles. Entry is below p25, premium above p75. */
  ladder: { category: string; n: number; min: string; p25: string; p50: string; p75: string; max: string }[];
  /** Discounted products: `cells[categoryIdx][bandIdx]`; bands like "<10", "10-20", "50+". */
  promoDepth: { category: string[]; bands: string[]; cells: number[][] } | null;
  /** The top 30 brands by priced products (n desc, then name), with their median price. */
  brandPrice: { brand: string; n: number; median: string }[];
  categoryMix: { category: string; n: number }[];
  /** `counts[i]` products cost from `edges[i]` up to `edges[i + 1]`. */
  priceHist: { edges: string[]; counts: number[] };
  /** `ratedPct` of products carry a rating; `points` is a deterministic sample when `sampled`. */
  ratingPrice: {
    n: number;
    ratedPct: string;
    sampled?: boolean;
    points: { price: string; rating: string; count: number }[];
  };
  /** Null when not measured; [] when measured and nothing is discounted. */
  topDiscounts:
    | {
        id: string;
        brand: string;
        name: string;
        category: string[];
        price: Money;
        regular: Money;
        depthPct: string;
        image?: string | null;
      }[]
    | null;
}

export interface SummaryQuery {
  market?: string;
  scope?: string;
  retailer?: string;
}

export function getSummary(
  api: ApiClient,
  query: SummaryQuery = {},
  signal?: AbortSignal,
): Promise<Envelope<Summary>> {
  // Not in the generated paths before 1.4.0; the typed client builds the URL and checks errors.
  const get = api.get as unknown as (
    path: string,
    opts: { query: SummaryQuery; signal?: AbortSignal },
  ) => Promise<Envelope<Summary>>;
  return get('/api/v1/summary', { query, signal });
}

/** A decimal string from the API as a number, for charts only; never shown re-rounded. */
export const num = (v: string | number | null | undefined): number =>
  v === null || v === undefined || v === '' ? NaN : Number(v);
