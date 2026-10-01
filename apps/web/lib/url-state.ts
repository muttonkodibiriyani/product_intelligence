/** Shared URL-state helpers for the analytics pages. */

/** Rows asked for: the API sends its most relevant rows first and says when the list was cut. */
export const LIMITS = [100, 500] as const;
export type Limit = (typeof LIMITS)[number];
export const MAX_LIMIT: Limit = LIMITS[LIMITS.length - 1]!;

/** The API's limits (contract): at most 25 values per list filter, 120 characters each. */
const MAX_VALUES = 25;
const MAX_LEN = 120;

export const cleanList = (vs: string[]) =>
  [...new Set(vs.map((v) => v.trim()).filter((v) => v && v.length <= MAX_LEN))].slice(0, MAX_VALUES);

export function parseLimit(v: string | null): Limit {
  const n = Number(v);
  return (LIMITS as readonly number[]).includes(n) ? (n as Limit) : LIMITS[0];
}

/** A retailer id as the API accepts it. */
export const RETAILER_ID = /^[a-z][a-z0-9_]{1,62}$/;
