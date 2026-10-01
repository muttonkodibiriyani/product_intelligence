/**
 * GET /api/v1/summary (API 1.4.0): one retailer's snapshot, aggregated by the server for the
 * landing dashboard.
 *
 * Amounts are MoneyValue and percentages decimal strings, like everywhere else in the API. A null
 * section (or count) is withheld, never zero; `withheld` lists which and why.
 */
import type { ApiClient } from './client';
import type { Envelope, Schemas } from './types';

export type Summary = Schemas['SummaryView'];
/** Why a section of /summary is null: it is not measured, which is not the same as zero. */
export type Withheld = Schemas['Withheld'];

/** A section the landing draws, once /summary has measured it. */
export type Measured<K extends keyof Summary> = NonNullable<Summary[K]>;

export type SummaryQuery = { market?: string; scope?: string; retailer?: string };

export function getSummary(
  api: ApiClient,
  query: SummaryQuery = {},
  signal?: AbortSignal,
): Promise<Envelope<Summary>> {
  return api.get('/api/v1/summary', { query, signal });
}

/** A decimal string from the API as a number, for charts only; never shown re-rounded. */
export const num = (v: string | number | null | undefined): number =>
  v === null || v === undefined || v === '' ? NaN : Number(v);
