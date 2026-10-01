/**
 * GET /api/v1/summary (API 1.4.0): one retailer's snapshot, aggregated by the server for the
 * landing dashboard. Written out field for field as `SummaryView` in #104's OpenAPI; on the
 * rebase onto 1.4.0, `Summary` becomes `Schemas['SummaryView']` and the cast in `getSummary` goes.
 *
 * Amounts are MoneyValue and percentages decimal strings, like everywhere else in the API.
 */
import type { ApiClient } from './client';
import type { Envelope, Schemas } from './types';

type Money = Schemas['MoneyValue'];

/** Why a section of /summary is null: it is not measured, which is not the same as zero. */
export interface Withheld {
  section: 'prices' | 'promotions' | 'ratings';
  reason:
    | 'capability_off'
    | 'field_not_collected'
    | 'retailer_blocked'
    | 'retailer_partial'
    | 'cohort_too_small'
    | 'matches_unreviewed'
    | 'no_match'
    | 'not_in_scope'
    | 'currency_mismatch'
    | 'not_applicable';
}

export interface Summary {
  asOf: string;
  retailer: string;
  currency: string;
  /** Offers observed on the latest date, priced or not; the counts are null when withheld, never 0. */
  products: number | null;
  /** Products with a price: the denominator for any share of priced products. */
  priced: number | null;
  brands: number | null;
  categories: number | null;
  medianPrice: Money | null;
  freshness: { cutoff: string; ageDays: number; status: 'fresh' | 'aging' | 'stale' };
  /** The sections below that are null, and why. */
  withheld: Withheld[];
  /** Per category: the price quartiles. Entry is below p25, premium above p75. Null: prices withheld. */
  ladder:
    { category: string; n: number; min: Money; p25: Money; p50: Money; p75: Money; max: Money }[] | null;
  /** The top 30 brands by priced products (n desc, then name), with their median price. */
  brandPrice: { brand: string; n: number; median: Money }[] | null;
  /** Products per category path. */
  categoryMix: { category: string[]; n: number }[] | null;
  /** `counts[i]` products cost from `edges[i]` up to `edges[i + 1]`. */
  priceHist: { edges: string[]; counts: number[] } | null;
  /** `ratedPct` of products carry a rating out of `scale`; `points` is a deterministic sample when `sampled`. */
  ratingPrice: {
    n: number;
    ratedPct: string;
    sampled: boolean;
    scale: string;
    points: { price: string; rating: string; count: number }[];
  } | null;
  /** The three promotion fields are null together when `withheld` lists "promotions". */
  promoSharePct: string | null;
  /** Discounted products: `cells[categoryIdx][bandIdx]`; bands like "<10", "10-20", "50+". */
  promoDepth: { category: string[]; bands: string[]; cells: number[][] } | null;
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

/** A section the landing draws, once /summary has measured it. */
export type Measured<K extends keyof Summary> = NonNullable<Summary[K]>;

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
