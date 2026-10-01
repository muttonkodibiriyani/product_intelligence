import type { ApiClient } from './client';
import type { Envelope, Money, Reason, Schemas } from './types';

/*
 * The category comparison over full catalogues, across the shared buckets:
 * GET /api/v1/category-compare?retailers=base,other&level=bucket.
 *
 * Everything that touches the wire shape (Schemas['CategoryComparison'] and its rows, cells and
 * coverage) lives in this file; the UI only sees the model below. Each field is read through the
 * schema's types, so a contract change fails tsc here, and still checked at run time, so a body
 * that drifts from the contract reads as too few or no data, never as 0.
 */
type Wire = Schemas['CategoryComparison'];
type WireRow = Schemas['CategoryRow'];
type WireCell = Schemas['Cell'];
type WireGap = Schemas['Gap'];
type WireUnmapped = Schemas['UnmappedPath'];

/** The nine shared buckets, in the order the owner fixed; 'other' is a bucket like any other. */
export const BUCKETS = [
  'fragrance',
  'skincare',
  'eyes',
  'lips',
  'body',
  'cheek',
  'foundation',
  'concealer',
  'other',
] as const;
export type BucketKey = (typeof BUCKETS)[number];

/**
 * Why a side (or a row's gap) has no figure: the API's shared Reason union, kept as sent so a
 * value added later still reads (the UI looks it up in the `reasons` messages when it knows it).
 */
export type SideReason = Reason | (string & {});

export interface Side {
  n: number;
  median: Money | null;
  mean: Money | null;
  p25: Money | null;
  p75: Money | null;
  min: Money | null;
  max: Money | null;
  /** 'blocked' is the retailer withholding collection, not a thin cohort. */
  status: 'ok' | 'too_few' | 'blocked';
  /** Any non-null reason means no figures; only 'retailer_blocked' is 'blocked'. */
  reason: SideReason | null;
}

export interface Bucket {
  key: BucketKey;
  label: { en: string; ar: string } | null;
  /** By retailer id, for both retailers of the pair. */
  sides: Record<string, Side>;
  /** (other.median − base.median) / base.median × 100; positive means `other` is dearer. */
  gapPct: string | null;
  /** other.median − base.median, when the API sent it. */
  gapAmount: Money | null;
  /** The cheaper retailer's id, 'same', or null when not computed. */
  cheaper: string | null;
  /** 'ok' only when both sides are ok and a gap was computed. */
  status: 'ok' | 'too_few' | 'blocked';
}

export type UnmappedReason = 'no_breadcrumb' | 'no_rule' | 'ambiguous';
const UNMAPPED_REASONS: readonly string[] = ['no_breadcrumb', 'no_rule', 'ambiguous'];

