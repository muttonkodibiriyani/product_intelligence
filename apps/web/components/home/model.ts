/**
 * Pure shaping for the Overview: who leads on the matched set, who is cheaper by category, and
 * the bar widths. No React, so it is unit-tested; every figure comes from the API's own counts and
 * decimal strings, never recomputed from the rows on screen. `verdict`, `minus` and `sign` match
 * the Compare page's helpers (components/compare/model.ts) so the two can be folded into one
 * module. A shop's colour comes from components/ui/retailer-dot.tsx, the one table the whole app uses.
 */
import type { Bucket } from '@/lib/api/category-compare';
import type { CaveatView, Money, Schemas } from '@/lib/api/types';

type CompareSummary = Schemas['CompareSummary'];

/**
 * The early sample items /compare left out, from its own `early_excluded` caveat (the API sends
 * it only when the count is above zero). Null without the caveat or a readable count: the read
 * is then not "early", whatever `total` says, since `total` also counts unreviewed, unmatched and
 * single-shop products.
 */
export function earlyExcluded(
  caveats: readonly CaveatView[] | null | undefined,
): { count: number; caveat: CaveatView } | null {
  const caveat = caveats?.find((c) => c.code === 'early_excluded');
  if (!caveat) return null;
  const count = Number(caveat.params?.count);
  return Number.isInteger(count) && count > 0 ? { count, caveat } : null;
}

export type Verdict =
  | { kind: 'allSame'; n: number }
  | { kind: 'tie'; k: number; n: number; equal: number }
  | { kind: 'lead'; leader: 'base' | 'other'; k: number; trailing: number; equal: number; n: number };

/** Who wins more often on the matched products, from the API's own counts. */
export function verdict(s: CompareSummary, base: string, other: string): Verdict {
  const a = s.cheaperCounts[base] ?? 0;
  const b = s.cheaperCounts[other] ?? 0;
  const equal = s.equalCount;
  if (a === 0 && b === 0) return { kind: 'allSame', n: s.n };
  if (a === b) return { kind: 'tie', k: a, n: s.n, equal };
  return a > b
    ? { kind: 'lead', leader: 'base', k: a, trailing: b, equal, n: s.n }
    : { kind: 'lead', leader: 'other', k: b, trailing: a, equal, n: s.n };
}

export interface CategoryRead {
  /** Buckets with a gap the API computed. */
  compared: number;
  base: number;
  other: number;
  same: number;
}

/**
 * The category read behind the headline when no products are matched yet: in how many of the
 * compared buckets each shop's median is the lower one, as the API's `cheaper` says.
 */
export function categoryRead(buckets: readonly Bucket[], base: string, other: string): CategoryRead {
  const read: CategoryRead = { compared: 0, base: 0, other: 0, same: 0 };
  for (const b of buckets) {
    if (b.status !== 'ok' || b.gapPct === null) continue;
    read.compared++;
    const who = bucketCheaper(b, base, other);
    if (who === base) read.base++;
    else if (who === other) read.other++;
    else read.same++;
  }
  return read;
}

/**
 * The cheaper side of a bucket: the API's verdict first, else the sign of its gap (negative means
 * `other` is cheaper); 'same' at zero or when the API said so.
 */
export function bucketCheaper(b: Bucket, base: string, other: string): string | 'same' | null {
  if (b.status !== 'ok' || b.gapPct === null) return null;
  if (b.cheaper === 'same' || b.cheaper === base || b.cheaper === other) return b.cheaper;
  const s = sign(b.gapPct);
  return s === 0 ? 'same' : s < 0 ? other : base;
}

/**
 * other − base of two API money values, on their integer minor units (no floating point), as a
 * money value in the same currency; null across currencies or when either amount is not an integer
 * count of minor units.
 */
export function minus(other: Money, base: Money): Money | null {
  if (other.currency !== base.currency) return null;
  if (!Number.isInteger(other.minor) || !Number.isInteger(base.minor)) return null;
  const minor = other.minor - base.minor;
  const decimals = (base.amount.split('.')[1] ?? '').length;
  const abs = Math.abs(minor)
    .toString()
    .padStart(decimals + 1, '0');
  const amount =
    (minor < 0 ? '-' : '') + (decimals ? `${abs.slice(0, -decimals)}.${abs.slice(-decimals)}` : abs);
  return { amount, currency: base.currency, minor };
}

/** |m|: the same money value with its sign dropped. */
export const abs = (m: Money): Money => ({
  ...m,
  amount: m.amount.replace(/^-/, ''),
  minor: Math.abs(m.minor),
});

/** Sign of an API decimal string: 1 above zero, -1 below, 0 at zero (or unreadable). */
export function sign(v: string | null | undefined): -1 | 0 | 1 {
  if (!v || !/^-?\d+(\.\d+)?$/.test(v)) return 0;
  const n = Number(v);
  return n > 0 ? 1 : n < 0 ? -1 : 0;
}

/** A count as a share of the largest one shown, 0…100, for an inline bar; 0 when nothing is. */
export function share(n: number, max: number): number {
  if (!(max > 0) || !(n > 0)) return 0;
  return Math.round(Math.min(1, n / max) * 1000) / 10;
}

/** |pct| as a share of the widest gap shown, 0…50: the gap bar's fill is half the bar at most. */
export function gapWidth(pct: string, maxAbs: number): number {
  const v = Math.abs(Number(pct));
  if (!(maxAbs > 0) || !Number.isFinite(v) || v === 0) return 0;
  return Math.round(Math.min(1, v / maxAbs) * 500) / 10;
}

/** The widest |gap| among the buckets the API compared. */
export function widestGap(buckets: readonly Bucket[]): number {
  return buckets.reduce((m, b) => {
    const v = b.status === 'ok' && b.gapPct !== null ? Math.abs(Number(b.gapPct)) : 0;
    return Number.isFinite(v) ? Math.max(m, v) : m;
  }, 0);
}

/** The deepest cut among the top discounts, as the API's decimal string; null without any. */
export function deepestCut(top: readonly { depthPct: string }[]): string | null {
  let best: string | null = null;
  for (const d of top) {
    const v = Number(d.depthPct);
    if (!Number.isFinite(v)) continue;
    if (best === null || v > Number(best)) best = d.depthPct;
  }
  return best;
}
