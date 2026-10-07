/**
 * Pure shaping for the Overview: who leads on the matched set, who is cheaper by category, and
 * the bar widths. No React, so it is unit-tested; every figure comes from the API's own counts and
 * decimal strings, never recomputed from the rows on screen. `verdict`, `minus` and `sign` match
 * the Compare page's helpers (components/compare/model.ts) so the two can be folded into one
 * module. A shop's colour comes from components/ui/retailer-dot.tsx, the one table the whole app uses.
 */
import { BUCKETS, type Bucket, type BucketKey } from '@/lib/api/category-compare';
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

type Group = Schemas['Group'];

/** One category on the Overview's table: its whole-range row and its matched group, either missing. */
export interface CategoryLine {
  key: BucketKey;
  bucket: Bucket | null;
  group: Group | null;
}

/** A matched group the API summarised: at or above its cohort minimum, with counts to read. */
export const groupOk = (g: Group | null): g is Group & { summary: CompareSummary } =>
  g !== null && g.status === 'ok' && g.summary !== null;

/**
 * The categories the Overview's table shows, and the ones it folds into one "not enough data"
 * row: a category shows when the API computed its range gap or summarised its matched pairs.
 * Shown rows rank by the range gap, widest first; the rest keep the fixed bucket order. Group
 * keys are /compare's top-level category codes, the same nine as the buckets; any other is ignored.
 */
export function categoryLines(
  buckets: readonly Bucket[],
  groups: readonly Group[],
): { shown: CategoryLine[]; thin: CategoryLine[] } {
  const byKey = new Map(groups.map((g) => [g.key, g]));
  const lines = BUCKETS.map((key) => ({
    key,
    bucket: buckets.find((b) => b.key === key) ?? null,
    group: byKey.get(key) ?? null,
  }));
  const gap = (l: CategoryLine) =>
    l.bucket?.status === 'ok' && l.bucket.gapPct !== null ? Math.abs(Number(l.bucket.gapPct)) : -1;
  const shown = lines
    .filter((l) => gap(l) >= 0 || groupOk(l.group))
    .map((l, i) => ({ l, i, g: gap(l) }))
    .sort((x, y) => (y.g === x.g ? x.i - y.i : y.g - x.g))
    .map((x) => x.l);
  return { shown, thin: lines.filter((l) => !shown.includes(l)) };
}

/** A matched group's leader: the shop cheaper on more of its pairs, or 'even' on a tie. */
export function groupLeader(g: Group & { summary: CompareSummary }, base: string, other: string) {
  const a = g.summary.cheaperCounts[base] ?? 0;
  const b = g.summary.cheaperCounts[other] ?? 0;
  return { a, b, e: g.summary.equalCount, n: g.summary.n, who: a === b ? 'even' : a > b ? base : other };
}

export interface CategoryRead {
  /** Categories whose matched pairs the API summarised. */
  compared: number;
  base: number;
  other: number;
}

/**
 * The finding behind the category card's title: in how many categories the same product is
 * cheaper at each shop more often, from the API's per-category matched counts. The whole-range
 * medians never decide it: a lower median reflects the range a shop stocks, not its prices.
 */
export function matchedRead(lines: readonly CategoryLine[], base: string, other: string): CategoryRead {
  const read: CategoryRead = { compared: 0, base: 0, other: 0 };
  for (const l of lines) {
    if (!groupOk(l.group)) continue;
    read.compared++;
    const { who } = groupLeader(l.group, base, other);
    if (who === base) read.base++;
    else if (who === other) read.other++;
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

/**
 * Discounted products per depth band, summed over the categories /summary counted, in the API's
 * band order; `total` is the sum. The bands are the API's own labels ("10-20", "50+").
 */
export function depthBands(d: { bands: readonly string[]; cells: readonly (readonly number[])[] }): {
  bands: { band: string; n: number }[];
  total: number;
} {
  const bands = d.bands.map((band, ci) => ({
    band,
    n: d.cells.reduce((s, row) => s + (Number.isFinite(row[ci]) ? row[ci]! : 0), 0),
  }));
  return { bands, total: bands.reduce((s, b) => s + b.n, 0) };
}

/**
 * Which discount band leads, and how strongly: 'most' when it holds more than half the discounted
 * products, 'largest' when it holds the most but not half, 'tie' when two or more bands share the
 * top count (no band is named then). Null when nothing is counted.
 */
export type LeadingBand =
  { kind: 'most' | 'largest'; band: string; n: number; total: number } | { kind: 'tie'; total: number };

export function leadingBand(d: {
  bands: readonly string[];
  cells: readonly (readonly number[])[];
}): LeadingBand | null {
  const { bands, total } = depthBands(d);
  if (total === 0) return null;
  const top = Math.max(...bands.map((b) => b.n));
  const leaders = bands.filter((b) => b.n === top);
  if (leaders.length > 1) return { kind: 'tie', total };
  const { band, n } = leaders[0]!;
  return { kind: n * 2 > total ? 'most' : 'largest', band, n, total };
}

/**
 * Launches per day summed across the shops whose dates are complete. A shop the API cut
 * (`perDay` null), still loading, or without two collection days is not in the sum, so
 * `partial` says the total covers only `covered`, by name, never all shops.
 */
export function launchTotals<S extends { name: string; perDay: readonly { date: string; n: number }[] }>(
  shops: number,
  series: readonly S[],
): { total: number; peak: { date: string; n: number } | null; covered: string[]; partial: boolean } {
  const byDay = new Map<string, number>();
  for (const s of series) for (const d of s.perDay) byDay.set(d.date, (byDay.get(d.date) ?? 0) + d.n);
  const days = [...byDay].map(([date, n]) => ({ date, n }));
  return {
    total: days.reduce((a, d) => a + d.n, 0),
    peak: peakDay(days),
    covered: series.map((s) => s.name),
    partial: series.length < shops,
  };
}

/** The day with the most launches in a window; null when there were none. */
export function peakDay(days: readonly { date: string; n: number }[]): { date: string; n: number } | null {
  let best: { date: string; n: number } | null = null;
  for (const d of days) if (d.n > 0 && (best === null || d.n > best.n)) best = d;
  return best;
}