export interface CategoryCompare {
  level: 'bucket';
  /** [base, other] */
  retailers: [string, string];
  /** The API's minimum cohort for a side to carry a figure. */
  minN: number;
  gapConvention: 'other_vs_base_median_pct';
  buckets: Bucket[];
  /** Share of each retailer's priced products in 'other', as a decimal-string percentage. */
  otherShare: Record<string, string>;
  /** Source categories not mapped to a bucket yet, with their product counts (may be a sample). */
  unmapped: { retailer: string; category: string; reason: UnmappedReason | null; n: number }[];
  /** How many unmapped paths there are in all, listed or not. */
  unmappedPaths: number;
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null;
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const DECIMAL = /^-?\d+(\.\d+)?$/;
const decimal = (v: unknown): string | null => (typeof v === 'string' && DECIMAL.test(v) ? v : null);

/** A money value as the API sends it; anything else is null (a missing price, never 0). */
function money(v: unknown): Money | null {
  if (!isObj(v) || typeof v.amount !== 'string' || !DECIMAL.test(v.amount) || typeof v.currency !== 'string')
    return null;
  return {
    amount: v.amount,
    currency: v.currency,
    minor: isNum(v.minor) ? v.minor : Math.round(Number(v.amount) * 100),
  };
}

/** A side with too few products to compare: nothing but its count (and the API's reason). */
export const tooFewSide = (n = 0, reason: SideReason | null = null): Side => ({
  n,
  median: null,
  mean: null,
  p25: null,
  p75: null,
  min: null,
  max: null,
  status: reason === 'retailer_blocked' ? 'blocked' : 'too_few',
  reason,
});

/**
 * One wire Cell. Too few when the API flags it, gives any reason, sends no median, or the count
 * is under the minimum cohort; a blocked retailer is 'blocked', not too few.
 */
function side(raw: unknown, minN: number): Side {
  if (!isObj(raw)) return tooFewSide();
  const v = raw as Partial<WireCell>;
  const n = isNum(v.n) && v.n >= 0 ? v.n : 0;
  const reason = typeof v.reason === 'string' && v.reason.length > 0 ? v.reason : null;
  const median = money(v.median);
  if (v.tooFew === true || reason !== null || !median || n < minN) return tooFewSide(n, reason);
  return {
    n,
    median,
    mean: money(v.mean),
    p25: money(v.p25),
    p75: money(v.p75),
    min: money(v.min),
    max: money(v.max),
    status: 'ok',
    reason: null,
  };
}

/** One wire CategoryRow for a key: the API's when well-formed, else too few; never dropped, never 0. */
function bucket(key: BucketKey, raw: unknown, retailers: [string, string], minN: number): Bucket {
  const [base, other] = retailers;
  const row: Partial<WireRow> = isObj(raw) ? raw : {};
  const sides = { [base]: side(row.base, minN), [other]: side(row.other, minN) };
  const label =
    isObj(row.label) && typeof row.label.en === 'string' && typeof row.label.ar === 'string'
      ? { en: row.label.en, ar: row.label.ar }
      : null;
  const gap: Partial<WireGap> | null = isObj(row.gap) ? row.gap : null;
  const gapPct = gap ? decimal(gap.pct) : null;
  const cheaper =
    gap?.cheaper === 'base'
      ? base
      : gap?.cheaper === 'other'
        ? other
        : gap?.cheaper === 'equal'
          ? 'same'
          : null;
  const blocked =
    sides[base]!.status === 'blocked' ||
    sides[other]!.status === 'blocked' ||
    row.gapReason === 'retailer_blocked';
  // The API's gap is the figure; without one (gap null) the row's gap and chip are suppressed.
  const ok = !blocked && sides[base]!.status === 'ok' && sides[other]!.status === 'ok' && gapPct !== null;
  return {
    key,
    label,
    sides,
    gapPct: ok ? gapPct : null,
    gapAmount: ok && gap ? money(gap.amount) : null,
    cheaper: ok ? cheaper : null,
    status: blocked ? 'blocked' : ok ? 'ok' : 'too_few',
  };
}

/**
 * Reads a /category-compare body (DC's CategoryComparison) defensively: a body that is not that
 * shape is null; the rows come back as buckets in the fixed order (the API ranks them by count),
 * a missing or malformed one as too few (it is never left out and never reads as 0); unknown
 * row keys are ignored.
 */
export function parseCategoryCompare(body: unknown): CategoryCompare | null {
  if (!isObj(body)) return null;
  const raw = body as Partial<Wire>;
  if (raw.level !== 'bucket' || !Array.isArray(raw.rows)) return null;
  const { base, other } = raw;
  if (typeof base !== 'string' || typeof other !== 'string' || base === other) return null;
  const retailers: [string, string] = [base, other];
  const minN = isNum(raw.minCohort) && raw.minCohort > 0 ? raw.minCohort : 1;
  const byKey = new Map<string, unknown>();
  for (const r of raw.rows as unknown[])
    if (isObj(r) && typeof r.key === 'string' && !byKey.has(r.key)) byKey.set(r.key, r);
  const otherShare: Record<string, string> = {};
  const coverage: Partial<Wire['coverage']> = isObj(raw.coverage) ? raw.coverage : {};
  for (const [side, id] of [
    ['base', base],
    ['other', other],
  ] as const) {
    const c = coverage[side];
    const v = isObj(c) ? decimal(c.otherPct) : null;
    if (v !== null) otherShare[id] = v;
  }
  const unmapped = Array.isArray(raw.unmapped)
    ? (raw.unmapped as unknown[]).flatMap((x) => {
        const u = (isObj(x) ? x : {}) as Partial<WireUnmapped>;
        return isObj(x) &&
          typeof u.retailer === 'string' &&
          Array.isArray(u.path) &&
          u.path.every((s) => typeof s === 'string') &&
          isNum(u.n) &&
          u.n > 0
          ? [
              {
                retailer: u.retailer,
                category: (u.path as string[]).join(' › '),
                reason:
                  typeof u.reason === 'string' && UNMAPPED_REASONS.includes(u.reason)
                    ? (u.reason as UnmappedReason)
                    : null,
                n: u.n,
              },
            ]
          : [];
      })
    : [];
  return {
    level: 'bucket',
    retailers,
    minN,
    gapConvention: 'other_vs_base_median_pct',
    buckets: BUCKETS.map((k) => bucket(k, byKey.get(k), retailers, minN)),
    otherShare,
    unmapped,
    unmappedPaths: isNum(raw.unmappedPaths) && raw.unmappedPaths >= 0 ? raw.unmappedPaths : unmapped.length,
  };
}

/** One /category-compare call for a pair; a body that is not the contract's shape is `data: null`. */
export async function fetchCategoryCompare(
  api: ApiClient,
  pair: { base: string; other: string },
  signal?: AbortSignal,
): Promise<Envelope<CategoryCompare>> {
  const env = await api.get('/api/v1/category-compare', {
    query: { retailers: `${pair.base},${pair.other}`, level: 'bucket' },
    signal,
  });
  return { ...env, data: env.data == null ? null : parseCategoryCompare(env.data) };
}
